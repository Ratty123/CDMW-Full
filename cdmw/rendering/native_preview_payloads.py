from __future__ import annotations

import dataclasses
import math
import re
import struct
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from cdmw.core.model_preview_orientation import resolve_preview_texture_flip_vertical
from cdmw.models import (
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
)

ISOLATED_PREVIEW_VERTEX_FLOATS = 23
ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES = ISOLATED_PREVIEW_VERTEX_FLOATS * 4
_VERTEX_STRUCT = struct.Struct("<23f")


@dataclasses.dataclass(frozen=True)
class NativePreviewBatchPayload:
    material_name: str = ""
    texture_name: str = ""
    vertex_count: int = 0
    bounds_min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    base_color: Tuple[float, float, float] = (0.78, 0.48, 0.34)
    texture_source: str = ""
    normal_texture_source: str = ""
    material_texture_source: str = ""
    height_texture_source: str = ""
    normal_texture_strength: float = 1.0
    material_texture_packed_channels: Tuple[str, ...] = ()
    material_texture_slots: Tuple[str, ...] = ()
    material_texture_inputs: Tuple[PreviewMaterialTextureInput, ...] = ()
    texture_flip_vertical: bool = False
    has_texture_coordinates: bool = False
    tangents_usable: bool = False


def _local_file_url(path_value: object) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("file:"):
        return text
    try:
        path = Path(text).expanduser()
    except OSError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.resolve().as_uri()
    except (OSError, ValueError):
        return ""


