from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.core.dds_native import dds_native_report_dict, dds_source_path_from_report, inspect_dds_native_path
from cdmw.core.model_preview_orientation import resolve_preview_texture_flip_vertical
from cdmw.core.texture_native import read_native_texture_report_sidecar
from cdmw.models import ModelPreviewRenderSettings, PreparedModelPreviewBatch, PreviewMaterialTextureInput
from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_AUTHORITATIVE,
    AUTHORITY_GUESS,
    decode_crimson_texture_binding,
)
from cdmw.rendering.native_preview_material_contract import _normalized_material_key
from cdmw.rendering.native_preview_payloads import (
    _batch_normal_texture_binding_allowed,
    _first_vertex_color,
    _input_texture_kind,
    _normal_texture_binding_allowed,
    _normal_texture_input_binding_allowed,
    _payload_material_inputs,
    _safe_float,
    _technical_texture_kind,
)

def _link_or_copy_file(source: Path, target: Path) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _source_file_stat_key(source: Path) -> str:
    try:
        resolved = source.expanduser().resolve()
    except OSError:
        resolved = source
    try:
        stat = source.stat()
        return (
            f"{resolved}|size:{int(stat.st_size)}|mtime:{int(stat.st_mtime_ns)}"
        ).casefold()
    except OSError:
        return str(resolved).casefold()


def _texture_copy_slot_policy(slot_name: str, *, max_dimension: int, source_suffix: str, target_suffix: str) -> str:
    normalized_slot = str(slot_name or "texture").strip().lower() or "texture"
    return (
        f"slot:{normalized_slot}|cap:{max(0, int(max_dimension or 0))}|"
        f"source:{str(source_suffix or '').lower()}|target:{str(target_suffix or '').lower()}"
    )


