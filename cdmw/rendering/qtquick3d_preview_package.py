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
from urllib.parse import unquote, urlparse

from PySide6.QtGui import QColor, QImage

from cdmw.core.dds_native import dds_native_report_dict, dds_source_path_from_report, inspect_dds_native_path
from cdmw.core.texture_native import read_native_texture_report_sidecar
from cdmw.models import (
    ClothPreviewBatch,
    ClothPreviewConstraint,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
)


ISOLATED_PREVIEW_SCHEMA_VERSION = 5
SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS = {1, 2, 3, 4, 5}
ISOLATED_PREVIEW_VERTEX_FLOATS = 23
ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES = ISOLATED_PREVIEW_VERTEX_FLOATS * 4
_VERTEX_STRUCT = struct.Struct("<23f")
_IDENTITY_STRUCT = struct.Struct("<ii")


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


def _write_editor_identity_blob(
    package_dir: Path,
    geometry_dir: Path,
    batch_index: int,
    batch: PreparedModelPreviewBatch,
    vertex_count: int,
) -> Dict[str, object]:
    source_submesh_index = _safe_int(getattr(batch, "source_submesh_index", -1), -1)
    raw_source_vertices = tuple(int(index) for index in tuple(getattr(batch, "source_vertex_indices", ()) or ()))
    identity_path = geometry_dir / f"batch_{batch_index:03d}_identity.bin"
    with identity_path.open("wb") as stream:
        for vertex_offset in range(vertex_count):
            source_vertex_index = (
                int(raw_source_vertices[vertex_offset])
                if vertex_offset < len(raw_source_vertices)
                else int(vertex_offset)
            )
            stream.write(_IDENTITY_STRUCT.pack(source_submesh_index, source_vertex_index))
    return {
        "source_submesh_index": source_submesh_index,
        "source_vertex_count": len(raw_source_vertices),
        "identity_file": identity_path.relative_to(package_dir).as_posix(),
        "role": str(getattr(batch, "editor_role", "") or ""),
        "part_name": str(getattr(batch, "editor_part_name", "") or ""),
        "editable": bool(getattr(batch, "editor_editable", source_submesh_index >= 0)),
    }


def _write_cloth_runtime_payloads(
    package_dir: Path,
    geometry_dir: Path,
    batch_index: int,
    cloth_batch: object,
) -> Dict[str, object]:
    if not isinstance(cloth_batch, ClothPreviewBatch):
        return {}
    positions = tuple(getattr(cloth_batch, "positions", ()) or ())
    constraints = tuple(getattr(cloth_batch, "constraints", ()) or ())
    pin_weights = tuple(float(value) for value in tuple(getattr(cloth_batch, "pin_weights", ()) or ()))
    particle_count = len(positions)
    if particle_count <= 0:
        return {}
    if len(pin_weights) != particle_count:
        pin_weights = tuple(0.0 for _ in range(particle_count))

    particle_path = geometry_dir / f"batch_{batch_index:03d}_cloth_particles.bin"
    with particle_path.open("wb") as stream:
        for position in positions:
            try:
                x, y, z = (float(position[0]), float(position[1]), float(position[2]))
            except (TypeError, ValueError, IndexError, OverflowError):
                x, y, z = 0.0, 0.0, 0.0
            stream.write(struct.pack("<3f", x, y, z))

    pin_path = geometry_dir / f"batch_{batch_index:03d}_cloth_pins.bin"
    with pin_path.open("wb") as stream:
        for weight in pin_weights:
            stream.write(struct.pack("<f", max(0.0, min(1.0, _safe_float(weight, 0.0)))))

    constraint_path = geometry_dir / f"batch_{batch_index:03d}_cloth_constraints.bin"
    written_constraints = 0
    with constraint_path.open("wb") as stream:
        for constraint in constraints:
            if not isinstance(constraint, ClothPreviewConstraint):
                continue
            a = _safe_int(getattr(constraint, "a", -1), -1)
            b = _safe_int(getattr(constraint, "b", -1), -1)
            if a < 0 or b < 0 or a >= particle_count or b >= particle_count or a == b:
                continue
            rest_length = max(0.0, _safe_float(getattr(constraint, "rest_length", 0.0), 0.0))
            stiffness = max(0.0, min(1.0, _safe_float(getattr(constraint, "stiffness", 0.0), 0.0)))
            stream.write(struct.pack("<ii2f", a, b, rest_length, stiffness))
            written_constraints += 1

    material = getattr(cloth_batch, "material_settings", None)
    return {
        "cloth_enabled": True,
        "cloth_kind": str(getattr(cloth_batch, "simulation_kind", "cloth") or "cloth"),
        "cloth_material_name": str(getattr(cloth_batch, "simulation_material_name", "") or ""),
        "cloth_particle_file": particle_path.relative_to(package_dir).as_posix(),
        "cloth_pin_file": pin_path.relative_to(package_dir).as_posix(),
        "cloth_constraint_file": constraint_path.relative_to(package_dir).as_posix(),
        "cloth_particle_count": particle_count,
        "cloth_constraint_count": written_constraints,
        "cloth_gravity": _safe_float(getattr(material, "gravity", -10.0), -10.0),
        "cloth_damping": _safe_float(getattr(material, "damping", 0.65), 0.65),
        "cloth_air_resistance": _safe_float(getattr(material, "air_resistance", 1.0), 1.0),
        "cloth_wind_response": _safe_float(getattr(material, "wind_response", 0.4), 0.4),
        "cloth_solver_iterations": max(1, min(64, _safe_int(getattr(material, "solver_iterations", 30), 30))),
        "cloth_collision_enabled": bool(getattr(material, "collision_enabled", True)),
    }