def _payload_bounds(vertex_blob: bytes, vertex_count: int) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    usable_count = min(max(0, int(vertex_count)), len(vertex_blob) // ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
    if usable_count <= 0:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for index in range(usable_count):
        try:
            vertex = _VERTEX_STRUCT.unpack_from(vertex_blob, index * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
        except struct.error:
            break
        for axis in range(3):
            value = float(vertex[axis])
            mins[axis] = min(mins[axis], value)
            maxs[axis] = max(maxs[axis], value)
    if not all(math.isfinite(value) for value in (*mins, *maxs)):
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return tuple(mins), tuple(maxs)  # type: ignore[return-value]


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


def _tuple3_or_empty(value: object) -> Tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return ()
    parsed = (_safe_float(value[0]), _safe_float(value[1]), _safe_float(value[2]))
    if not all(math.isfinite(item) for item in parsed):
        return ()
    return parsed


def _batch_base_color(batch: object, vertex_blob: bytes) -> Tuple[float, float, float]:
    color = _tuple3_or_empty(getattr(batch, "preview_base_color", ()))
    return color if color else _first_vertex_color(vertex_blob)


def _batch_bounds(
    batch: object,
    vertex_blob: bytes,
    vertex_count: int,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    bounds_min = _tuple3_or_empty(getattr(batch, "preview_bounds_min", ()))
    bounds_max = _tuple3_or_empty(getattr(batch, "preview_bounds_max", ()))
    if bounds_min and bounds_max:
        return bounds_min, bounds_max
    return _payload_bounds(vertex_blob, vertex_count)


def _batch_tangents_usable(batch: object, vertex_blob: bytes, vertex_count: int) -> bool:
    value = getattr(batch, "tangents_usable", None)
    if value is not None:
        return bool(value)
    return _tangents_usable(vertex_blob, vertex_count)


def _lighting_preset_for_settings(settings: ModelPreviewRenderSettings) -> str:
    d3d11_mode = str(getattr(settings, "d3d11_view_mode", "") or "").strip().lower()
    if d3d11_mode in {"game_outdoor", "cd_outdoor", "outdoor_game"}:
        return "game_outdoor_approx"
    mode = str(getattr(settings, "render_diagnostic_mode", "lit") or "lit").strip().lower()
    if mode in {"texture_probe", "base_direct", "base_no_tint", "normal_raw", "material_raw", "height_raw", "uv_checker"}:
        return "texture_debug"
    if mode in {"metal_shine", "roughness_response", "material_response"}:
        return "shiny_metal_inspection"
    if mode in {"rich_lit", "height_depth", "height_calibrated"}:
        return "cloth_skin_inspection"
    return "neutral_studio"


def _batch_has_metal_preview_response(batch: Mapping[str, object]) -> bool:
    if (
        str(batch.get("material_category", "") or "").strip().lower() == "metal"
        and _safe_float(batch.get("material_category_confidence"), 0.0) >= 0.45
    ):
        return True
    contract = batch.get("material_contract")
    if isinstance(contract, Mapping):
        hints = contract.get("pbr_scalar_hints")
        if isinstance(hints, Mapping):
            if _safe_float(hints.get("metalness"), 0.0) >= 0.18:
                return True
    return False


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
    if (
        any(token in tokens for token in ("specularglossiness", "specgloss", "speculargloss"))
        or "specular_glossiness" in lower
        or ("specular" in lower and "glossiness" in lower)
    ):
        return "specular_glossiness"
    if any(token in tokens for token in ("emi", "emissive", "glow", "illum", "emit")) or "emissive" in lower:
        return "emissive"
    if any(token in tokens for token in ("n", "normal")) or lower.endswith("_n.dds"):
        return "normal"
    if any(token in tokens for token in ("disp", "height", "displacement")):
        return "height"
    if any(token in tokens for token in ("sp", "spec", "specular")):
        return "specular"
    if any(token in tokens for token in ("gloss", "glossiness", "smooth", "smoothness")):
        return "glossiness"
    if any(token in tokens for token in ("rough", "roughness")):
        return "roughness"
    if any(token in tokens for token in ("ao", "occlusion", "ambientocclusion")):
        return "occlusion"
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
        return "" if technical in {"normal", "height", "packed_material", "detail_mask", "opacity", "specular", "specular_glossiness", "emissive"} else "base"
    if slot_kind == "emissive" or semantic_type == "emissive" or semantic_subtype.startswith("emissive") or _contains_token(names, "emissive", "glow", "illum"):
        return "emissive"
    if slot_kind == "normal" or semantic_type == "normal" or _contains_token(names, "normal"):
        return "normal"
    if slot_kind == "height" or semantic_type in {"height", "displacement"} or _contains_token(names, "disp", "height"):
        return "height"
    if slot_kind in {"ao", "occlusion"} or semantic_type in {"ao", "occlusion"} or semantic_subtype in {"ao", "occlusion"} or _contains_token(names, "ao", "occlusion"):
        return "occlusion"
    packed_channels = tuple(
        str(channel or "").strip().lower()
        for channel in getattr(texture_input, "packed_channels", ())
        if str(channel or "").strip()
    )
    if (
        semantic_subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}
        or packed_channels[:2] == ("specular", "glossiness")
        or "specularglossiness" in parameter_name.replace("_", "")
    ):
        return "specular_glossiness"
    if semantic_subtype in {"metallic_roughness", "gltf_metallic_roughness"} or packed_channels[:2] == ("roughness", "metallic"):
        return "packed_material"
    if semantic_subtype in {"glossiness", "gloss", "smoothness", "smooth"} or _contains_token(names, "glossiness", "gloss", "smoothness"):
        return "glossiness"
    if semantic_subtype in {"roughness", "rough"} or _contains_token(names, "roughness"):
        return "roughness"
    if semantic_subtype in {"metal", "metallic", "metalness"} or _contains_token(names, "metallic", "metalness"):
        return "metalness"
    if semantic_subtype in {"specular", "spec"} or _contains_token(names, "specular"):
        return "specular"
    technical = _technical_texture_kind(names)
    if technical in {"specular", "specular_glossiness", "roughness", "glossiness", "metalness", "height", "normal", "opacity", "packed_material", "detail_mask", "emissive", "occlusion"}:
        return technical
    return ""


def _payload_material_slots(batch: PreparedModelPreviewBatch) -> Tuple[str, ...]:
    subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
    channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
        if str(channel or "").strip()
    )
    descriptor = " ".join((subtype, " ".join(channels))).lower()
    if "opacity" in descriptor or channels == ("alpha",):
        return ()
    if "specular_glossiness" in descriptor or channels[:2] == ("specular", "glossiness"):
        return ("roughness", "specular")
    if subtype in {"orm", "rma", "mra"} or channels[:3] == ("ao", "roughness", "metallic"):
        return ("occlusion", "roughness", "metalness")
    if "material_mask" in descriptor or "mask" in descriptor:
        return ("roughness", "specular")
    if "roughness" in descriptor and ("metallic" in descriptor or "metalness" in descriptor):
        return ("roughness", "metalness")
    if "occlusion" in descriptor or "ao" in descriptor:
        return ("occlusion",)
    if "glossiness" in descriptor or "gloss" in descriptor:
        return ("roughness",)
    if "specular" in descriptor:
        return ("specular",)
    return ()


def _payload_material_inputs(batch: PreparedModelPreviewBatch) -> Tuple[PreviewMaterialTextureInput, ...]:
    explicit = tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
    if explicit:
        return tuple(
            texture_input
            for texture_input in explicit
            if not (
                isinstance(texture_input, PreviewMaterialTextureInput)
                and _input_texture_kind(texture_input) == "normal"
                and not _normal_texture_input_binding_allowed(texture_input)
            )
        )
    inputs: list[PreviewMaterialTextureInput] = []
    base_path = str(getattr(batch, "preview_texture_path", "") or "").strip()
    if base_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="base",
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                preview_texture_path=base_path,
                semantic_type="color",
                visualized=True,
            )
        )
    normal_path = str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
    if normal_path and _normal_texture_binding_allowed(
        normal_path,
        getattr(batch, "preview_normal_texture_dds_path", ""),
        getattr(batch, "preview_normal_texture_name", ""),
    ):
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="normal",
                texture_name=str(getattr(batch, "preview_normal_texture_name", "") or ""),
                preview_texture_path=normal_path,
                semantic_type="normal",
                visualized=True,
            )
        )
    material_path = str(getattr(batch, "preview_material_texture_path", "") or "").strip()
    if material_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                texture_name=str(getattr(batch, "preview_material_texture_name", "") or ""),
                preview_texture_path=material_path,
                semantic_type="material",
                semantic_subtype=str(getattr(batch, "preview_material_texture_subtype", "") or ""),
                packed_channels=tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                visualized=True,
            )
        )
    height_path = str(getattr(batch, "preview_height_texture_path", "") or "").strip()
    if height_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="height",
                texture_name=str(getattr(batch, "preview_height_texture_name", "") or ""),
                preview_texture_path=height_path,
                semantic_type="height",
                visualized=True,
            )
        )
    return tuple(inputs)


