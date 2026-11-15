from __future__ import annotations

"""No-PySide native DDS export service for Texture Editor documents."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional

import numpy as np
from PIL import Image

from cdmw.core import texture_native
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native_path
from cdmw.core.texture_editor_project_io import (
    create_texture_editor_document_from_source as _create_document_from_source,
    load_texture_editor_project as _load_project,
    make_texture_editor_workspace_root as _make_workspace_root,
    save_texture_editor_project as _save_project,
)
from cdmw.core.texture_editor_raster_ops import (
    export_texture_editor_flattened_png as _export_flattened_png,
    export_texture_editor_grid_slices as _export_grid_slices,
    export_texture_editor_region_png as _export_region_png,
)
from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset
from cdmw.models import TextureEditorDocument


class NativeTextureEditorExportError(RuntimeError):
    pass


class TextureEditorService:
    """Project and image I/O boundary for Texture Editor workers."""

    make_workspace_root = staticmethod(_make_workspace_root)
    create_document_from_source = staticmethod(_create_document_from_source)
    load_project = staticmethod(_load_project)
    save_project = staticmethod(_save_project)
    export_flattened_png = staticmethod(_export_flattened_png)
    export_region_png = staticmethod(_export_region_png)
    export_grid_slices = staticmethod(_export_grid_slices)


@dataclass(frozen=True, slots=True)
class TextureEditorNativeDdsOptions:
    output_path: Path
    preset_key: str = "base_color"
    dds_format: str = ""
    mip_mode: str = ""
    overwrite: bool = True
    preview_max_dimension: int = 1024
    preview_output_path: Optional[Path] = None
    temp_root: Optional[Path] = None
    timeout_seconds: float = 60.0


@dataclass(slots=True)
class TextureEditorNativeDdsResult:
    dds_path: Path
    report: Dict[str, object]
    preview_path: Optional[Path] = None
    preview_report: Dict[str, object] = field(default_factory=dict)
    preview_rgba: Optional[np.ndarray] = None


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())
    return "_".join(part for part in cleaned.split("_") if part) or "texture_editor"


def _slot_kind_for_preset(preset_key: str) -> str:
    key = str(preset_key or "").strip().lower()
    if key == "normal":
        return "normal"
    if key == "mask_packed":
        return "mask"
    if key == "height_scalar":
        return "scalar"
    return "base"


def _load_rgba_png(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def _normalized_native_report(
    dds_path: Path,
    native_report: Mapping[str, object],
    *,
    preset_key: str,
    requested_format: str,
    requested_mip_count: int,
) -> Dict[str, object]:
    report = dict(native_report)
    report.setdefault("backend", texture_native.DIRECTXTEX_TEXTURE_BACKEND_ID)
    report.setdefault("native_backend", "directxtex")
    report["output_path"] = str(dds_path)
    report["preset_key"] = str(preset_key)
    report["requested_format"] = str(requested_format)
    report["requested_mip_count"] = int(requested_mip_count)
    try:
        report["output_byte_size"] = int(dds_path.stat().st_size)
    except OSError:
        report["output_byte_size"] = 0
    try:
        info = inspect_dds_native_path(dds_path)
    except Exception:
        info = None
    if info is not None:
        header_report = dds_native_report_dict(dds_path, info, backend="dds_native_header")
        report["actual_dxgi_format"] = str(report.get("format") or header_report.get("format") or "")
        if header_report.get("format"):
            report["format"] = header_report["format"]
        for key in ("dxgi_format", "width", "height", "mip_count", "compressed_family", "srgb", "supported_compressed", "supported_uncompressed"):
            report[key] = header_report.get(key)
        report["compressed"] = bool(header_report.get("supported_compressed"))
        report["inspect_report"] = header_report
    return report


def native_texture_editor_backend_available() -> bool:
    return texture_native.find_directxtex_texture_binary() is not None


def native_texture_editor_backend_status_text() -> str:
    return "Native DDS: cd-texture-dx ready." if native_texture_editor_backend_available() else "Native DDS: cd-texture-dx missing."


_BLOCK_BYTES = {"BC1": 8, "BC4": 8, "BC2": 16, "BC3": 16, "BC5": 16, "BC6H": 16, "BC7": 16}
_PIXEL_BYTES = {"R8G8B8A8": 4, "B8G8R8A8": 4, "B8G8R8X8": 4, "R8G8": 2, "R8": 1, "A8": 1}


def _dds_payload_bytes(dds_format: str, width: int, height: int, mip_count: int) -> Optional[int]:
    """The bytes a complete DDS of this format holds after its header, or None when not known here."""
    name = str(dds_format or "").upper()
    family = name.split("_", 1)[0]
    total = 0
    for level in range(max(1, int(mip_count))):
        w, h = max(1, int(width) >> level), max(1, int(height) >> level)
        if family in _BLOCK_BYTES:
            total += ((w + 3) // 4) * ((h + 3) // 4) * _BLOCK_BYTES[family]
        elif family in _PIXEL_BYTES:
            total += w * h * _PIXEL_BYTES[family]
        else:
            return None
    return total

@dataclass(slots=True)
class TextureEditorNativeDdsService:
    settings: object | None = None

    def export_dds(
        self,
        document: TextureEditorDocument,
        layer_pixels: Mapping[str, np.ndarray],
        options: TextureEditorNativeDdsOptions,
    ) -> TextureEditorNativeDdsResult:
        if texture_native.find_directxtex_texture_binary() is None:
            raise NativeTextureEditorExportError("Native DirectXTex texture backend cd-texture-dx is missing.")
        resolved = resolve_texture_editor_dds_preset(
            options.preset_key,
            width=document.width,
            height=document.height,
            dds_format=options.dds_format,
            mip_mode=options.mip_mode,
        )
        dds_path = Path(options.output_path).expanduser().resolve()
        temp_parent = Path(options.temp_root).expanduser().resolve() if options.temp_root is not None else None
        if temp_parent is not None:
            temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cdmw_texture_editor_", dir=str(temp_parent) if temp_parent is not None else None) as temp_dir:
            png_path = Path(temp_dir) / f"{_safe_slug(document.title)}.png"
            _export_flattened_png(document, layer_pixels, png_path)
            report = texture_native.encode_dds_with_directxtex(
                png_path,
                dds_path,
                dds_format=resolved.dds_format,
                width=document.width,
                height=document.height,
                mip_count=resolved.mip_count,
                overwrite=options.overwrite,
                timeout_seconds=options.timeout_seconds,
            )
        if not report:
            raise NativeTextureEditorExportError("Native DirectXTex DDS export failed.")
        normalized = _normalized_native_report(
            dds_path,
            report,
            preset_key=resolved.preset.key,
            requested_format=resolved.dds_format,
            requested_mip_count=resolved.mip_count,
        )
        if resolved.warning:
            normalized["warning"] = resolved.warning
        return TextureEditorNativeDdsResult(dds_path=dds_path, report=normalized)

    def export_matching_original(
        self,
        document: TextureEditorDocument,
        layer_pixels: Mapping[str, np.ndarray],
        original,
        output_path: Path,
        *,
        overwrite: bool = True,
        temp_root: Optional[Path] = None,
        timeout_seconds: float = 60.0,
    ) -> TextureEditorNativeDdsResult:
        """Write the document in the original texture's format, colour space and mip chain.

        `original` is an `OriginalTextureOutput` (cdmw.domain.textures.original_output);
        a format the encoder cannot write was refused when it was made. The size is the
        document's. The written header is checked against the request, so a helper that
        writes something else is an error rather than a silent conversion.
        """
        if (int(document.width), int(document.height)) != (original.width, original.height):
            raise ValueError("The output settings were made for another size; make them again for this document.")
        return self._encode_matching_original(
            lambda png_path: _export_flattened_png(document, layer_pixels, png_path),
            _safe_slug(document.title), original, output_path,
            overwrite=overwrite, temp_root=temp_root, timeout_seconds=timeout_seconds)

    def export_rgba_matching_original(
        self,
        rgba: np.ndarray,
        original,
        output_path: Path,
        *,
        temp_root: Optional[Path] = None,
        timeout_seconds: float = 60.0,
    ) -> TextureEditorNativeDdsResult:
        """`export_matching_original` for a flattened uint8 RGBA image (Mesh Editor live edits)."""

        pixels = np.ascontiguousarray(np.asarray(rgba, dtype=np.uint8))
        if pixels.ndim != 3 or pixels.shape[2] != 4:
            raise ValueError("The edited texture is not an RGBA image.")
        if (int(pixels.shape[1]), int(pixels.shape[0])) != (original.width, original.height):
            raise ValueError("The output settings were made for another size; make them again for this document.")
        return self._encode_matching_original(
            lambda png_path: Image.fromarray(pixels, "RGBA").save(png_path),
            "texture", original, output_path,
            overwrite=True, temp_root=temp_root, timeout_seconds=timeout_seconds)

    def _encode_matching_original(self, write_png, title, original, output_path, *, overwrite, temp_root,
                                  timeout_seconds) -> TextureEditorNativeDdsResult:
        from cdmw.domain.textures.original_output import OriginalTextureOutput, TextureOutputRefused

        if not isinstance(original, OriginalTextureOutput):
            raise TypeError("export_matching_original needs an OriginalTextureOutput.")
        if texture_native.find_directxtex_texture_binary() is None:
            raise NativeTextureEditorExportError("Native DirectXTex texture backend cd-texture-dx is missing.")
        dds_path = Path(output_path).expanduser().resolve()
        # Stage beside the output (the caller's folder), not in the system temp folder.
        temp_parent = Path(temp_root).expanduser().resolve() if temp_root is not None else dds_path.parent
        temp_parent.mkdir(parents=True, exist_ok=True)
        if dds_path.exists() and not overwrite:
            raise FileExistsError(f"Texture output already exists: {dds_path}")
        with tempfile.TemporaryDirectory(prefix="cdmw_texture_editor_", dir=str(temp_parent) if temp_parent is not None else None) as temp_dir:
            png_path = Path(temp_dir) / f"{title}.png"
            staged = Path(temp_dir) / "matched.dds"
            write_png(png_path)
            report = texture_native.encode_dds_with_directxtex(
                png_path,
                staged,
                dds_format=original.dds_format,
                width=original.width,
                height=original.height,
                mip_count=original.mip_count,
                overwrite=True,
                # The flattened PNG carries no colour tag. Its sRGB pixels are already encoded, so
                # say so (as the other untagged-PNG encodes do) rather than let "auto" convert them
                # again; linear data keeps its bytes (H3 of the review).
                source_color_policy="assume_srgb" if original.srgb else "ignore_srgb_metadata",
                timeout_seconds=timeout_seconds,
            )
            if not report:
                raise NativeTextureEditorExportError("Native DirectXTex DDS export failed.")
            normalized = _normalized_native_report(
                staged,
                report,
                preset_key="match_original",
                requested_format=original.dds_format,
                requested_mip_count=original.mip_count,
            )
            written = str(normalized.get("format") or normalized.get("actual_dxgi_format") or "")
            if written and written.upper() != original.dds_format:
                raise TextureOutputRefused(
                    f"The encoder wrote {written} instead of {original.dds_format}; nothing was saved.",
                    dds_format=original.dds_format,
                )
            from cdmw.core.texture_pipeline.inspection import parse_dds

            try:
                header = parse_dds(staged)
                data = staged.read_bytes()
                expected = _dds_payload_bytes(header.dds_format, header.width, header.height, header.mip_count)
                offset = 148 if data[84:88] == b"DX10" else 128
                if expected is not None and len(data) - offset < expected:
                    # The whole file, not only its header: every mip must be there.
                    raise ValueError(f"{len(data) - offset:,} of {expected:,} payload bytes")
            except (OSError, ValueError) as exc:
                raise TextureOutputRefused(f"The encoder wrote an incomplete texture ({exc}); nothing was saved.",
                                           dds_format=original.dds_format) from exc
            if (header.width, header.height) != (original.width, original.height):
                raise TextureOutputRefused(
                    f"The encoder wrote {header.width}x{header.height} instead of {original.width}x{original.height}; "
                    "nothing was saved.", dds_format=original.dds_format)
            written_srgb = normalized.get("srgb")
            if written_srgb is not None and bool(written_srgb) != original.srgb:
                raise TextureOutputRefused(
                    f"The encoder wrote {'sRGB' if written_srgb else 'linear'} colour instead of "
                    f"{'sRGB' if original.srgb else 'linear'}; nothing was saved.",
                    dds_format=original.dds_format,
                )
            if normalized.get("mip_count") not in (None, original.mip_count):
                raise TextureOutputRefused(
                    f"The encoder wrote {normalized.get('mip_count')} mips instead of {original.mip_count}; "
                    "nothing was saved.",
                    dds_format=original.dds_format,
                )
            # Only a checked file reaches the output path.
            from cdmw.core.atomic_file import atomic_write_bytes

            dds_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dds_path, staged.read_bytes())
        normalized["output_path"] = str(dds_path)
        return TextureEditorNativeDdsResult(dds_path=dds_path, report=normalized)

    def preview_compressed(
        self,
        document: TextureEditorDocument,
        layer_pixels: Mapping[str, np.ndarray],
        options: TextureEditorNativeDdsOptions,
    ) -> TextureEditorNativeDdsResult:
        result = self.export_dds(document, layer_pixels, options)
        preview_path = (
            Path(options.preview_output_path).expanduser().resolve()
            if options.preview_output_path is not None
            else result.dds_path.with_name(f"{result.dds_path.stem}.preview.png")
        )
        preview_report = texture_native.decode_dds_preview_with_directxtex(
            result.dds_path,
            preview_path,
            max_dimension=max(1, int(options.preview_max_dimension or max(document.width, document.height))),
            slot_kind=_slot_kind_for_preset(options.preset_key),
            srgb="srgb" if bool(result.report.get("srgb")) else "linear",
            timeout_seconds=options.timeout_seconds,
            temp_root=options.temp_root,
        )
        if not preview_report:
            raise NativeTextureEditorExportError("Native DirectXTex compressed preview failed.")
        result.preview_path = preview_path
        result.preview_report = dict(preview_report)
        result.preview_rgba = _load_rgba_png(preview_path)
        return result


__all__ = [
    "NativeTextureEditorExportError",
    "TextureEditorService",
    "TextureEditorNativeDdsOptions",
    "TextureEditorNativeDdsResult",
    "TextureEditorNativeDdsService",
    "native_texture_editor_backend_available",
    "native_texture_editor_backend_status_text",
]
