"""Worker-safe generation of resident Material Authority DDS resources."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path


def material_authority_resource_backend_available() -> bool:
    from cdmw.core.texture_native import find_directxtex_texture_binary

    return find_directxtex_texture_binary() is not None


def _resource_id(material_index: int, material_name: object, channel: object) -> str:
    identity = (
        f"material_authority|{material_index}|{str(material_name or '').strip().casefold()}|"
        f"{str(channel or '').strip().casefold()}"
    )
    return f"material:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _original_slot_path(texture_set: object, channel: str) -> str:
    slots = getattr(texture_set, "slots", {}) or {}
    aliases = {
        "material_mask": ("material_mask", "material", "roughness", "metallic", "metalness", "ao"),
    }.get(channel, (channel,))
    for alias in aliases:
        slot = slots.get(alias) if isinstance(slots, Mapping) else None
        path = str(getattr(slot, "source_path", "") or "") if slot is not None else ""
        if path:
            return path
    return ""


def _owned_name(index: int, material_name: object, channel: str) -> str:
    safe_material = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(material_name or "material")
    ).strip("_") or "material"
    return f"{index:04d}_{safe_material[:80]}_{channel}.dds"


def _copy_cancellable(source: Path, target: Path, stop_event: threading.Event) -> None:
    from cdmw.core.atomic_file import atomic_binary_writer
    from cdmw.domain.cancellation import raise_if_cancelled

    raise_if_cancelled(stop_event, "Material resource generation cancelled.")
    with source.open("rb") as source_handle, atomic_binary_writer(target) as target_handle:
        while chunk := source_handle.read(1024 * 1024):
            raise_if_cancelled(stop_event, "Material resource generation cancelled.")
            target_handle.write(chunk)


def _channel_preset_key(channel: str) -> str:
    return {
        "base": "base_color",
        "normal": "normal",
        "height": "height_scalar",
        "roughness": "height_scalar",
        "metallic": "height_scalar",
        "metalness": "height_scalar",
        "occlusion": "height_scalar",
        "material_mask": "mask_packed",
        "emissive": "emissive",
    }.get(str(channel or "").strip().lower(), "mask_packed")


def _preview_dds_format(
    canonical_format: str,
    *,
    width: int,
    height: int,
    mip_count: int,
    max_uncompressed_bytes: int,
) -> str:
    """Choose a fast, lossless preview format without changing saved artifacts."""

    replacements = {
        "BC7_UNORM": "R8G8B8A8_UNORM",
        "BC7_UNORM_SRGB": "R8G8B8A8_UNORM_SRGB",
    }
    replacement = replacements.get(str(canonical_format or "").strip().upper())
    if replacement is None or int(max_uncompressed_bytes) <= 0:
        return canonical_format
    level_width = max(1, int(width))
    level_height = max(1, int(height))
    projected_bytes = 148  # DDS magic, header, and the largest possible DX10 header.
    for _level in range(max(1, int(mip_count))):
        projected_bytes += level_width * level_height * 4
        level_width = max(1, level_width // 2)
        level_height = max(1, level_height // 2)
    return replacement if projected_bytes <= int(max_uncompressed_bytes) else canonical_format


def _projected_rgba_dds_bytes(width: int, height: int, mip_count: int) -> int:
    projected_bytes = 148
    level_width = max(1, int(width))
    level_height = max(1, int(height))
    for _level in range(max(1, int(mip_count))):
        projected_bytes += level_width * level_height * 4
        level_width = max(1, level_width // 2)
        level_height = max(1, level_height // 2)
    return projected_bytes


def _bounded_image_dimensions(
    width: int,
    height: int,
    max_dimension: int,
) -> tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    max_dimension = max(0, int(max_dimension))
    if max_dimension <= 0 or max(width, height) <= max_dimension:
        return width, height
    if width >= height:
        return max_dimension, max(1, round(height * max_dimension / width))
    return max(1, round(width * max_dimension / height)), max_dimension


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_content_addressed_dds(
    source: Path,
    content_sha256: str,
    stop_event: threading.Event,
) -> Path:
    root = Path(tempfile.gettempdir()) / "cdmw-material-authority-artifacts-v1"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{content_sha256}.dds"
    if target.is_file():
        if _file_sha256(target) != content_sha256:
            raise ValueError("Content-addressed Material Authority DDS cache hash mismatch.")
        return target
    _copy_cancellable(source, target, stop_event)
    if _file_sha256(target) != content_sha256:
        target.unlink(missing_ok=True)
        raise ValueError("Published Material Authority DDS failed hash readback.")
    return target


def _owned_dds_artifact(
    target: Path,
    *,
    output_format: str,
    output_srgb: bool,
    preset: object,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> dict[str, object]:
    from cdmw.core.dds_native import inspect_dds_native_path

    info = inspect_dds_native_path(target)
    expected_mips = int(getattr(preset, "mip_count", 0) or 0)
    if info.width <= 0 or info.height <= 0 or info.mip_count <= 0 or info.reason:
        raise ValueError(f"Generated DDS failed readback: {info.reason or 'invalid DDS metadata'}")
    if (
        expected_width is not None
        and expected_height is not None
        and (
            int(info.width) != int(expected_width)
            or int(info.height) != int(expected_height)
        )
    ):
        raise ValueError(
            "Generated DDS has the wrong preview dimensions: expected "
            f"{expected_width}x{expected_height}, got {info.width}x{info.height}"
        )
    if (
        str(info.format_name or "").strip().upper() != output_format
        or int(info.mip_count) != expected_mips
        or bool(info.srgb) != bool(output_srgb)
    ):
        raise ValueError(
            f"Generated DDS has the wrong preview contract: expected {output_format}/"
            f"{expected_mips} mips/{'srgb' if output_srgb else 'linear'}, got "
            f"{info.format_name}/{info.mip_count} mips/{'srgb' if info.srgb else 'linear'}"
        )
    canonical_format = str(getattr(preset, "dds_format", "") or "").strip().upper()
    preset_value = getattr(preset, "preset", None)
    return {
        "content_sha256": _file_sha256(target),
        "byte_count": int(target.stat().st_size),
        "dds_format": str(info.format_name or output_format),
        "width": int(info.width),
        "height": int(info.height),
        "mip_count": int(info.mip_count),
        "color_space": "srgb" if info.srgb else "linear",
        "preset": str(getattr(preset_value, "key", "") or ""),
        "preview_uncompressed": output_format != canonical_format,
    }


def _encode_owned_image_dds_batch(
    jobs: Sequence[tuple[Path, Path, str]],
    stop_event: threading.Event,
    *,
    source_color_policy: str = "auto",
    preview_uncompressed_max_bytes: int = 0,
    max_dimension: int = 0,
) -> tuple[dict[str, object], ...]:
    """Encode external preview images with one native-helper invocation."""

    from PIL import Image

    from cdmw.core.texture_native import (
        NativeTextureEncodeRequest,
        encode_dds_batch_with_directxtex,
    )
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset

    if not jobs:
        return ()
    with tempfile.TemporaryDirectory(prefix="cdmw-material-images-") as normalized_root:
        remaining_budget = max(0, int(preview_uncompressed_max_bytes))
        requests: list[NativeTextureEncodeRequest] = []
        plans: list[tuple[Path, str, bool, object, str, int, int]] = []
        for raw_source, raw_target, channel in jobs:
            raise_if_cancelled(stop_event, "Material DDS generation cancelled.")
            source = Path(raw_source)
            target = Path(raw_target)
            if source.suffix.lower() == ".dds":
                raise ValueError("External preview image batch cannot contain DDS input.")
            with Image.open(source) as image:
                width, height = _bounded_image_dimensions(
                    image.width,
                    image.height,
                    max_dimension,
                )
                # The native encoder accepts PNG bytes only. External scene textures
                # also arrive as JPEG/TGA/WebP, so normalize an owned temporary copy.
                if image.format != "PNG":
                    source = Path(normalized_root) / f"{len(requests):04d}.png"
                    with image.convert("RGBA") as rgba:
                        rgba.save(source, format="PNG")
            preset = resolve_texture_editor_dds_preset(
                _channel_preset_key(channel),
                width=width,
                height=height,
            )
            output_format = _preview_dds_format(
                preset.dds_format,
                width=width,
                height=height,
                mip_count=preset.mip_count,
                max_uncompressed_bytes=remaining_budget,
            )
            if output_format != preset.dds_format:
                remaining_budget = max(
                    0,
                    remaining_budget
                    - _projected_rgba_dds_bytes(width, height, preset.mip_count),
                )
            output_srgb = output_format.endswith("_SRGB")
            target.parent.mkdir(parents=True, exist_ok=True)
            requests.append(
                NativeTextureEncodeRequest(
                    input_path=source,
                    output_path=target,
                    dds_format=output_format,
                    width=width,
                    height=height,
                    mip_count=preset.mip_count,
                    overwrite=True,
                    source_color_policy=source_color_policy,
                )
            )
            plans.append(
                (target, output_format, output_srgb, preset, str(channel), width, height)
            )

        reports = encode_dds_batch_with_directxtex(
            requests,
            timeout_seconds=60.0,
            stop_event=stop_event,
        )
        artifacts: list[dict[str, object]] = []
        for target, output_format, output_srgb, preset, channel, width, height in plans:
            report = reports.get(str(target))
            if not report or not target.is_file():
                raise RuntimeError(f"Native DirectXTex DDS encode failed for {channel}.")
            raise_if_cancelled(stop_event, "Material DDS generation cancelled.")
            artifacts.append(
                _owned_dds_artifact(
                    target,
                    output_format=output_format,
                    output_srgb=output_srgb,
                    preset=preset,
                    expected_width=width,
                    expected_height=height,
                )
            )
        return tuple(artifacts)


def _encode_owned_dds(
    source: Path,
    target: Path,
    channel: str,
    stop_event: threading.Event,
    *,
    source_color_policy: str = "auto",
    preview_uncompressed_max_bytes: int = 0,
) -> dict[str, object]:
    from cdmw.core.dds_native import inspect_dds_native_path
    from cdmw.core.texture_native import (
        decode_dds_preview_with_directxtex,
        encode_dds_with_directxtex,
    )
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset

    if source.suffix.lower() != ".dds":
        return _encode_owned_image_dds_batch(
            ((source, target, channel),),
            stop_event,
            source_color_policy=source_color_policy,
            preview_uncompressed_max_bytes=preview_uncompressed_max_bytes,
        )[0]

    decoded_source: Path | None = None
    source_info = inspect_dds_native_path(source)
    if source_info.width <= 0 or source_info.height <= 0 or source_info.reason:
        raise ValueError(
            f"Source {channel} DDS failed readback: {source_info.reason or 'invalid DDS metadata'}"
        )
    width, height = int(source_info.width), int(source_info.height)
    preset = resolve_texture_editor_dds_preset(
        _channel_preset_key(channel),
        width=width,
        height=height,
    )
    output_format = _preview_dds_format(
        preset.dds_format,
        width=width,
        height=height,
        mip_count=preset.mip_count,
        max_uncompressed_bytes=preview_uncompressed_max_bytes,
    )
    output_srgb = output_format.endswith("_SRGB")
    canonical_source = (
        str(source_info.format_name or "").strip().upper() == output_format
        and int(source_info.mip_count) == int(preset.mip_count)
        and bool(source_info.srgb) == bool(output_srgb)
    )
    if canonical_source:
        _copy_cancellable(source, target, stop_event)
    else:
        decoded_source = target.with_name(f".{target.stem}.decoded.png")
        report = decode_dds_preview_with_directxtex(
            source,
            decoded_source,
            max_dimension=max(width, height),
            slot_kind=channel,
            requested_mip=0,
            output_pixel_type="rgba8",
            timeout_seconds=60.0,
            stop_event=stop_event,
        )
        if not report or not decoded_source.is_file():
            raise RuntimeError(f"Native DirectXTex DDS decode failed for {channel}.")
    if decoded_source is not None:
        staged = target.with_name(f".{target.stem}.encoding.dds")
        try:
            report = encode_dds_with_directxtex(
                decoded_source,
                staged,
                dds_format=output_format,
                width=width,
                height=height,
                mip_count=preset.mip_count,
                overwrite=True,
                source_color_policy=source_color_policy,
                timeout_seconds=60.0,
                stop_event=stop_event,
            )
            if not report or not staged.is_file():
                raise RuntimeError(f"Native DirectXTex DDS encode failed for {channel}.")
            raise_if_cancelled(stop_event, "Material DDS generation cancelled.")
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
            if decoded_source != source:
                decoded_source.unlink(missing_ok=True)
    return _owned_dds_artifact(
        target,
        output_format=output_format,
        output_srgb=output_srgb,
        preset=preset,
    )


def generate_material_authority_resource_bindings(
    texture_sets: Sequence[tuple[str, object]],
    material_profile: object,
    affected_channels: Sequence[str],
    output_root: Path,
    stop_event: threading.Event,
) -> tuple[dict[str, object], ...]:
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.modding.material_replacer import material_authority_preview_texture_slots

    generated_root = output_root / "generated"
    bindings: list[dict[str, object]] = []
    for index, (fallback_name, texture_set) in enumerate(texture_sets):
        raise_if_cancelled(stop_event, "Material resource generation cancelled.")
        material_name = str(getattr(texture_set, "material_name", "") or fallback_name or f"material_{index}")
        slots = material_authority_preview_texture_slots(
            texture_set,
            material_profile,
            enabled=True,
            output_root=generated_root,
            stop_event=stop_event,
        )
        for slot_kind in affected_channels:
            raise_if_cancelled(stop_event, "Material resource generation cancelled.")
            channel = "material" if slot_kind == "material_mask" else slot_kind
            slot = slots.get(slot_kind)
            source = Path(getattr(slot, "source_path", "")) if slot is not None else Path()
            common = {
                "material_name": material_name,
                "resource_id": _resource_id(index, material_name, channel),
                "channel": channel,
                "logical_path": _original_slot_path(texture_set, slot_kind),
            }
            if slot is None or not source.is_file():
                bindings.append({**common, "path": "", "source_dds_path": "", "remove": True})
                continue
            owned = output_root / _owned_name(index, material_name, slot_kind)
            artifact = _encode_owned_dds(source, owned, slot_kind, stop_event)
            artifact_path = _publish_content_addressed_dds(
                owned,
                str(artifact["content_sha256"]),
                stop_event,
            )
            bindings.append(
                {
                    **common,
                    **artifact,
                    "path": str(artifact_path),
                    "source_dds_path": str(artifact_path),
                    "logical_path": str(source),
                    "semantic_type": str(getattr(slot, "semantic_type", "") or ""),
                    "semantic_subtype": str(getattr(slot, "semantic_subtype", "") or ""),
                    "packed_channels": tuple(getattr(slot, "packed_channels", ()) or ()),
                    "source_authority": str(getattr(slot, "source_authority", "") or ""),
                    "remove": False,
                }
            )
    return tuple(bindings)


__all__ = (
    "generate_material_authority_resource_bindings",
    "material_authority_resource_backend_available",
)