def _looks_like_normal_texture_path(texture_path: object) -> bool:
    text = str(texture_path or "").replace("\\", "/").strip()
    if not text:
        return False
    if text.lower().startswith("file:"):
        try:
            text = unquote(urlparse(text).path or text)
        except Exception:
            pass
    stem = PurePosixPath(text).stem.lower()
    if not stem:
        return False
    if "normal" in stem or stem.endswith(("_n", "_wn", "_nm", "_nrm", "_nor", "_no")):
        return True
    if re.search(r"(?:^|[_\-.])n(?:$|[_\-.])", stem):
        return True
    return bool("0xff7f7f" in stem or "defaultnormal" in stem or "neutralnormal" in stem)


def _normal_texture_binding_allowed(*values: object) -> bool:
    candidates = tuple(str(value or "").strip() for value in values if str(value or "").strip())
    if not candidates:
        return False
    return any(_looks_like_normal_texture_path(value) for value in candidates)


def _batch_normal_texture_binding_allowed(batch: object) -> bool:
    return _normal_texture_binding_allowed(
        getattr(batch, "preview_normal_texture_path", ""),
        getattr(batch, "preview_normal_texture_dds_path", ""),
        getattr(batch, "preview_normal_texture_name", ""),
    )


def _normal_texture_input_binding_allowed(texture_input: PreviewMaterialTextureInput) -> bool:
    return _normal_texture_binding_allowed(
        getattr(texture_input, "source_dds_path", ""),
        getattr(texture_input, "source_texture_path", ""),
        getattr(texture_input, "preview_texture_path", ""),
        getattr(texture_input, "texture_name", ""),
    )


