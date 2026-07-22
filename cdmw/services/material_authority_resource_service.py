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
        "material_mask": "mask_packed",
        "emissive": "emissive",
    }.get(str(channel or "").strip().lower(), "mask_packed")


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


def _encode_owned_dds(
    source: Path,
    target: Path,
    channel: str,
    stop_event: threading.Event,
) -> dict[str, object]:
    from cdmw.core.dds_native import inspect_dds_native_path
    from cdmw.core.texture_native import (
        decode_dds_preview_with_directxtex,
        encode_dds_with_directxtex,
    )
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset
    from PIL import Image

    decoded_source: Path | None = None
    if source.suffix.lower() == ".dds":
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
        canonical_source = (
            str(source_info.format_name or "").strip().upper() == preset.dds_format
            and int(source_info.mip_count) == int(preset.mip_count)
            and bool(source_info.srgb) == bool(preset.srgb)
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
    else:
        raise_if_cancelled(stop_event, "Material DDS generation cancelled.")
        with Image.open(source) as image:
            width, height = int(image.width), int(image.height)
        preset = resolve_texture_editor_dds_preset(
            _channel_preset_key(channel),
            width=width,
            height=height,
        )
        decoded_source = source
    if decoded_source is not None:
        staged = target.with_name(f".{target.stem}.encoding.dds")
        try:
            report = encode_dds_with_directxtex(
                decoded_source,
                staged,
                dds_format=preset.dds_format,
                width=width,
                height=height,
                mip_count=preset.mip_count,
                overwrite=True,
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
    info = inspect_dds_native_path(target)
    if info.width <= 0 or info.height <= 0 or info.mip_count <= 0 or info.reason:
        raise ValueError(f"Generated {channel} DDS failed readback: {info.reason or 'invalid DDS metadata'}")
    if (
        str(info.format_name or "").strip().upper() != preset.dds_format
        or int(info.mip_count) != int(preset.mip_count)
        or bool(info.srgb) != bool(preset.srgb)
    ):
        raise ValueError(
            f"Generated {channel} DDS is not canonical: expected {preset.dds_format}/"
            f"{preset.mip_count} mips/{preset.preset.colorspace}, got "
            f"{info.format_name}/{info.mip_count} mips/{'srgb' if info.srgb else 'linear'}"
        )
    return {
        "content_sha256": _file_sha256(target),
        "byte_count": int(target.stat().st_size),
        "dds_format": str(info.format_name or preset.dds_format),
        "width": int(info.width),
        "height": int(info.height),
        "mip_count": int(info.mip_count),
        "color_space": "srgb" if info.srgb else "linear",
        "preset": preset.preset.key,
    }


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
