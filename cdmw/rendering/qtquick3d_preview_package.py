from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from PySide6.QtGui import QColor, QImage

from cdmw.core.dds_native import dds_native_report_dict, dds_source_path_from_report, inspect_dds_native_path
from cdmw.core.texture_native import read_native_texture_report_sidecar
from cdmw.models import (
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
)


ISOLATED_PREVIEW_SCHEMA_VERSION = 2
SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS = {1, 2}
ISOLATED_PREVIEW_VERTEX_FLOATS = 23
ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES = ISOLATED_PREVIEW_VERTEX_FLOATS * 4
_VERTEX_STRUCT = struct.Struct("<23f")


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _clamp01(value: object, fallback: float = 0.0) -> float:
    return max(0.0, min(1.0, _safe_float(value, fallback)))


def _first_vertex_color(vertex_blob: bytes) -> Tuple[float, float, float]:
    if len(vertex_blob) < ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES:
        return (0.78, 0.48, 0.34)
    try:
        vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, 0)
    except struct.error:
        return (0.78, 0.48, 0.34)
    return (
        _clamp01(vertex[6], 0.78),
        _clamp01(vertex[7], 0.48),
        _clamp01(vertex[8], 0.34),
    )


def _vector_length(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def _tangents_usable(vertex_blob: bytes, vertex_count: int) -> bool:
    if vertex_count <= 0:
        return False
    usable_count = min(vertex_count, len(vertex_blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
    if usable_count <= 0:
        return False
    checked = 0
    valid = 0
    for offset in range(0, usable_count * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES):
        try:
            vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, offset)
        except struct.error:
            continue
        normal = vertex[3:6]
        uv = vertex[9:11]
        tangent = vertex[11:14]
        bitangent = vertex[14:17]
        checked += 1
        if (
            all(math.isfinite(float(value)) for value in (*normal, *uv, *tangent, *bitangent))
            and _vector_length(normal) > 0.05
            and _vector_length(tangent) > 0.05
            and _vector_length(bitangent) > 0.05
        ):
            valid += 1
    return bool(checked > 0 and valid / float(checked) >= 0.80)


def _suffix_tokens(name: str) -> Tuple[str, ...]:
    lower = str(name or "").replace("\\", "/").split("/")[-1].lower()
    stem = lower.rsplit(".", 1)[0]
    return tuple(token for token in stem.replace("-", "_").split("_") if token)


def _contains_token(name: str, *tokens: str) -> bool:
    haystack = " ".join((str(name or "").lower(), " ".join(_suffix_tokens(name))))
    return any(str(token).lower() in haystack for token in tokens)


def _technical_texture_kind(name: str) -> str:
    tokens = _suffix_tokens(name)
    lower = str(name or "").lower()
    if any(token in tokens for token in ("n", "normal")) or lower.endswith("_n.dds"):
        return "normal"
    if any(token in tokens for token in ("disp", "height", "displacement")):
        return "height"
    if any(token in tokens for token in ("sp", "spec", "specular")):
        return "specular"
    if any(token in tokens for token in ("rough", "roughness")):
        return "roughness"
    if any(token in tokens for token in ("metal", "metallic", "metalness")):
        return "metalness"
    if any(token in tokens for token in ("ma", "orm", "rma", "mra", "arm")):
        return "packed_material"
    if any(token in tokens for token in ("mg", "mask", "detail")):
        return "detail_mask"
    if any(token in tokens for token in ("opacity", "alpha")):
        return "opacity"
    return ""


def _input_texture_kind(texture_input: PreviewMaterialTextureInput) -> str:
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
    names = " ".join(
        (
            slot_kind,
            semantic_type,
            semantic_subtype,
            parameter_name,
            str(getattr(texture_input, "texture_name", "") or ""),
            str(getattr(texture_input, "source_texture_path", "") or ""),
            str(getattr(texture_input, "preview_texture_path", "") or ""),
        )
    )
    if slot_kind == "base" or semantic_type in {"base", "base_color", "diffuse", "albedo", "color"}:
        technical = _technical_texture_kind(names)
        return "" if technical in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular"} else "base"
    if slot_kind == "normal" or semantic_type == "normal" or _contains_token(names, "normal"):
        return "normal"
    if slot_kind == "height" or semantic_type in {"height", "displacement"} or _contains_token(names, "disp", "height"):
        return "height"
    if semantic_subtype in {"roughness", "rough"} or _contains_token(names, "roughness"):
        return "roughness"
    if semantic_subtype in {"metal", "metallic", "metalness"} or _contains_token(names, "metallic", "metalness"):
        return "metalness"
    if semantic_subtype in {"specular", "spec"} or _contains_token(names, "specular"):
        return "specular"
    technical = _technical_texture_kind(names)
    if technical in {"specular", "roughness", "metalness", "height", "normal", "opacity", "packed_material", "detail_mask"}:
        return technical
    return ""


def _copy_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    slot_name: str,
    copy_cache: Dict[str, str],
    notes: list[str],
) -> str:
    raw = str(source_path or "").strip()
    if not raw:
        return ""
    try:
        source = Path(raw).expanduser()
    except OSError:
        notes.append(f"{slot_name} invalid path")
        return ""
    if not source.is_file():
        notes.append(f"{slot_name} missing texture:{Path(raw).name}")
        return ""
    try:
        key = str(source.resolve()).casefold()
    except OSError:
        key = str(source).casefold()
    cached = copy_cache.get(key)
    if cached:
        return cached
    suffix = source.suffix if source.suffix else ".png"
    target = textures_dir / f"batch_{batch_index:03d}_{slot_name}_{len(copy_cache):03d}{suffix}"
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        notes.append(f"{slot_name} copy failed:{exc}")
        return ""
    relative = target.relative_to(package_dir).as_posix()
    copy_cache[key] = relative
    return relative


def _split_legacy_pbr_texture(
    source_path: str,
    *,
    package_dir: Path,
    textures_dir: Path,
    batch_index: int,
    notes: list[str],
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


def _render_settings_to_dict(settings: Optional[ModelPreviewRenderSettings]) -> Dict[str, object]:
    value = clamp_model_preview_render_settings(settings)
    return {
        field_info.name: getattr(value, field_info.name)
        for field_info in dataclasses.fields(ModelPreviewRenderSettings)
    }


def _material_input_to_dict(texture_input: PreviewMaterialTextureInput) -> Dict[str, object]:
    def to_jsonable(value: object) -> object:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field_info.name: to_jsonable(getattr(value, field_info.name))
                for field_info in dataclasses.fields(value)
            }
        if isinstance(value, tuple):
            return [to_jsonable(item) for item in value]
        if isinstance(value, list):
            return [to_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): to_jsonable(item) for key, item in value.items()}
        return value

    return {
        field_info.name: to_jsonable(getattr(texture_input, field_info.name))
        for field_info in dataclasses.fields(PreviewMaterialTextureInput)
    }


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