def _copy_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    slot_name: str,
    copy_cache: Dict[str, str],
    notes: list[str],
    max_dimension: int = 0,
    persistent_cache_dir: Optional[Path] = None,
) -> str:
    raw = str(source_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme.lower() == "file":
        raw = unquote(parsed.path or "")
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
    try:
        source = Path(raw).expanduser()
    except OSError:
        notes.append(f"{slot_name} invalid path")
        return ""
    if not source.is_file():
        notes.append(f"{slot_name} missing texture:{Path(raw).name}")
        return ""
    normalized_cap = max(0, int(max_dimension or 0))
    suffix = source.suffix if source.suffix else ".png"
    resize_supported = source.suffix.lower() not in {".dds"} and normalized_cap > 0
    target_suffix = ".png" if resize_supported else suffix
    slot_policy = _texture_copy_slot_policy(
        slot_name,
        max_dimension=normalized_cap,
        source_suffix=suffix,
        target_suffix=target_suffix,
    )
    key = f"{_source_file_stat_key(source)}|{slot_policy}"
    cached = copy_cache.get(key)
    if cached:
        return cached
    target = textures_dir / f"batch_{batch_index:03d}_{slot_name}_{len(copy_cache):03d}{target_suffix}"
    write_target = target
    cache_target: Optional[Path] = None
    if persistent_cache_dir is not None:
        try:
            persistent_cache_dir.mkdir(parents=True, exist_ok=True)
            key_hash = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()
            cache_target = persistent_cache_dir / f"{key_hash}{target_suffix}"
            if cache_target.is_file():
                _link_or_copy_file(cache_target, target)
                relative = target.relative_to(package_dir).as_posix()
                copy_cache[key] = relative
                return relative
            write_target = cache_target
        except OSError:
            cache_target = None
            write_target = target
    try:
        if resize_supported:
            image = QImage(str(source))
            if image.isNull():
                shutil.copy2(source, write_target)
            else:
                capped = max(int(image.width()), int(image.height())) > normalized_cap
                if capped:
                    image = image.scaled(
                        normalized_cap,
                        normalized_cap,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                if image.save(str(write_target), "PNG"):
                    if capped:
                        notes.append(f"{slot_name} preview texture capped:{normalized_cap}px")
                else:
                    shutil.copy2(source, write_target)
        else:
            shutil.copy2(source, write_target)
        if cache_target is not None:
            _link_or_copy_file(cache_target, target)
    except OSError as exc:
        notes.append(f"{slot_name} copy failed:{exc}")
        return ""
    relative = target.relative_to(package_dir).as_posix()
    copy_cache[key] = relative
    return relative


def _materialize_in_memory_texture_key(
    model: object,
    texture_key: str,
    *,
    textures_dir: Path,
    batch_index: int,
    slot_name: str,
) -> str:
    key = str(texture_key or "").strip()
    if not key.startswith("in_memory"):
        return key
    prefix, _separator, raw_index = key.partition(":")
    try:
        mesh_index = int(raw_index)
    except (TypeError, ValueError):
        return key
    meshes = tuple(getattr(model, "meshes", ()) or ())
    if mesh_index < 0 or mesh_index >= len(meshes):
        return key
    image_attribute = {
        "in_memory": "preview_texture_image",
        "in_memory_normal": "preview_normal_texture_image",
        "in_memory_material": "preview_material_texture_image",
        "in_memory_height": "preview_height_texture_image",
    }.get(prefix)
    if not image_attribute:
        return key
    image = getattr(meshes[mesh_index], image_attribute, None)
    if image is None or not hasattr(image, "save"):
        return key
    try:
        if hasattr(image, "isNull") and image.isNull():
            return key
    except Exception:
        return key
    materialized_dir = textures_dir / "in_memory"
    materialized_dir.mkdir(parents=True, exist_ok=True)
    target = materialized_dir / f"batch_{batch_index:03d}_{slot_name}.png"
    try:
        if image.save(str(target), "PNG"):
            return str(target)
    except Exception:
        return key
    return key


def _materialized_in_memory_batch(
    model: object,
    batch: PreparedModelPreviewBatch,
    *,
    textures_dir: Path,
    batch_index: int,
) -> PreparedModelPreviewBatch:
    replacements: Dict[str, str] = {}
    for attribute_name, slot_name in (
        ("preview_texture_path", "base"),
        ("preview_normal_texture_path", "normal"),
        ("preview_material_texture_path", "material"),
        ("preview_height_texture_path", "height"),
    ):
        value = str(getattr(batch, attribute_name, "") or "")
        materialized = _materialize_in_memory_texture_key(
            model,
            value,
            textures_dir=textures_dir,
            batch_index=batch_index,
            slot_name=slot_name,
        )
        if materialized != value:
            replacements[attribute_name] = materialized
    if not replacements:
        return batch
    return dataclasses.replace(batch, **replacements)


def _split_legacy_pbr_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    notes: list[str],
    max_dimension: int = 0,
) -> Dict[str, str]:
    raw = str(source_path or "").strip()
    if not raw:
        return {}
    try:
        source = Path(raw).expanduser()
    except OSError:
        notes.append("legacy PBR map invalid path")
        return {}
    if not source.is_file():
        notes.append(f"legacy PBR map missing:{Path(raw).name}")
        return {}
    image = QImage(str(source)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        notes.append(f"legacy PBR map unreadable:{source.name}")
        return {}
    width = int(image.width())
    height = int(image.height())
    if width <= 0 or height <= 0:
        notes.append(f"legacy PBR map empty:{source.name}")
        return {}
    normalized_cap = max(0, int(max_dimension or 0))
    if normalized_cap > 0 and max(width, height) > normalized_cap:
        image = image.scaled(
            normalized_cap,
            normalized_cap,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_RGBA8888)
        width = int(image.width())
        height = int(image.height())
        notes.append(f"legacy PBR response capped:{normalized_cap}px")
    output_dir = textures_dir / "combined"
    output_dir.mkdir(parents=True, exist_ok=True)
    slot_channels = {
        "occlusion": 0,
        "roughness": 1,
        "metalness": 2,
        "specular": 3,
    }
    generated: Dict[str, str] = {}
    for slot_name, channel_index in slot_channels.items():
        target = QImage(width, height, QImage.Format.Format_RGB888)
        peak = 0
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                value = (
                    color.red()
                    if channel_index == 0
                    else color.green()
                    if channel_index == 1
                    else color.blue()
                    if channel_index == 2
                    else color.alpha()
                )
                peak = max(peak, int(value))
                target.setPixelColor(x, y, QColor(value, value, value))
        if slot_name in {"metalness", "specular"} and peak <= 3:
            continue
        target_path = output_dir / f"batch_{batch_index:03d}_{slot_name}_legacy_pbr.png"
        if target.save(str(target_path), "PNG"):
            generated[slot_name] = target_path.relative_to(package_dir).as_posix()
    if generated:
        notes.append("legacy PBR response reused for D3D11 material slots")
    return generated


def _source_dds_for_preview_path(preview_path: str) -> str:
    raw = str(preview_path or "").strip()
    if not raw:
        return ""
    try:
        direct_source = Path(raw).expanduser()
        if direct_source.suffix.lower() == ".dds" and direct_source.is_file():
            return str(direct_source)
    except OSError:
        pass
    try:
        report = read_native_texture_report_sidecar(Path(raw))
    except Exception:
        return ""
    if not isinstance(report, Mapping):
        return ""
    source_path = dds_source_path_from_report(report)
    if not source_path:
        return ""
    try:
        source = Path(source_path).expanduser()
    except OSError:
        return ""
    return str(source) if source.is_file() else ""


def _dds_manifest_entry(
    source_path: str,
    *,
    slot_name: str,
    reason: str = "",
    inspect_cache: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
    raw = str(source_path or "").strip()
    if not raw:
        return {}
    try:
        source = Path(raw).expanduser()
    except OSError:
        return {
            "slot": str(slot_name or ""),
            "source_path": raw,
            "available": False,
            "reason": "invalid DDS path",
        }
    if not source.is_file():
        return {
            "slot": str(slot_name or ""),
            "source_path": str(source),
            "available": False,
            "reason": reason or "DDS file missing",
        }
    cache_key = _source_file_stat_key(source)
    report: Dict[str, object]
    cached_report = inspect_cache.get(cache_key) if inspect_cache is not None else None
    if cached_report is not None:
        report = dict(cached_report)
    else:
        try:
            info = inspect_dds_native_path(source)
            report = dds_native_report_dict(source, info, backend="dds_native_manifest")
        except Exception as exc:
            return {
                "slot": str(slot_name or ""),
                "source_path": str(source),
                "available": False,
                "reason": f"DDS inspect failed: {exc}",
            }
        report.update(
            {
                "available": True,
                "direct_upload_candidate": bool(
                    report.get("direct_upload_candidate", False)
                    or report.get("supported_compressed", False)
                    or report.get("supported_uncompressed", False)
                ),
            }
        )
        if inspect_cache is not None:
            inspect_cache[cache_key] = dict(report)
    report.update(
        {
            "slot": str(slot_name or ""),
            "available": True,
            "direct_upload_candidate": bool(
                report.get("direct_upload_candidate", False)
                or report.get("supported_compressed", False)
                or report.get("supported_uncompressed", False)
            ),
        }
    )
    if reason:
        report["reason"] = reason
    compact = {
        key: value
        for key, value in report.items()
        if key not in {"mip_levels"}
    }
    return compact


def _dds_manifest_entry_is_native_usable(entry: object) -> bool:
    if not isinstance(entry, Mapping):
        return False
    if not bool(entry.get("available", False)):
        return False
    if not bool(entry.get("direct_upload_candidate", False)):
        return False
    source_path = str(entry.get("source_path", "") or "").strip()
    if not source_path:
        return False
    try:
        return Path(source_path).expanduser().is_file()
    except OSError:
        return False


def _dds_textures_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    inspect_cache: Optional[Dict[str, Dict[str, object]]] = None,
    include_support_slots: bool = True,
    material_input_kinds: Optional[set[str]] = None,
) -> Dict[str, object]:
    slots = {
        "base": str(getattr(batch, "preview_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_texture_path", "") or "")),
    }
    if include_support_slots:
        if _batch_normal_texture_binding_allowed(batch):
            slots["normal"] = str(getattr(batch, "preview_normal_texture_dds_path", "") or "") or _source_dds_for_preview_path(
                str(getattr(batch, "preview_normal_texture_path", "") or "")
            )
        slots.update(
            {
                "material": str(getattr(batch, "preview_material_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_material_texture_path", "") or "")),
                "height": str(getattr(batch, "preview_height_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_height_texture_path", "") or "")),
                "emissive": str(getattr(batch, "preview_emissive_texture_dds_path", "") or "")
                or _source_dds_for_preview_path(str(getattr(batch, "preview_emissive_texture_path", "") or "")),
            }
        )
    output: Dict[str, object] = {
        slot_name: _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
        for slot_name, source_path in slots.items()
        if str(source_path or "").strip()
    }
    for slot_name, entry in list(output.items()):
        if not isinstance(entry, dict):
            continue
        registry_decode = decode_crimson_texture_binding(
            shader_family=str(getattr(batch, "preview_sidecar_shader_family", "") or ""),
            parameter_name="",
            source_path=str(entry.get("source_path", "") or ""),
            slot_name=slot_name,
        )
        entry["authority"] = AUTHORITY_AUTHORITATIVE if slot_name in {"base", "normal", "height"} else str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
        entry["disposition"] = "promoted" if slot_name in {"base", "normal", "height"} else str(registry_decode.get("disposition", "") or "")
        entry["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
    input_entries: list[Dict[str, object]] = []
    allowed_input_kinds = (
        None
        if material_input_kinds is None
        else {str(kind or "").strip().lower() for kind in set(material_input_kinds)}
    )
    for texture_input in _payload_material_inputs(batch):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_kind = _input_texture_kind(texture_input)
        if allowed_input_kinds is not None and input_kind not in allowed_input_kinds:
            continue
        source_path = str(getattr(texture_input, "source_dds_path", "") or "").strip()
        if not source_path:
            source_path = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        if not source_path:
            continue
        if input_kind == "normal" and not _normal_texture_input_binding_allowed(texture_input):
            continue
        slot_name = str(getattr(texture_input, "slot_kind", "") or "material").strip().lower() or "material"
        entry = _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
        entry["parameter_name"] = str(getattr(texture_input, "parameter_name", "") or "")
        entry["semantic_type"] = str(getattr(texture_input, "semantic_type", "") or "")
        entry["semantic_subtype"] = str(getattr(texture_input, "semantic_subtype", "") or "")
        entry["material_name"] = str(getattr(texture_input, "material_name", "") or "")
        entry["shader_family"] = str(getattr(texture_input, "shader_family", "") or "")
        entry["shader_rule"] = str(getattr(texture_input, "shader_rule", "") or "")
        entry["sidecar_path"] = str(getattr(texture_input, "sidecar_path", "") or "")
        entry["sidecar_kind"] = str(getattr(texture_input, "sidecar_kind", "") or "")
        entry["linked_mesh_path"] = str(getattr(texture_input, "linked_mesh_path", "") or "")
        entry["packed_channels"] = list(tuple(getattr(texture_input, "packed_channels", ()) or ()))
        entry["srgb_mode"] = str(getattr(texture_input, "srgb_mode", "") or "")
        entry["parameter_declared_by"] = str(getattr(texture_input, "parameter_declared_by", "") or "")
        entry["material_output_quality"] = str(getattr(texture_input, "material_output_quality", "") or "")
        entry["layer_role"] = str(getattr(texture_input, "layer_role", "") or "")
        entry["layer_channel"] = str(getattr(texture_input, "layer_channel", "") or "")
        entry["blend_flags"] = list(tuple(getattr(texture_input, "blend_flags", ()) or ()))
        registry_decode = decode_crimson_texture_binding(
            shader_family=entry["shader_family"],
            parameter_name=entry["parameter_name"],
            source_path=str(entry.get("source_path", "") or ""),
            slot_name=slot_name,
            semantic_subtype=entry["semantic_subtype"],
            packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
            layer_channel=entry["layer_channel"],
            blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
            sidecar_kind=entry["sidecar_kind"],
            parameter_declared_by=entry["parameter_declared_by"],
        )
        entry["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
        entry["disposition"] = str(registry_decode.get("disposition", "") or "")
        entry["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
        entry["promoted_channels"] = dict(registry_decode.get("promoted_channels", {}) or {})
        if registry_decode.get("layer_channel"):
            entry["layer_channel"] = str(registry_decode.get("layer_channel", "") or "")
        input_entries.append(entry)
    if input_entries:
        output["material_inputs"] = input_entries
    return output


def _batch_dds_manifest_cache_key(
    batch: PreparedModelPreviewBatch,
    *,
    include_support_slots: bool,
    material_input_kinds: Optional[set[str]],
) -> str:
    allowed_input_kinds = (
        None
        if material_input_kinds is None
        else sorted(str(kind or "").strip().lower() for kind in set(material_input_kinds))
    )
    input_values = []
    for texture_input in _payload_material_inputs(batch):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_kind = _input_texture_kind(texture_input)
        if allowed_input_kinds is not None and input_kind not in set(allowed_input_kinds):
            continue
        input_values.append(
            (
                input_kind,
                str(getattr(texture_input, "slot_kind", "") or ""),
                str(getattr(texture_input, "parameter_name", "") or ""),
                str(getattr(texture_input, "source_dds_path", "") or ""),
                str(getattr(texture_input, "source_texture_path", "") or ""),
                str(getattr(texture_input, "preview_texture_path", "") or ""),
                str(getattr(texture_input, "texture_name", "") or ""),
                tuple(str(value) for value in tuple(getattr(texture_input, "packed_channels", ()) or ())),
                str(getattr(texture_input, "semantic_type", "") or ""),
                str(getattr(texture_input, "semantic_subtype", "") or ""),
                str(getattr(texture_input, "material_name", "") or ""),
                str(getattr(texture_input, "shader_family", "") or ""),
            )
        )
    payload = {
        "support": bool(include_support_slots),
        "input_kinds": allowed_input_kinds,
        "slots": {
            "base_dds": str(getattr(batch, "preview_texture_dds_path", "") or ""),
            "base_preview": str(getattr(batch, "preview_texture_path", "") or ""),
            "normal_dds": str(getattr(batch, "preview_normal_texture_dds_path", "") or ""),
            "normal_preview": str(getattr(batch, "preview_normal_texture_path", "") or ""),
            "normal_name": str(getattr(batch, "preview_normal_texture_name", "") or ""),
            "material_dds": str(getattr(batch, "preview_material_texture_dds_path", "") or ""),
            "material_preview": str(getattr(batch, "preview_material_texture_path", "") or ""),
            "height_dds": str(getattr(batch, "preview_height_texture_dds_path", "") or ""),
            "height_preview": str(getattr(batch, "preview_height_texture_path", "") or ""),
            "emissive_dds": str(getattr(batch, "preview_emissive_texture_dds_path", "") or ""),
            "emissive_preview": str(getattr(batch, "preview_emissive_texture_path", "") or ""),
        },
        "inputs": input_values,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")).hexdigest()


def _source_path_key(value: object) -> str:
    source_path = str(value or "").strip()
    if not source_path:
        return ""
    try:
        return str(Path(source_path).expanduser().resolve()).casefold()
    except OSError:
        return source_path.casefold()


def _filter_dds_textures_for_preview_settings(
    dds_textures: Mapping[str, object],
    batch: PreparedModelPreviewBatch,
    *,
    render_settings: ModelPreviewRenderSettings,
    use_textures: bool,
    high_quality_textures: bool,
    promote_material_inputs: bool = True,
) -> Dict[str, object]:
    if not use_textures or not bool(getattr(batch, "has_texture_coordinates", False)):
        return {}
    support_enabled = bool(
        high_quality_textures
        and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
        and not bool(getattr(render_settings, "disable_all_support_maps", False))
    )

    def entry_is_layer_only(entry: Mapping[str, object]) -> bool:
        disposition = str(entry.get("disposition", "") or "").strip().lower()
        source_kind = str(entry.get("registry_source_kind", "") or "").strip().lower()
        parameter_key = _normalized_material_key(entry.get("parameter_name", ""))
        return bool(
            disposition in {"layer_only", "layer_material_response", "layer_flow", "layer_direction"}
            or source_kind.startswith("crimson_layer")
            or any(token in parameter_key for token in ("detaildiffuse", "grimediffuse", "damageblendingdiffuse"))
        )

    def entry_is_true_base(entry: Mapping[str, object]) -> bool:
        disposition = str(entry.get("disposition", "") or "").strip().lower()
        source_kind = str(entry.get("registry_source_kind", "") or "").strip().lower()
        return bool(disposition == "promoted" and source_kind not in {"crimson_layer_color"})

    input_entries = dds_textures.get("material_inputs")
    raw_input_entries = (
        [
            dict(raw_entry)
            for raw_entry in input_entries
            if isinstance(raw_entry, Mapping) and _dds_manifest_entry_is_native_usable(raw_entry)
        ]
        if isinstance(input_entries, Sequence) and not isinstance(input_entries, (str, bytes, bytearray))
        else []
    )

    def base_entry_is_layer_only_input(base_entry_value: object) -> bool:
        if not isinstance(base_entry_value, Mapping):
            return False
        base_key = _source_path_key(base_entry_value.get("source_path"))
        if not base_key:
            return False
        matching_inputs = [entry for entry in raw_input_entries if _source_path_key(entry.get("source_path")) == base_key]
        return bool(
            matching_inputs
            and any(entry_is_layer_only(entry) for entry in matching_inputs)
            and not any(entry_is_true_base(entry) for entry in matching_inputs)
        )

    output: Dict[str, object] = {}
    base_entry = dds_textures.get("base")
    if _dds_manifest_entry_is_native_usable(base_entry) and not base_entry_is_layer_only_input(base_entry):
        output["base"] = dict(base_entry)
    if support_enabled:
        for slot_name, disabled_attr in (
            ("normal", "disable_normal_map"),
            ("material", "disable_material_map"),
            ("height", "disable_height_map"),
        ):
            if bool(getattr(render_settings, disabled_attr, False)):
                continue
            if slot_name == "normal" and not _batch_normal_texture_binding_allowed(batch):
                continue
            entry = dds_textures.get(slot_name)
            if _dds_manifest_entry_is_native_usable(entry):
                output[slot_name] = dict(entry)

    def input_role(entry: Mapping[str, object]) -> str:
        if entry_is_layer_only(entry):
            return "material"
        descriptor = " ".join(
            str(entry.get(field, "") or "")
            for field in ("slot", "parameter_name", "semantic_type", "semantic_subtype", "source_path")
        ).lower()
        technical = _technical_texture_kind(descriptor)
        if (
            "base" in descriptor
            or "albedo" in descriptor
            or "diffuse" in descriptor
            or "color" in descriptor
        ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "emissive"}:
            return "base"
        if technical == "emissive" or "emissive" in descriptor or "glow" in descriptor:
            return "emissive"
        if technical == "normal" or "normal" in descriptor:
            return "normal"
        if technical == "height" or "displacement" in descriptor:
            return "height"
        if technical in {"packed_material", "detail_mask", "specular", "roughness", "glossiness", "metalness", "occlusion"}:
            return "material"
        if any(token in descriptor for token in ("roughness", "metallic", "metalness", "occlusion", "materialmask")):
            return "material"
        if "opacity" in descriptor or "alpha" in descriptor:
            return "opacity"
        return "material"

    if raw_input_entries:
        filtered_inputs: list[Dict[str, object]] = []
        for raw_entry in raw_input_entries:
            role = input_role(raw_entry)
            if role in {"base", "emissive"}:
                filtered_inputs.append(dict(raw_entry))
            elif not support_enabled:
                continue
            elif (
                role == "normal"
                and not bool(getattr(render_settings, "disable_normal_map", False))
                and _normal_texture_binding_allowed(raw_entry.get("source_path", ""))
            ):
                filtered_inputs.append(dict(raw_entry))
            elif role == "height" and not bool(getattr(render_settings, "disable_height_map", False)):
                filtered_inputs.append(dict(raw_entry))
            elif role == "material" and not bool(getattr(render_settings, "disable_material_map", False)):
                filtered_inputs.append(dict(raw_entry))
        if filtered_inputs:
            for promoted_role, manifest_slot in (
                ("base", "base"),
                ("normal", "normal"),
                ("height", "height"),
                ("material", "material"),
                ("emissive", "emissive"),
            ):
                if not promote_material_inputs:
                    break
                if manifest_slot in output:
                    continue
                if promoted_role not in {"base", "emissive"} and not support_enabled:
                    continue
                if promoted_role == "normal" and bool(getattr(render_settings, "disable_normal_map", False)):
                    continue
                if promoted_role == "height" and bool(getattr(render_settings, "disable_height_map", False)):
                    continue
                if promoted_role == "material" and bool(getattr(render_settings, "disable_material_map", False)):
                    continue
                for entry in filtered_inputs:
                    if input_role(entry) != promoted_role:
                        continue
                    promoted = dict(entry)
                    promoted["slot"] = manifest_slot
                    promoted["promoted_from_material_input"] = True
                    output[manifest_slot] = promoted
                    break
            output["material_inputs"] = filtered_inputs
    return output


def _texture_sources_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    render_settings: ModelPreviewRenderSettings,
    use_textures: bool,
    high_quality_textures: bool,
    source_format: object,
    source_path: object,
    tangents_usable: bool,
    copy_cache: Dict[str, str],
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
    direct_dds_slots: Optional[Mapping[str, object]] = None,
    legacy_pbr_cache: Optional[Dict[Tuple[str, int], Dict[str, str]]] = None,
    persistent_texture_cache_dir: Optional[Path] = None,
) -> Tuple[Dict[str, str], Tuple[str, ...], Dict[str, object]]:
    notes: list[str] = []
    textures: Dict[str, str] = {
        "base": "",
        "normal": "",
        "occlusion": "",
        "roughness": "",
        "metalness": "",
        "specular": "",
        "height": "",
        "emissive": "",
    }
    combiner_metadata: Dict[str, object] = {
        "active": False,
        "outputs": (),
        "decode_modes": (),
        "notes": (),
    }
    has_uv = bool(getattr(batch, "has_texture_coordinates", False))
    support_enabled = bool(
        use_textures
        and high_quality_textures
        and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
        and not bool(getattr(render_settings, "disable_all_support_maps", False))
    )
    if not use_textures or not has_uv:
        notes.append("textures disabled" if not use_textures else "missing UVs")
        return textures, tuple(notes), combiner_metadata

    base_copy_cap = max(0, int(getattr(render_settings, "preview_texture_max_dimension", 0) or 0))
    support_copy_cap = max(0, int(getattr(render_settings, "low_quality_texture_max_dimension", 0) or 0))

    direct_dds_slots = direct_dds_slots if prefer_direct_dds and isinstance(direct_dds_slots, Mapping) else (
        _dds_textures_for_batch(batch) if prefer_direct_dds else {}
    )

    material_inputs = _payload_material_inputs(batch)
    normal_texture_allowed = _batch_normal_texture_binding_allowed(batch)

    def _direct_dds_entry_available(entry: object) -> bool:
        return bool(
            isinstance(entry, Mapping)
            and entry.get("available")
            and entry.get("source_path")
            and entry.get("direct_upload_candidate")
        )

    def has_direct_dds(slot_name: str) -> bool:
        entry = direct_dds_slots.get(slot_name)
        return _direct_dds_entry_available(entry)
    def _direct_material_input_entries() -> Tuple[Mapping[str, object], ...]:
        entries = direct_dds_slots.get("material_inputs")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            return ()
        return tuple(entry for entry in entries if isinstance(entry, Mapping))
    def _direct_material_descriptor(entry: Mapping[str, object]) -> str:
        return " ".join(
            str(entry.get(field, "") or "")
            for field in ("slot", "parameter_name", "semantic_type", "semantic_subtype", "source_path")
        ).lower()

    def _direct_material_input_available_for(kind: str, texture_input: Optional[PreviewMaterialTextureInput] = None) -> bool:
        normalized_kind = str(kind or "").strip().lower()
        direct_source = ""
        if texture_input is not None:
            direct_source = str(getattr(texture_input, "source_dds_path", "") or "").strip()
            if not direct_source:
                direct_source = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        direct_source_key = _source_path_key(direct_source)
        for entry in _direct_material_input_entries():
            if not _direct_dds_entry_available(entry):
                continue
            if direct_source_key and _source_path_key(entry.get("source_path")) == direct_source_key:
                return True
            if texture_input is not None:
                continue
            descriptor = _direct_material_descriptor(entry)
            technical = _technical_texture_kind(str(entry.get("source_path", "") or ""))
            if normalized_kind == "base":
                if (
                    "base" in descriptor
                    or "albedo" in descriptor
                    or "diffuse" in descriptor
                    or "color" in descriptor
                ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "emissive"}:
                    return True
            elif normalized_kind == "emissive" and (technical == "emissive" or "emissive" in descriptor or "glow" in descriptor):
                return True
            elif normalized_kind == "normal" and technical == "normal":
                return True
            elif normalized_kind == "height" and technical == "height":
                return True
            elif normalized_kind == "specular" and (
                technical == "specular" or "specular" in descriptor or "_sp" in descriptor
            ):
                return True
            elif normalized_kind == "roughness" and ("roughness" in descriptor or "gloss" in descriptor or "smoothness" in descriptor):
                return True
            elif normalized_kind == "metalness" and ("metallic" in descriptor or "metalness" in descriptor):
                return True
            elif normalized_kind in {"material", "packed_material", "occlusion"} and (
                technical == "packed_material"
                or technical == "occlusion"
                or "material_mask" in descriptor
                or "packed_mask" in descriptor
                or "_ma" in descriptor
            ):
                return True
            elif normalized_kind in {"detail", "detail_mask"} and (
                technical == "detail_mask" or "detailmask" in descriptor or "colorblendingmask" in descriptor or "_mg" in descriptor
            ):
                return True
        return False
    def _direct_material_response_available() -> bool:
        return bool(
            has_direct_dds("material")
            or _direct_material_input_available_for("material")
            or _direct_material_input_available_for("specular")
            or _direct_material_input_available_for("roughness")
            or _direct_material_input_available_for("metalness")
            or _direct_material_input_available_for("detail")
        )

    def _direct_dds_available_for_source(source_path: str) -> bool:
        source_key = _source_path_key(source_path)
        if not source_key:
            return False
        for slot_name in ("base", "normal", "material", "height", "emissive"):
            entry = direct_dds_slots.get(slot_name)
            if _direct_dds_entry_available(entry) and _source_path_key(entry.get("source_path")) == source_key:
                return True
        for entry in _direct_material_input_entries():
            if _direct_dds_entry_available(entry) and _source_path_key(entry.get("source_path")) == source_key:
                return True
        return False

    def _preview_source_has_direct_dds_upload(preview_path: str) -> bool:
        dds_path = _source_dds_for_preview_path(preview_path)
        return bool(dds_path and _direct_dds_available_for_source(dds_path))

    def _texture_input_source_keys(texture_input: PreviewMaterialTextureInput) -> set[str]:
        keys: set[str] = set()
        for raw_source in (
            getattr(texture_input, "source_dds_path", ""),
            getattr(texture_input, "source_texture_path", ""),
            getattr(texture_input, "preview_texture_path", ""),
            getattr(texture_input, "texture_name", ""),
        ):
            source_text = str(raw_source or "").strip()
            if not source_text:
                continue
            keys.add(_source_path_key(source_text))
            try:
                keys.add(Path(source_text).expanduser().name.casefold())
            except OSError:
                pass
        return {key for key in keys if key}

    def _base_preview_is_layer_only_input() -> bool:
        base_sources = {
            _source_path_key(getattr(batch, "preview_texture_dds_path", "")),
            _source_path_key(getattr(batch, "preview_texture_path", "")),
        }
        try:
            base_sources.add(Path(str(getattr(batch, "preview_texture_path", "") or "")).expanduser().name.casefold())
        except OSError:
            pass
        try:
            base_sources.add(Path(str(getattr(batch, "preview_texture_dds_path", "") or "")).expanduser().name.casefold())
        except OSError:
            pass
        base_sources = {source for source in base_sources if source}
        if not base_sources:
            return False
        matched_layer_input = False
        matched_true_base = False
        for texture_input in material_inputs:
            if not isinstance(texture_input, PreviewMaterialTextureInput):
                continue
            input_keys = _texture_input_source_keys(texture_input)
            if not input_keys or not (base_sources & input_keys):
                continue
            registry_decode = decode_crimson_texture_binding(
                shader_family=str(getattr(texture_input, "shader_family", "") or ""),
                parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
                source_path=str(
                    getattr(texture_input, "source_dds_path", "")
                    or getattr(texture_input, "source_texture_path", "")
                    or getattr(texture_input, "preview_texture_path", "")
                    or ""
                ),
                slot_name=str(getattr(texture_input, "slot_kind", "") or "base"),
                semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
                packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
                layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
                blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
                sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
                parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
            )
            disposition = str(registry_decode.get("disposition", "") or "").strip().lower()
            source_kind = str(registry_decode.get("source_kind", "") or "").strip().lower()
            parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
            if disposition == "promoted" and source_kind != "crimson_layer_color":
                matched_true_base = True
            if (
                disposition in {"layer_only", "layer_material_response", "layer_flow", "layer_direction"}
                or source_kind.startswith("crimson_layer")
                or any(token in parameter_key for token in ("detaildiffuse", "grimediffuse", "damageblendingdiffuse"))
            ):
                matched_layer_input = True
        return bool(matched_layer_input and not matched_true_base)

    def package_relative(source_ref: str, slot_name: str) -> str:
        raw = str(source_ref or "").strip()
        if not raw:
            return ""
        try:
            from PySide6.QtCore import QUrl

            local_path = QUrl(raw).toLocalFile() if raw.lower().startswith("file:") else raw
        except Exception:
            local_path = raw
        try:
            source = Path(local_path).expanduser()
        except OSError:
            notes.append(f"{slot_name} invalid generated path")
            return ""
        if not source.is_file():
            notes.append(f"{slot_name} generated texture missing:{Path(local_path).name}")
            return ""
        try:
            return source.resolve().relative_to(package_dir.resolve()).as_posix()
        except (OSError, ValueError):
            return _copy_texture(
                str(source),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=slot_name,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap if slot_name == "base" else support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )

    base_path = str(getattr(batch, "preview_texture_path", "") or "")
    if base_path:
        if _base_preview_is_layer_only_input():
            notes.append("base texturelayer kept masked; whole-surface base skipped")
        elif has_direct_dds("base"):
            notes.append("base PNG fallback skipped; direct DDS available")
        else:
            textures["base"] = _copy_texture(
                base_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="base",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
    else:
        notes.append("no reliable base DDS")

    if support_enabled and not bool(getattr(render_settings, "disable_normal_map", False)):
        if not normal_texture_allowed:
            suspicious_source = str(getattr(batch, "preview_normal_texture_dds_path", "") or "") or str(
                getattr(batch, "preview_normal_texture_path", "") or ""
            )
            if suspicious_source:
                notes.append("normal map skipped; binding does not look like a normal texture")
        elif has_direct_dds("normal"):
            notes.append("normal PNG fallback skipped; direct DDS available")
        else:
            textures["normal"] = _copy_texture(
                str(getattr(batch, "preview_normal_texture_path", "") or ""),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="normal",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
    if support_enabled and not bool(getattr(render_settings, "disable_height_map", False)):
        if has_direct_dds("height"):
            notes.append("height PNG fallback skipped; direct DDS available")
        else:
            textures["height"] = _copy_texture(
                str(getattr(batch, "preview_height_texture_path", "") or ""),
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="height",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )

    material_path = str(getattr(batch, "preview_material_texture_path", "") or "")
    material_subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    reused_legacy_pbr = False
    if support_enabled and material_path and material_subtype in {"pbr_combined", "legacy_pbr_combined"}:
        if prefer_direct_dds and _direct_material_response_available():
            notes.append("legacy PBR PNG split skipped; direct DDS material inputs available")
        else:
            try:
                cache_key = (str(Path(material_path).expanduser().resolve()).casefold(), int(support_copy_cap))
            except OSError:
                cache_key = (str(material_path).casefold(), int(support_copy_cap))
            generated = dict((legacy_pbr_cache or {}).get(cache_key, {}))
            if generated:
                notes.append("legacy PBR response reused from package cache")
            else:
                generated = _split_legacy_pbr_texture(
                    material_path,
                    package_dir=package_dir,
                    textures_dir=textures_dir,
                    batch_index=batch_index,
                    notes=notes,
                    max_dimension=support_copy_cap,
                )
                if generated and legacy_pbr_cache is not None:
                    legacy_pbr_cache[cache_key] = dict(generated)
            if not bool(getattr(render_settings, "disable_material_map", False)):
                for slot_name, relative_path in generated.items():
                    textures[slot_name] = relative_path
            if generated:
                reused_legacy_pbr = True
                combiner_metadata = {
                    "active": True,
                    "outputs": tuple(generated.keys()),
                    "decode_modes": ("pbr_combined",),
                    "notes": ("legacy PBR response reused",),
                }

    if enable_material_combiner and not reused_legacy_pbr and (support_enabled or material_inputs):
        try:
            from cdmw.rendering.material_combiner import (
                MaterialPreviewCombinerSettings,
                combine_preview_material,
                synthesize_material_texture_inputs,
            )

            synthesized_inputs = synthesize_material_texture_inputs(batch)
            combiner_payload = SimpleNamespace(
                material_name=str(getattr(batch, "material_name", "") or ""),
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                source_path=str(source_path or ""),
                base_color=_first_vertex_color(getattr(batch, "vertex_blob", b"") or b""),
                texture_flip_vertical=resolve_preview_texture_flip_vertical(
                    getattr(batch, "preview_texture_flip_vertical", None),
                    source_format=source_format,
                    source_path=source_path,
                ),
                material_texture_inputs=synthesized_inputs,
                alpha_mode=str(getattr(batch, "preview_alpha_mode", "") or ""),
                tangents_usable=bool(tangents_usable),
                normal_texture_strength=max(0.0, _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0))
                if normal_texture_allowed
                else 0.0,
            )
            combiner_settings = MaterialPreviewCombinerSettings(
                normal_strength_floor=max(0.0, _safe_float(getattr(render_settings, "normal_strength_floor", 0.5), 0.5)),
                normal_strength_cap=max(0.0, _safe_float(getattr(render_settings, "normal_strength_cap", 1.0), 1.0)),
                height_amount=max(0.0, min(0.12, _safe_float(getattr(render_settings, "height_effect_max", 0.35), 0.35) * 0.08)),
                support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
            )
            combined = combine_preview_material(
                combiner_payload,
                textures_dir / "combined",
                batch_index,
                settings=combiner_settings,
            )
            combiner_metadata = {
                "active": bool(combined.active),
                "outputs": tuple(combined.outputs),
                "decode_modes": tuple(combined.decode_modes),
                "notes": tuple(combined.notes),
            }
            if combined.base_note:
                combiner_metadata["base_note"] = str(combined.base_note)
            notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
            if combined.base_source:
                textures["base"] = package_relative(combined.base_source, "base")
            if (
                support_enabled
                and not bool(getattr(render_settings, "disable_normal_map", False))
                and normal_texture_allowed
                and combined.normal_source
            ):
                textures["normal"] = package_relative(combined.normal_source, "normal")
            if support_enabled and not bool(getattr(render_settings, "disable_material_map", False)):
                if combined.occlusion_source:
                    textures["occlusion"] = package_relative(combined.occlusion_source, "occlusion")
                if combined.roughness_source:
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.metalness_source:
                    textures["metalness"] = package_relative(combined.metalness_source, "metalness")
                if combined.specular_source:
                    textures["specular"] = package_relative(combined.specular_source, "specular")
            if support_enabled and not bool(getattr(render_settings, "disable_height_map", False)) and combined.height_source:
                textures["height"] = package_relative(combined.height_source, "height")
                combiner_metadata["height_amount"] = float(combined.height_amount)
            if normal_texture_allowed and combined.normal_source:
                combiner_metadata["normal_strength"] = float(combined.normal_strength)
            combiner_metadata["texture_flip_vertical"] = bool(combined.texture_flip_vertical)
        except Exception as exc:
            notes.append(f"material combiner failed:{exc}")

    def assign_kind(
        kind: str,
        texture_source_path: str,
        label: str,
        texture_input: Optional[PreviewMaterialTextureInput] = None,
    ) -> None:
        nonlocal combiner_metadata
        combiner_decoded = bool(tuple(combiner_metadata.get("decode_modes", ()) or ()) or tuple(combiner_metadata.get("outputs", ()) or ()))
        if kind in {"base", "normal", "height"}:
            if kind == "normal" and not _normal_texture_binding_allowed(texture_source_path, label):
                notes.append(f"normal material input skipped; binding does not look like a normal texture:{label}")
                return
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=base_copy_cap if kind == "base" else support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind == "emissive":
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append("emissive PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind == "specular_glossiness":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("roughness") and textures.get("specular"):
                return
            try:
                from cdmw.rendering.material_combiner import (
                    MaterialPreviewCombinerSettings,
                    combine_preview_material,
                )

                spec_gloss_input = texture_input
                if spec_gloss_input is None:
                    spec_gloss_input = PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_specularGlossinessTexture",
                        source_texture_path=texture_source_path,
                        texture_name=label,
                        preview_texture_path=texture_source_path,
                        semantic_type="specular",
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                    )
                combiner_payload = SimpleNamespace(
                    material_name=str(getattr(batch, "material_name", "") or ""),
                    texture_name=str(getattr(batch, "texture_name", "") or ""),
                    texture_flip_vertical=resolve_preview_texture_flip_vertical(
                        getattr(batch, "preview_texture_flip_vertical", None),
                        source_format=source_format,
                        source_path=source_path,
                    ),
                    material_texture_inputs=(spec_gloss_input,),
                    tangents_usable=bool(tangents_usable),
                    normal_texture_strength=max(
                        0.0,
                        _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
                    )
                    if normal_texture_allowed
                    else 0.0,
                )
                combiner_settings = MaterialPreviewCombinerSettings(
                    normal_strength_floor=max(0.0, _safe_float(getattr(render_settings, "normal_strength_floor", 0.5), 0.5)),
                    normal_strength_cap=max(0.0, _safe_float(getattr(render_settings, "normal_strength_cap", 1.0), 1.0)),
                    height_amount=max(0.0, min(0.12, _safe_float(getattr(render_settings, "height_effect_max", 0.35), 0.35) * 0.08)),
                    support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
                )
                combined = combine_preview_material(
                    combiner_payload,
                    textures_dir / "combined",
                    batch_index,
                    settings=combiner_settings,
                )
                notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
                if combined.roughness_source and not textures.get("roughness"):
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.specular_source and not textures.get("specular"):
                    textures["specular"] = package_relative(combined.specular_source, "specular")
                if combined.active:
                    combiner_metadata = {
                        "active": True,
                        "outputs": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("outputs", ()) or ()) + tuple(combined.outputs or ()))
                        ),
                        "decode_modes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("decode_modes", ()) or ()) + tuple(combined.decode_modes or ()))
                        ),
                        "notes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("notes", ()) or ()) + tuple(combined.notes or ()))
                        ),
                        "texture_flip_vertical": bool(combined.texture_flip_vertical),
                    }
                if textures.get("roughness") or textures.get("specular"):
                    return
            except Exception as exc:
                notes.append(f"specular-glossiness split failed:{exc}")
            if not textures.get("specular"):
                textures["specular"] = _copy_texture(
                    texture_source_path,
                    package_dir=package_dir,
                    textures_dir=textures_dir,
                    batch_index=batch_index,
                    slot_name="specular",
                    copy_cache=copy_cache,
                    notes=notes,
                    max_dimension=support_copy_cap,
                    persistent_cache_dir=persistent_texture_cache_dir,
                )
            notes.append(f"specular-glossiness roughness unavailable:{label}")
            return
        if kind == "glossiness":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("roughness"):
                return
            try:
                from cdmw.rendering.material_combiner import (
                    MaterialPreviewCombinerSettings,
                    combine_preview_material,
                )

                gloss_input = texture_input
                if gloss_input is None:
                    gloss_input = PreviewMaterialTextureInput(
                        slot_kind="glossiness",
                        parameter_name="_glossinessTexture",
                        source_texture_path=texture_source_path,
                        texture_name=label,
                        preview_texture_path=texture_source_path,
                        semantic_type="roughness",
                        semantic_subtype="glossiness",
                        packed_channels=("glossiness",),
                    )
                combiner_payload = SimpleNamespace(
                    material_name=str(getattr(batch, "material_name", "") or ""),
                    texture_name=str(getattr(batch, "texture_name", "") or ""),
                    texture_flip_vertical=resolve_preview_texture_flip_vertical(
                        getattr(batch, "preview_texture_flip_vertical", None),
                        source_format=source_format,
                        source_path=source_path,
                    ),
                    material_texture_inputs=(gloss_input,),
                    tangents_usable=bool(tangents_usable),
                    normal_texture_strength=max(
                        0.0,
                        _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
                    )
                    if normal_texture_allowed
                    else 0.0,
                )
                combined = combine_preview_material(
                    combiner_payload,
                    textures_dir / "combined",
                    batch_index,
                    settings=MaterialPreviewCombinerSettings(
                        support_map_max_dimension=min(192, int(getattr(render_settings, "low_quality_texture_max_dimension", 192) or 192)),
                    ),
                )
                notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
                if combined.roughness_source and not textures.get("roughness"):
                    textures["roughness"] = package_relative(combined.roughness_source, "roughness")
                if combined.active:
                    combiner_metadata = {
                        "active": True,
                        "outputs": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("outputs", ()) or ()) + tuple(combined.outputs or ()))
                        ),
                        "decode_modes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("decode_modes", ()) or ()) + tuple(combined.decode_modes or ()))
                        ),
                        "notes": tuple(
                            dict.fromkeys(tuple(combiner_metadata.get("notes", ()) or ()) + tuple(combined.notes or ()))
                        ),
                        "texture_flip_vertical": bool(combined.texture_flip_vertical),
                    }
                if textures.get("roughness"):
                    return
            except Exception as exc:
                notes.append(f"glossiness split failed:{exc}")
            notes.append(f"glossiness roughness unavailable:{label}")
            return
        if kind == "occlusion":
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("occlusion"):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append("occlusion PNG fallback skipped; direct DDS material input available")
                return
            textures["occlusion"] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="occlusion",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind in {"roughness", "metalness", "specular"}:
            if not support_enabled or bool(getattr(render_settings, f"disable_material_map", False)):
                return
            if textures.get(kind):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures[kind] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        if kind in {"packed_material", "detail_mask"}:
            if not support_enabled or bool(getattr(render_settings, "disable_material_map", False)):
                return
            if textures.get("material"):
                return
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(texture_source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
                return
            textures["material"] = _copy_texture(
                texture_source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name="material",
                copy_cache=copy_cache,
                notes=notes,
                max_dimension=support_copy_cap,
                persistent_cache_dir=persistent_texture_cache_dir,
            )
            return
        elif kind == "opacity":
            notes.append(f"opacity ignored:{label}")

    if material_path:
        material_descriptor = " ".join(
            (
                str(getattr(batch, "preview_material_texture_type", "") or ""),
                str(getattr(batch, "preview_material_texture_subtype", "") or ""),
                str(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                material_path,
            )
        )
        assign_kind(_technical_texture_kind(material_descriptor), material_path, Path(material_path).name)

    for texture_input in material_inputs:
        source = str(getattr(texture_input, "preview_texture_path", "") or "").strip()
        if not source:
            continue
        kind = _input_texture_kind(texture_input)
        label = str(getattr(texture_input, "texture_name", "") or "").strip() or Path(source).name
        if kind and prefer_direct_dds and _direct_material_input_available_for(kind, texture_input):
            notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
            continue
        assign_kind(kind, source, label, texture_input)

    return textures, tuple(dict.fromkeys(note for note in notes if note)), combiner_metadata



__all__ = [
    "_batch_dds_manifest_cache_key",
    "_copy_texture",
    "_dds_manifest_entry",
    "_dds_manifest_entry_is_native_usable",
    "_dds_textures_for_batch",
    "_filter_dds_textures_for_preview_settings",
    "_link_or_copy_file",
    "_materialize_in_memory_texture_key",
    "_materialized_in_memory_batch",
    "_source_dds_for_preview_path",
    "_source_file_stat_key",
    "_split_legacy_pbr_texture",
    "_texture_copy_slot_policy",
    "_texture_sources_for_batch",
]