def build_native_preview_payloads(
    prepared: PreparedModelPreviewData,
    *,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
) -> Tuple[NativePreviewBatchPayload, ...]:
    settings = clamp_model_preview_render_settings(render_settings)
    payloads: list[NativePreviewBatchPayload] = []
    for batch in tuple(getattr(prepared, "batches", ()) or ()):
        vertex_blob = bytes(getattr(batch, "vertex_blob", b"") or b"")
        vertex_count = int(getattr(batch, "index_count", 0) or 0)
        if vertex_count <= 0 or not vertex_blob:
            continue
        bounds_min, bounds_max = _batch_bounds(batch, vertex_blob, vertex_count)
        flip_value = resolve_preview_texture_flip_vertical(
            getattr(batch, "preview_texture_flip_vertical", None),
            source_path=str(getattr(prepared, "source_path", "") or ""),
            source_format=str(getattr(prepared, "format", "") or ""),
            default=False,
            flip_texture_v=bool(getattr(settings, "flip_texture_v", False)),
        )
        material_channels = tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
        normal_texture_allowed = _batch_normal_texture_binding_allowed(batch)
        payloads.append(
            NativePreviewBatchPayload(
                material_name=str(getattr(batch, "material_name", "") or ""),
                texture_name=str(getattr(batch, "texture_name", "") or ""),
                vertex_count=vertex_count,
                bounds_min=bounds_min,
                bounds_max=bounds_max,
                base_color=_batch_base_color(batch, vertex_blob),
                texture_source=_local_file_url(getattr(batch, "preview_texture_path", "")),
                normal_texture_source=_local_file_url(getattr(batch, "preview_normal_texture_path", ""))
                if normal_texture_allowed
                else "",
                material_texture_source=_local_file_url(getattr(batch, "preview_material_texture_path", "")),
                height_texture_source=_local_file_url(getattr(batch, "preview_height_texture_path", "")),
                normal_texture_strength=float(getattr(batch, "preview_normal_texture_strength", 1.0) or 1.0)
                if normal_texture_allowed
                else 0.0,
                material_texture_packed_channels=tuple(str(channel) for channel in material_channels),
                material_texture_slots=_payload_material_slots(batch),
                material_texture_inputs=_payload_material_inputs(batch),
                texture_flip_vertical=bool(flip_value),
                has_texture_coordinates=bool(getattr(batch, "has_texture_coordinates", False)),
                tangents_usable=_batch_tangents_usable(batch, vertex_blob, vertex_count),
            )
        )
    return tuple(payloads)

__all__ = [
    "ISOLATED_PREVIEW_VERTEX_FLOATS",
    "ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES",
    "NativePreviewBatchPayload",
    "_VERTEX_STRUCT",
    "_batch_has_metal_preview_response",
    "_batch_base_color",
    "_batch_bounds",
    "_batch_normal_texture_binding_allowed",
    "_batch_tangents_usable",
    "_clamp01",
    "_contains_token",
    "_first_vertex_color",
    "_input_texture_kind",
    "_lighting_preset_for_settings",
    "_local_file_url",
    "_looks_like_normal_texture_path",
    "_normal_texture_binding_allowed",
    "_normal_texture_input_binding_allowed",
    "_payload_bounds",
    "_payload_material_inputs",
    "_payload_material_slots",
    "_safe_float",
    "_safe_int",
    "_suffix_tokens",
    "_tangents_usable",
    "_technical_texture_kind",
    "_vector_length",
    "build_native_preview_payloads",
]