def _dds_manifest_entry(source_path: str, *, slot_name: str, reason: str = "") -> Dict[str, object]:
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
            "slot": str(slot_name or ""),
            "available": True,
            "direct_upload_candidate": bool(report.get("supported_compressed", False)),
        }
    )
    if reason:
        report["reason"] = reason
    return report


def _dds_textures_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    slots = {
        "base": str(getattr(batch, "preview_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_texture_path", "") or "")),
        "normal": str(getattr(batch, "preview_normal_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_normal_texture_path", "") or "")),
        "material": str(getattr(batch, "preview_material_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_material_texture_path", "") or "")),
        "height": str(getattr(batch, "preview_height_texture_dds_path", "") or "")
        or _source_dds_for_preview_path(str(getattr(batch, "preview_height_texture_path", "") or "")),
    }
    output: Dict[str, object] = {
        slot_name: _dds_manifest_entry(source_path, slot_name=slot_name)
        for slot_name, source_path in slots.items()
        if str(source_path or "").strip()
    }
    input_entries: list[Dict[str, object]] = []
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        source_path = str(getattr(texture_input, "source_dds_path", "") or "").strip()
        if not source_path:
            source_path = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        if not source_path:
            continue
        slot_name = str(getattr(texture_input, "slot_kind", "") or "material").strip().lower() or "material"
        entry = _dds_manifest_entry(source_path, slot_name=slot_name)
        entry["parameter_name"] = str(getattr(texture_input, "parameter_name", "") or "")
        entry["semantic_type"] = str(getattr(texture_input, "semantic_type", "") or "")
        entry["semantic_subtype"] = str(getattr(texture_input, "semantic_subtype", "") or "")
        entry["material_name"] = str(getattr(texture_input, "material_name", "") or "")
        input_entries.append(entry)
    if input_entries:
        output["material_inputs"] = input_entries
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
    tangents_usable: bool,
    copy_cache: Dict[str, str],
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
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

    direct_dds_slots = _dds_textures_for_batch(batch) if prefer_direct_dds else {}

    def has_direct_dds(slot_name: str) -> bool:
        entry = direct_dds_slots.get(slot_name)
        return bool(isinstance(entry, Mapping) and entry.get("available") and entry.get("source_path"))

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
            )

    base_path = str(getattr(batch, "preview_texture_path", "") or "")
    if base_path:
        if has_direct_dds("base"):
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
            )
    else:
        notes.append("no reliable base DDS")

    if support_enabled and not bool(getattr(render_settings, "disable_normal_map", False)):
        if has_direct_dds("normal"):
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
            )

    material_inputs: Tuple[PreviewMaterialTextureInput, ...] = tuple(
        texture_input
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )
    material_path = str(getattr(batch, "preview_material_texture_path", "") or "")
    material_subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    reused_legacy_pbr = False
    if support_enabled and material_path and material_subtype in {"pbr_combined", "legacy_pbr_combined"}:
        generated = _split_legacy_pbr_texture(
            material_path,
            package_dir=package_dir,
            textures_dir=textures_dir,
            batch_index=batch_index,
            notes=notes,
        )
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
            from cdmw.ui.model_preview_material_combiner import (
                MaterialPreviewCombinerSettings,
                combine_preview_material,
                synthesize_material_texture_inputs,
            )

            synthesized_inputs = synthesize_material_texture_inputs(batch)
            combiner_payload = SimpleNamespace(
                material_name=str(getattr(batch, "material_name", "") or ""),
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                texture_flip_vertical=bool(getattr(batch, "preview_texture_flip_vertical", True)),
                material_texture_inputs=synthesized_inputs,
                tangents_usable=bool(tangents_usable),
                normal_texture_strength=max(0.0, _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0)),
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
            notes.extend(str(note) for note in tuple(combined.notes or ()) if str(note))
            if combined.base_source:
                textures["base"] = package_relative(combined.base_source, "base")
            if support_enabled and not bool(getattr(render_settings, "disable_normal_map", False)) and combined.normal_source:
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
            if combined.normal_source:
                combiner_metadata["normal_strength"] = float(combined.normal_strength)
            combiner_metadata["texture_flip_vertical"] = bool(combined.texture_flip_vertical)
        except Exception as exc:
            notes.append(f"material combiner failed:{exc}")

    def assign_kind(kind: str, source_path: str, label: str) -> None:
        combiner_decoded = bool(tuple(combiner_metadata.get("decode_modes", ()) or ()) or tuple(combiner_metadata.get("outputs", ()) or ()))
        if kind in {"base", "normal", "height"}:
            if textures.get(kind):
                return
            textures[kind] = _copy_texture(
                source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
            )
            return
        if kind in {"roughness", "metalness", "specular"}:
            if not support_enabled or bool(getattr(render_settings, f"disable_material_map", False)):
                return
            if textures.get(kind):
                return
            textures[kind] = _copy_texture(
                source_path,
                package_dir=package_dir,
                textures_dir=textures_dir,
                batch_index=batch_index,
                slot_name=kind,
                copy_cache=copy_cache,
                notes=notes,
            )
            return
        if kind == "packed_material":
            if not combiner_decoded:
                notes.append(f"packed material map skipped:{label}")
        elif kind == "detail_mask":
            if not combiner_decoded:
                notes.append(f"detail mask skipped:{label}")
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
        assign_kind(kind, source, label)

    return textures, tuple(dict.fromkeys(note for note in notes if note)), combiner_metadata


