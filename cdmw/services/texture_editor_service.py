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
from cdmw.core.texture_editor import export_texture_editor_flattened_png
from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset
from cdmw.models import TextureEditorDocument


class NativeTextureEditorExportError(RuntimeError):
    pass


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


def _copy_layer_pixels(layer_pixels: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
    return {str(key): value.copy() for key, value in layer_pixels.items()}


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
            export_texture_editor_flattened_png(document, _copy_layer_pixels(layer_pixels), png_path)
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
    "TextureEditorNativeDdsOptions",
    "TextureEditorNativeDdsResult",
    "TextureEditorNativeDdsService",
    "native_texture_editor_backend_available",
    "native_texture_editor_backend_status_text",
]