def _tuple3(value: object) -> Tuple[float, float, float]:
    try:
        raw = tuple(value)  # type: ignore[arg-type]
        result = (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return ()
    return result if all(math.isfinite(component) for component in result) else ()


def _write_cloth_collider_payload(
    model: object,
    package_dir: Path,
    geometry_dir: Path,
) -> Tuple[str, int]:
    overlay = getattr(model, "physics_overlay", None)
    shapes = tuple(getattr(overlay, "shapes", ()) or ())
    if not shapes:
        return "", 0
    collider_path = geometry_dir / "cloth_colliders.bin"
    collider_count = 0
    with collider_path.open("wb") as stream:
        for shape in shapes[:512]:
            center = _tuple3(getattr(shape, "center", ()) or ())
            radius = max(0.0, _safe_float(getattr(shape, "radius", 0.0), 0.0))
            capsule_start = _tuple3(getattr(shape, "capsule_start", ()) or ())
            capsule_end = _tuple3(getattr(shape, "capsule_end", ()) or ())
            bounds_min = _tuple3(getattr(shape, "bounds_min", ()) or ())
            bounds_max = _tuple3(getattr(shape, "bounds_max", ()) or ())
            if capsule_start and capsule_end and radius > 0.0:
                record = (2.0, *capsule_start, *capsule_end, radius, 0.0, 0.0, 0.0)
            elif center and radius > 0.0:
                record = (1.0, *center, radius, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            elif bounds_min and bounds_max:
                record = (3.0, *bounds_min, *bounds_max, 0.0, 0.0, 0.0, 0.0)
            else:
                vertices = tuple(getattr(shape, "vertices", ()) or ())
                points = [_tuple3(vertex) for vertex in vertices[:1024]]
                points = [point for point in points if point]
                if not points:
                    continue
                xs, ys, zs = zip(*points)
                record = (3.0, min(xs), min(ys), min(zs), max(xs), max(ys), max(zs), 0.0, 0.0, 0.0, 0.0)
            stream.write(struct.pack("<11f", *record))
            collider_count += 1
    if collider_count <= 0:
        try:
            collider_path.unlink()
        except OSError:
            pass
        return "", 0
    return collider_path.relative_to(package_dir).as_posix(), collider_count


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


def _normalized_shader_family(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    compact = "".join(ch for ch in text if ch.isalnum())
    if "skin" in compact and "skinnedmesh" not in compact:
        return "skin"
    if "hair" in compact:
        return "hair"
    if "cloth" in compact:
        return "cloth_v2" if "v2" in compact or "ver2" in compact else "cloth"
    if "emissive" in compact:
        return "emissive_v2" if "v2" in compact or "ver2" in compact else "emissive"
    if "static" in compact and ("multi" in compact or "rgbtexture" in compact):
        return "static_multitextured"
    if "static" in compact:
        return "static_standard"
    if "standard" in compact:
        return "standard_v2" if "v2" in compact or "ver2" in compact else "standard"
    return text.replace(" ", "_")


def _material_contract_shader_family(batch: PreparedModelPreviewBatch) -> str:
    candidates: list[str] = []
    direct = str(getattr(batch, "preview_sidecar_shader_family", "") or "").strip()
    if direct:
        candidates.append(direct)
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if isinstance(texture_input, PreviewMaterialTextureInput):
            shader_family = str(getattr(texture_input, "shader_family", "") or "").strip()
            if shader_family:
                candidates.append(shader_family)
    if not candidates:
        return ""
    normalized = [_normalized_shader_family(value) for value in candidates]
    for preferred in (
        "skin",
        "hair",
        "cloth_v2",
        "cloth",
        "standard_v2",
        "standard",
        "static_multitextured",
        "static_standard",
        "emissive_v2",
        "emissive",
    ):
        if preferred in normalized:
            return preferred
    return normalized[0]


def _material_decode_policy(shader_family: str) -> Dict[str, object]:
    family = str(shader_family or "").strip().lower()
    policies: Dict[str, Dict[str, object]] = {
        "skin": {
            "roughness_source": "sidecar skin roughness/detail parameters",
            "metalness_scale": 0.08,
            "specular_scale": 0.45,
            "layered_diffuse": True,
        },
        "hair": {
            "roughness_source": "hair flow/specular parameters",
            "metalness_scale": 0.02,
            "specular_scale": 0.70,
            "anisotropic_hint": True,
        },
        "cloth": {
            "roughness_source": "cloth material/detail mask parameters",
            "metalness_scale": 0.12,
            "specular_scale": 0.38,
            "layered_diffuse": True,
        },
        "cloth_v2": {
            "roughness_source": "cloth v2 colorBlend/detail/grime parameters",
            "metalness_scale": 0.16,
            "specular_scale": 0.42,
            "layered_diffuse": True,
        },
        "standard": {
            "roughness_source": "standard material mask/specular parameters",
            "metalness_scale": 0.62,
            "specular_scale": 0.82,
            "layered_diffuse": True,
        },
        "standard_v2": {
            "roughness_source": "standard v2 material/detail/grime parameters",
            "metalness_scale": 0.78,
            "specular_scale": 0.90,
            "layered_diffuse": True,
        },
        "static_standard": {
            "roughness_source": "static material mask parameters",
            "metalness_scale": 0.72,
            "specular_scale": 0.80,
            "layered_diffuse": False,
        },
        "static_multitextured": {
            "roughness_source": "rgbTexture layer material parameters",
            "metalness_scale": 0.70,
            "specular_scale": 0.78,
            "layered_diffuse": True,
        },
        "emissive_v2": {
            "roughness_source": "emissive v2 standard/detail parameters",
            "metalness_scale": 0.42,
            "specular_scale": 0.68,
            "layered_diffuse": True,
            "emissive_hint": True,
        },
    }
    policy = dict(policies.get(family, {}))
    if not policy:
        policy = {
            "roughness_source": "generic material mask/specular fallback",
            "metalness_scale": 0.55,
            "specular_scale": 0.72,
            "layered_diffuse": False,
            "unknown_family": bool(family),
        }
    policy["family"] = family or "generic"
    return policy


def _texture_slot_state(slot_name: str, textures: Mapping[str, str], dds_textures: Mapping[str, object]) -> Dict[str, object]:
    dds_entry = dds_textures.get(slot_name)
    direct_dds = bool(
        isinstance(dds_entry, Mapping)
        and dds_entry.get("available")
        and dds_entry.get("source_path")
        and dds_entry.get("direct_upload_candidate")
    )
    return {
        "slot": slot_name,
        "preview_path": str(textures.get(slot_name, "") or ""),
        "source_dds_path": str(dds_entry.get("source_path", "") or "") if isinstance(dds_entry, Mapping) else "",
        "source_width": _safe_int(dds_entry.get("width"), 0) if isinstance(dds_entry, Mapping) else 0,
        "source_height": _safe_int(dds_entry.get("height"), 0) if isinstance(dds_entry, Mapping) else 0,
        "direct_dds": direct_dds,
        "status": "direct_dds" if direct_dds else ("preview_png" if textures.get(slot_name) else "missing"),
    }


def _material_contract_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    combiner_metadata: Mapping[str, object],
) -> Dict[str, object]:
    shader_family = _material_contract_shader_family(batch)
    hints = _native_material_hints_for_batch(batch)
    slot_states = {
        slot_name: _texture_slot_state(slot_name, textures, dds_textures)
        for slot_name in ("base", "normal", "material", "occlusion", "roughness", "metalness", "specular", "height")
    }
    return {
        "schema_version": 1,
        "shader_family": shader_family or "generic",
        "decode_policy": _material_decode_policy(shader_family),
        "material_hints": hints,
        "texture_slots": slot_states,
        "packed_channels": list(tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())),
        "material_input_count": sum(
            1
            for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
            if isinstance(texture_input, PreviewMaterialTextureInput)
        ),
        "combiner_active": bool(combiner_metadata.get("active", False)),
        "combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
        "fallback": "generic" if not shader_family else "",
    }


def _texture_quality_summary(
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    settings: ModelPreviewRenderSettings,
    high_quality_textures: bool,
) -> Dict[str, object]:
    support_cap = int(getattr(settings, "low_quality_texture_max_dimension", 2048) or 2048)
    base_cap = int(getattr(settings, "preview_texture_max_dimension", 16384) or 16384)
    slots = {
        slot_name: _texture_slot_state(slot_name, textures, dds_textures)
        for slot_name in ("base", "normal", "material", "occlusion", "roughness", "metalness", "specular", "height")
    }
    for slot_name, slot in slots.items():
        cap = base_cap if slot_name == "base" else support_cap
        slot["preview_cap"] = cap
        width = _safe_int(slot.get("source_width"), 0)
        height = _safe_int(slot.get("source_height"), 0)
        slot["source_exceeds_preview_cap"] = bool(max(width, height) > cap > 0)
        slot["safe_upscale_candidate"] = bool(slot_name == "base" and (slot.get("source_dds_path") or slot.get("preview_path")))
    low_resolution_base = False
    base = slots["base"]
    if base.get("source_width") and base.get("source_height"):
        low_resolution_base = max(_safe_int(base.get("source_width"), 0), _safe_int(base.get("source_height"), 0)) < 1024
    return {
        "schema_version": 1,
        "preview_texture_max_dimension": base_cap,
        "support_texture_max_dimension": support_cap,
        "high_quality_textures": bool(high_quality_textures),
        "slots": slots,
        "low_resolution_base": low_resolution_base,
        "upscale_handoff_policy": "opt-in visible/base textures only; technical maps preserved by default",
    }


def _combiner_generated_authoritative_albedo(combiner_metadata: Mapping[str, object]) -> bool:
    notes = tuple(str(note or "").strip().lower() for note in tuple(combiner_metadata.get("notes", ()) or ()))
    outputs = {str(output or "").strip().lower() for output in tuple(combiner_metadata.get("outputs", ()) or ())}
    return bool("albedo" in outputs and any(note.startswith("albedo synthesized") for note in notes))


def _normalized_material_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _byte4_channels(value: object) -> Tuple[float, float, float, float]:
    text = str(value or "").strip()
    if not text:
        return ()
    try:
        integer = int(text, 0)
    except (TypeError, ValueError, OverflowError):
        return ()
    integer = max(0, min(0xFFFFFFFF, integer))
    return tuple(((integer >> (8 * index)) & 0xFF) / 255.0 for index in range(4))  # type: ignore[return-value]


def _native_material_hints_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    inputs = tuple(
        texture_input
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )
    shader_families = tuple(
        dict.fromkeys(
            str(getattr(texture_input, "shader_family", "") or "").strip()
            for texture_input in inputs
            if str(getattr(texture_input, "shader_family", "") or "").strip()
        )
    )
    roughness_values: list[float] = []
    metalness_values: list[float] = []
    specular_values: list[float] = []
    height_values: list[float] = []
    for texture_input in inputs:
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            key = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if not key:
                continue
            numeric_value = getattr(parameter, "numeric_value", None)
            if numeric_value is not None:
                numeric = _clamp01(numeric_value)
                if "screenspacedisplacementscale" in key or "heightintensity" in key:
                    height_values.append(numeric if "heightintensity" in key else min(1.0, numeric * 8.0))
                if "specular" in key or "sheen" in key:
                    specular_values.append(numeric)
                if "roughness" in key:
                    roughness_values.append(numeric)
                if "metallic" in key or "metalness" in key:
                    metalness_values.append(numeric)
                continue
            channels = _byte4_channels(getattr(parameter, "value", ""))
            if not channels:
                continue
            channel_peak = max(channels)
            if "scratchroughness" in key or key.endswith("roughness"):
                roughness_values.append(channel_peak)
            if "scratchmetallic" in key or "metallic" in key or "metalness" in key:
                metalness_values.append(channel_peak)
            if "specular" in key:
                specular_values.append(channel_peak)

    roughness_hint = max(roughness_values) if roughness_values else 0.0
    metalness_hint = max(metalness_values) if metalness_values else 0.0
    specular_hint = max(specular_values) if specular_values else 0.0
    if metalness_hint > 0.02:
        specular_hint = max(specular_hint, 0.14 + (metalness_hint * 0.32))
    return {
        "shader_families": list(shader_families[:4]),
        "roughness": round(float(max(0.0, min(1.0, roughness_hint))), 4),
        "metalness": round(float(max(0.0, min(1.0, metalness_hint * 0.42))), 4),
        "specular": round(float(max(0.0, min(1.0, specular_hint * 0.72))), 4),
        "height_scale": round(float(max(0.0, min(1.0, max(height_values) if height_values else 0.0))), 4),
        "source": "sidecar_parameters" if any((roughness_values, metalness_values, specular_values, height_values)) else "",
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
    cache_key = str(source).casefold()
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
    return report


def _dds_textures_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    inspect_cache: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
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
        slot_name: _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
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
        entry = _dds_manifest_entry(source_path, slot_name=slot_name, inspect_cache=inspect_cache)
        entry["parameter_name"] = str(getattr(texture_input, "parameter_name", "") or "")
        entry["semantic_type"] = str(getattr(texture_input, "semantic_type", "") or "")
        entry["semantic_subtype"] = str(getattr(texture_input, "semantic_subtype", "") or "")
        entry["material_name"] = str(getattr(texture_input, "material_name", "") or "")
        input_entries.append(entry)
    if input_entries:
        output["material_inputs"] = input_entries
    return output


def _filter_dds_textures_for_preview_settings(
    dds_textures: Mapping[str, object],
    batch: PreparedModelPreviewBatch,
    *,
    render_settings: ModelPreviewRenderSettings,
    use_textures: bool,
    high_quality_textures: bool,
) -> Dict[str, object]:
    if not use_textures or not bool(getattr(batch, "has_texture_coordinates", False)):
        return {}
    support_enabled = bool(
        high_quality_textures
        and not bool(getattr(batch, "preview_debug_disable_support_maps", False))
        and not bool(getattr(render_settings, "disable_all_support_maps", False))
    )
    output: Dict[str, object] = {}
    base_entry = dds_textures.get("base")
    if isinstance(base_entry, Mapping):
        output["base"] = dict(base_entry)
    if support_enabled:
        for slot_name, disabled_attr in (
            ("normal", "disable_normal_map"),
            ("material", "disable_material_map"),
            ("height", "disable_height_map"),
        ):
            if bool(getattr(render_settings, disabled_attr, False)):
                continue
            entry = dds_textures.get(slot_name)
            if isinstance(entry, Mapping):
                output[slot_name] = dict(entry)

    def input_role(entry: Mapping[str, object]) -> str:
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
        ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular"}:
            return "base"
        if technical == "normal" or "normal" in descriptor:
            return "normal"
        if technical == "height" or "displacement" in descriptor:
            return "height"
        if technical in {"packed_material", "detail_mask", "specular", "roughness", "metalness"}:
            return "material"
        if any(token in descriptor for token in ("roughness", "metallic", "metalness", "occlusion", "materialmask")):
            return "material"
        if "opacity" in descriptor or "alpha" in descriptor:
            return "opacity"
        return "material"

    input_entries = dds_textures.get("material_inputs")
    if isinstance(input_entries, Sequence) and not isinstance(input_entries, (str, bytes, bytearray)):
        filtered_inputs: list[Dict[str, object]] = []
        for raw_entry in input_entries:
            if not isinstance(raw_entry, Mapping):
                continue
            role = input_role(raw_entry)
            if role == "base":
                filtered_inputs.append(dict(raw_entry))
            elif not support_enabled:
                continue
            elif role == "normal" and not bool(getattr(render_settings, "disable_normal_map", False)):
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
            ):
                if manifest_slot in output:
                    continue
                if promoted_role != "base" and not support_enabled:
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
    tangents_usable: bool,
    copy_cache: Dict[str, str],
    enable_material_combiner: bool = True,
    prefer_direct_dds: bool = False,
    direct_dds_slots: Optional[Mapping[str, object]] = None,
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

    direct_dds_slots = direct_dds_slots if prefer_direct_dds and isinstance(direct_dds_slots, Mapping) else (
        _dds_textures_for_batch(batch) if prefer_direct_dds else {}
    )

    material_inputs: Tuple[PreviewMaterialTextureInput, ...] = tuple(
        texture_input
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )

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

    def _direct_material_source(entry: Mapping[str, object]) -> str:
        try:
            return str(Path(str(entry.get("source_path", "") or "")).expanduser().resolve()).casefold()
        except OSError:
            return str(entry.get("source_path", "") or "").casefold()

    def _source_identity(source_path: str) -> str:
        try:
            return str(Path(str(source_path or "")).expanduser().resolve()).casefold()
        except OSError:
            return str(source_path or "").casefold()

    def _direct_material_input_available_for(kind: str, texture_input: Optional[PreviewMaterialTextureInput] = None) -> bool:
        normalized_kind = str(kind or "").strip().lower()
        direct_source = ""
        if texture_input is not None:
            direct_source = str(getattr(texture_input, "source_dds_path", "") or "").strip()
            if not direct_source:
                direct_source = _source_dds_for_preview_path(str(getattr(texture_input, "preview_texture_path", "") or ""))
        direct_source_key = _source_identity(direct_source) if direct_source else ""
        for entry in _direct_material_input_entries():
            if not _direct_dds_entry_available(entry):
                continue
            if direct_source_key and _direct_material_source(entry) == direct_source_key:
                return True
            descriptor = _direct_material_descriptor(entry)
            technical = _technical_texture_kind(str(entry.get("source_path", "") or ""))
            if normalized_kind == "base":
                if (
                    "base" in descriptor
                    or "albedo" in descriptor
                    or "diffuse" in descriptor
                    or "color" in descriptor
                ) and technical not in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular"}:
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
        source_key = _source_identity(source_path)
        if not source_key:
            return False
        for slot_name in ("base", "normal", "material", "height"):
            entry = direct_dds_slots.get(slot_name)
            if _direct_dds_entry_available(entry) and _direct_material_source(entry) == source_key:
                return True
        for entry in _direct_material_input_entries():
            if _direct_dds_entry_available(entry) and _direct_material_source(entry) == source_key:
                return True
        return False

    def _preview_source_has_direct_dds_upload(preview_path: str) -> bool:
        dds_path = _source_dds_for_preview_path(preview_path)
        return bool(dds_path and _direct_dds_available_for_source(dds_path))

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

    material_path = str(getattr(batch, "preview_material_texture_path", "") or "")
    material_subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    reused_legacy_pbr = False
    if support_enabled and material_path and material_subtype in {"pbr_combined", "legacy_pbr_combined"}:
        if prefer_direct_dds and _direct_material_response_available():
            notes.append("legacy PBR PNG split skipped; direct DDS material inputs available")
        else:
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
            if combined.base_note:
                combiner_metadata["base_note"] = str(combined.base_note)
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
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
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
            if prefer_direct_dds and _preview_source_has_direct_dds_upload(source_path):
                notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
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
        if kind and prefer_direct_dds and _direct_material_input_available_for(kind, texture_input):
            notes.append(f"{kind} PNG fallback skipped; direct DDS material input available")
            continue
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
    display_mode: str = "replacement_only",
    editor_workspace: str = "",
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
    dds_inspect_cache: Dict[str, Dict[str, object]] = {}
    batches: list[Dict[str, object]] = []
    total_vertices = 0
    prepared_batches = tuple(getattr(prepared_preview, "batches", ()) or ())
    has_cloth_batches = any(
        isinstance(getattr(batch, "cloth_preview", None), ClothPreviewBatch)
        for batch in prepared_batches
        if isinstance(batch, PreparedModelPreviewBatch)
    )
    cloth_collider_file, cloth_collider_count = (
        _write_cloth_collider_payload(model, package_dir, geometry_dir)
        if has_cloth_batches
        else ("", 0)
    )
    cloth_batch_count = 0
    cloth_particle_count = 0
    cloth_constraint_count = 0
    for batch_index, batch in enumerate(prepared_batches):
        if not isinstance(batch, PreparedModelPreviewBatch):
            continue
        batch = _materialized_in_memory_batch(
            model,
            batch,
            textures_dir=textures_dir,
            batch_index=batch_index,
        )
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
        editor_identity = _write_editor_identity_blob(
            package_dir,
            geometry_dir,
            batch_index,
            batch,
            vertex_count,
        )
        tangents_usable = _tangents_usable(usable_blob, vertex_count)
        dds_textures = _filter_dds_textures_for_preview_settings(
            _dds_textures_for_batch(batch, inspect_cache=dds_inspect_cache),
            batch,
            render_settings=settings,
            use_textures=bool(use_textures),
            high_quality_textures=bool(high_quality_textures),
        )
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
            direct_dds_slots=dds_textures,
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
        if bool(getattr(settings, "flip_texture_v", False)):
            texture_flip_vertical = not texture_flip_vertical
        prefer_generated_base_texture = bool(
            textures.get("base")
            and _combiner_generated_authoritative_albedo(combiner_metadata)
        )
        if prefer_generated_base_texture:
            notes = tuple(notes) + ("native base DDS bypassed for synthesized sidecar albedo",)
        material_contract = _material_contract_for_batch(
            batch,
            textures=textures,
            dds_textures=dds_textures,
            combiner_metadata=combiner_metadata,
        )
        texture_quality = _texture_quality_summary(
            textures=textures,
            dds_textures=dds_textures,
            settings=settings,
            high_quality_textures=bool(high_quality_textures),
        )
        batch_payload = {
                "index": batch_index,
                "material_name": str(getattr(batch, "material_name", "") or ""),
                "texture_name": str(getattr(batch, "texture_name", "") or ""),
                "vertex_file": geometry_path.relative_to(package_dir).as_posix(),
                "vertex_count": vertex_count,
                "editor_identity": editor_identity,
                "base_color": list(_first_vertex_color(usable_blob)),
                "textures": textures,
                "dds_textures": dds_textures,
                "texture_flip_vertical": texture_flip_vertical,
                "has_texture_coordinates": bool(getattr(batch, "has_texture_coordinates", False)),
                "tangents_usable": tangents_usable,
                "normal_strength": normal_strength,
                "height_amount": height_amount,
                "native_material_hints": _native_material_hints_for_batch(batch),
                "material_contract": material_contract,
                "material_shader_family": str(material_contract.get("shader_family", "generic") or "generic"),
                "prefer_generated_base_texture": prefer_generated_base_texture,
                "texture_quality": texture_quality,
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
        cloth_payload = _write_cloth_runtime_payloads(
            package_dir,
            geometry_dir,
            batch_index,
            getattr(batch, "cloth_preview", None),
        )
        if cloth_payload:
            cloth_batch_count += 1
            cloth_particle_count += _safe_int(cloth_payload.get("cloth_particle_count"), 0)
            cloth_constraint_count += _safe_int(cloth_payload.get("cloth_constraint_count"), 0)
            if not cloth_collider_file:
                cloth_payload["cloth_collision_enabled"] = False
            batch_payload.update(cloth_payload)
        batches.append(batch_payload)

    normalized_display_mode = str(display_mode or "replacement_only").strip().lower()
    if normalized_display_mode not in {"side_by_side", "overlay", "replacement_only"}:
        normalized_display_mode = "replacement_only"
    manifest = {
        "schema_version": ISOLATED_PREVIEW_SCHEMA_VERSION,
        "backend": str(backend or "d3d11").strip().lower(),
        "created_at": time.time(),
        "write_ms": max(0.0, (time.perf_counter() - started) * 1000.0),
        "display_mode": normalized_display_mode,
        "editor_workspace": str(editor_workspace or "").strip(),
        "source_path": str(getattr(prepared_preview, "source_path", "") or getattr(model, "path", "") or ""),
        "format": str(getattr(prepared_preview, "format", "") or getattr(model, "format", "") or ""),
        "summary": str(getattr(prepared_preview, "summary", "") or getattr(model, "summary", "") or ""),
        "mesh_count": _safe_int(getattr(prepared_preview, "mesh_count", 0), 0),
        "vertex_count": total_vertices,
        "face_count": _safe_int(getattr(prepared_preview, "face_count", 0), 0),
        "normalization_center": list(getattr(prepared_preview, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        "normalization_scale": _safe_float(getattr(prepared_preview, "normalization_scale", 1.0), 1.0),
        "render_settings": _render_settings_to_dict(settings),
        "orbit_sensitivity": _safe_float(getattr(settings, "orbit_sensitivity", 0.22), 0.22),
        "pan_sensitivity": _safe_float(getattr(settings, "pan_sensitivity", 0.60), 0.60),
        "invert_orbit_x": bool(getattr(settings, "invert_orbit_x", False)),
        "invert_orbit_y": bool(getattr(settings, "invert_orbit_y", False)),
        "invert_pan_x": bool(getattr(settings, "invert_pan_x", False)),
        "invert_pan_y": bool(getattr(settings, "invert_pan_y", False)),
        "use_textures": bool(use_textures),
        "high_quality_textures": bool(high_quality_textures),
        "material_contract_schema": 1,
        "texture_quality_schema": 1,
        "texture_quality_policy": {
            "preview_texture_max_dimension": int(getattr(settings, "preview_texture_max_dimension", 16384) or 16384),
            "support_texture_max_dimension": int(getattr(settings, "low_quality_texture_max_dimension", 2048) or 2048),
            "upscale_handoff": "opt-in visible/base textures only",
            "technical_map_default": "preserve",
        },
        "cloth_runtime_schema": 1,
        "cloth_batch_count": cloth_batch_count,
        "cloth_particle_count": cloth_particle_count,
        "cloth_constraint_count": cloth_constraint_count,
        "cloth_collider_file": cloth_collider_file,
        "cloth_collider_count": cloth_collider_count,
        "batches": batches,
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
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