def write_isolated_qtquick3d_preview_package(
    model: object,
    prepared_preview: PreparedModelPreviewData,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    use_textures: bool = True,
    high_quality_textures: bool = True,
    backend: str = "d3d11",
    output_root: Optional[Path] = None,
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
) -> Path:
    if not isinstance(prepared_preview, PreparedModelPreviewData):
        raise TypeError("prepared_preview must be PreparedModelPreviewData")
    started = time.perf_counter()
    if output_root is None:
        package_dir = Path(tempfile.mkdtemp(prefix="cdmw_isolated_d3d11_"))
    else:
        package_dir = Path(output_root).expanduser()
        package_dir.mkdir(parents=True, exist_ok=True)
    textures_dir = package_dir / "textures"
    geometry_dir = package_dir / "geometry"
    textures_dir.mkdir(parents=True, exist_ok=True)
    geometry_dir.mkdir(parents=True, exist_ok=True)

    settings = clamp_model_preview_render_settings(render_settings)
    copy_cache: Dict[str, str] = {}
    batches: list[Dict[str, object]] = []
    total_vertices = 0
    for batch_index, batch in enumerate(tuple(getattr(prepared_preview, "batches", ()) or ())):
        if not isinstance(batch, PreparedModelPreviewBatch):
            continue
        blob = bytes(getattr(batch, "vertex_blob", b"") or b"")
        vertex_count = max(
            0,
            min(_safe_int(getattr(batch, "index_count", 0), 0), len(blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
        )
        if vertex_count <= 0:
            continue
        usable_blob = blob[: vertex_count * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES]
        geometry_path = geometry_dir / f"batch_{batch_index:03d}.bin"
        geometry_path.write_bytes(usable_blob)
        tangents_usable = _tangents_usable(usable_blob, vertex_count)
        textures, notes, combiner_metadata = _texture_sources_for_batch(
            batch,
            package_dir=package_dir,
            textures_dir=textures_dir,
            batch_index=batch_index,
            render_settings=settings,
            use_textures=bool(use_textures),
            high_quality_textures=bool(high_quality_textures),
            tangents_usable=tangents_usable,
            copy_cache=copy_cache,
            enable_material_combiner=bool(enable_material_combiner),
            prefer_direct_dds=bool(prefer_direct_dds),
        )
        total_vertices += vertex_count
        normal_strength = max(
            _safe_float(getattr(settings, "normal_strength_floor", 0.5), 0.5),
            min(
                _safe_float(getattr(settings, "normal_strength_cap", 1.0), 1.0),
                _safe_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0),
            ),
        )
        if _safe_float(combiner_metadata.get("normal_strength", 0.0), 0.0) > 0.0:
            normal_strength = _safe_float(combiner_metadata.get("normal_strength"), normal_strength)
        height_amount = max(0.0, min(0.08, _safe_float(getattr(settings, "height_effect_max", 0.35), 0.35) * 0.08))
        if _safe_float(combiner_metadata.get("height_amount", 0.0), 0.0) > 0.0:
            height_amount = max(0.0, min(0.12, _safe_float(combiner_metadata.get("height_amount"), height_amount)))
        texture_flip_vertical = bool(getattr(batch, "preview_texture_flip_vertical", True))
        if "texture_flip_vertical" in combiner_metadata:
            texture_flip_vertical = bool(combiner_metadata.get("texture_flip_vertical", texture_flip_vertical))
        batches.append(
            {
                "index": batch_index,
                "material_name": str(getattr(batch, "material_name", "") or ""),
                "texture_name": str(getattr(batch, "texture_name", "") or ""),
                "vertex_file": geometry_path.relative_to(package_dir).as_posix(),
                "vertex_count": vertex_count,
                "base_color": list(_first_vertex_color(usable_blob)),
                "textures": textures,
                "dds_textures": _dds_textures_for_batch(batch),
                "texture_flip_vertical": texture_flip_vertical,
                "has_texture_coordinates": bool(getattr(batch, "has_texture_coordinates", False)),
                "tangents_usable": tangents_usable,
                "normal_strength": normal_strength,
                "height_amount": height_amount,
                "notes": list(notes),
                "material_combiner_active": bool(combiner_metadata.get("active", False)),
                "material_combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
                "material_combiner_decode_modes": list(tuple(combiner_metadata.get("decode_modes", ()) or ())),
                "material_combiner_notes": list(tuple(combiner_metadata.get("notes", ()) or ())),
                "material_inputs": [
                    _material_input_to_dict(texture_input)
                    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
                    if isinstance(texture_input, PreviewMaterialTextureInput)
                ],
            }
        )

    manifest = {
        "schema_version": ISOLATED_PREVIEW_SCHEMA_VERSION,
        "backend": str(backend or "d3d11").strip().lower(),
        "created_at": time.time(),
        "write_ms": max(0.0, (time.perf_counter() - started) * 1000.0),
        "source_path": str(getattr(prepared_preview, "source_path", "") or getattr(model, "path", "") or ""),
        "format": str(getattr(prepared_preview, "format", "") or getattr(model, "format", "") or ""),
        "summary": str(getattr(prepared_preview, "summary", "") or getattr(model, "summary", "") or ""),
        "mesh_count": _safe_int(getattr(prepared_preview, "mesh_count", 0), 0),
        "vertex_count": total_vertices,
        "face_count": _safe_int(getattr(prepared_preview, "face_count", 0), 0),
        "normalization_center": list(getattr(prepared_preview, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        "normalization_scale": _safe_float(getattr(prepared_preview, "normalization_scale", 1.0), 1.0),
        "render_settings": _render_settings_to_dict(settings),
        "use_textures": bool(use_textures),
        "high_quality_textures": bool(high_quality_textures),
        "batches": batches,
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return package_dir


def read_isolated_qtquick3d_preview_manifest(package_dir: Path) -> Mapping[str, Any]:
    manifest_path = Path(package_dir).expanduser() / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("isolated preview manifest is not a JSON object")
    if _safe_int(data.get("schema_version"), 0) not in SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported isolated preview schema version: {data.get('schema_version')!r}")
    return data


__all__ = [
    "ISOLATED_PREVIEW_SCHEMA_VERSION",
    "ISOLATED_PREVIEW_VERTEX_FLOATS",
    "ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES",
    "SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS",
    "read_isolated_qtquick3d_preview_manifest",
    "write_isolated_qtquick3d_preview_package",
]
