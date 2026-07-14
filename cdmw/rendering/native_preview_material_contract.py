from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
)
from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_AUTHORITATIVE,
    AUTHORITY_GUESS,
    AUTHORITY_SIDECAR,
    decode_crimson_texture_binding,
    decode_crimson_texture_entry,
    decode_profile_for_family,
    normalize_shader_family,
    registry_manifest,
)
from cdmw.rendering.material_channels import (
    MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
    resolve_preview_batch_material_channels,
)
from cdmw.rendering.native_preview_payloads import (
    _batch_has_metal_preview_response,
    _clamp01,
    _input_texture_kind,
    _safe_float,
    _safe_int,
)

MATERIAL_CONTRACT_SCHEMA_VERSION = 2

def _render_settings_to_dict(settings: Optional[ModelPreviewRenderSettings]) -> Dict[str, object]:
    value = clamp_model_preview_render_settings(settings)
    return {
        field_info.name: getattr(value, field_info.name)
        for field_info in dataclasses.fields(ModelPreviewRenderSettings)
    }


def _normalized_shader_family(value: object) -> str:
    return normalize_shader_family(value)


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
    family = _normalized_shader_family(shader_family)
    registry_policy = decode_profile_for_family(family)
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
    policy["authority"] = str(registry_policy.get("authority", "") or AUTHORITY_GUESS)
    policy["registry_schema_version"] = registry_policy.get("schema_version", 1)
    policy["global_material_promotions"] = list(tuple(registry_policy.get("global_material_promotions", ()) or ()))
    policy["unknown_policy"] = "unresolved_diagnostic"
    policy["renderdoc_truth_pass"] = registry_policy.get("renderdoc_truth_pass", {})
    return policy


def _texture_slot_state(slot_name: str, textures: Mapping[str, str], dds_textures: Mapping[str, object]) -> Dict[str, object]:
    dds_entry = dds_textures.get(slot_name)
    preview_path = str(textures.get(slot_name, "") or "")
    source_dds_path = str(dds_entry.get("source_path", "") or "") if isinstance(dds_entry, Mapping) else ""
    direct_dds = bool(
        isinstance(dds_entry, Mapping)
        and dds_entry.get("available")
        and source_dds_path
        and dds_entry.get("direct_upload_candidate")
    )
    status = "direct_dds" if direct_dds else ("preview_png" if preview_path else "missing")
    confidence = str(dds_entry.get("confidence", "") or "").strip().lower() if isinstance(dds_entry, Mapping) else ""
    if not confidence:
        confidence = "high" if direct_dds else ("medium" if preview_path else "missing")
    diagnostic = {
        "direct_dds": "using source DDS for native upload",
        "preview_png": "using preview texture fallback",
        "missing": "texture slot unresolved",
    }.get(status, status)
    state = {
        "slot": slot_name,
        "preview_path": preview_path,
        "source_dds_path": source_dds_path,
        "source_width": _safe_int(dds_entry.get("width"), 0) if isinstance(dds_entry, Mapping) else 0,
        "source_height": _safe_int(dds_entry.get("height"), 0) if isinstance(dds_entry, Mapping) else 0,
        "direct_dds": direct_dds,
        "status": status,
        "confidence": confidence,
        "authority": str(dds_entry.get("authority", "") or (AUTHORITY_AUTHORITATIVE if (direct_dds or preview_path) else AUTHORITY_GUESS)) if isinstance(dds_entry, Mapping) else (AUTHORITY_AUTHORITATIVE if preview_path else AUTHORITY_GUESS),
        "source_kind": "direct_dds" if direct_dds else ("preview_texture" if preview_path else "missing"),
        "reason": str(dds_entry.get("reason", "") or "") if isinstance(dds_entry, Mapping) else "",
        "diagnostic": diagnostic,
    }
    if isinstance(dds_entry, Mapping):
        for field in (
            "archive_path",
            "parameter_name",
            "semantic_type",
            "semantic_subtype",
            "shader_family",
            "shader_rule",
            "sidecar_path",
            "sidecar_kind",
            "packed_channels",
            "srgb_mode",
            "parameter_declared_by",
            "material_output_quality",
            "layer_role",
            "layer_channel",
            "blend_flags",
            "authority",
            "disposition",
            "registry_source_kind",
        ):
            value = dds_entry.get(field)
            if value not in (None, ""):
                state[field] = value
    return state


def _material_input_contract_slots(texture_input: PreviewMaterialTextureInput) -> Tuple[str, ...]:
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
    packed_channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(getattr(texture_input, "packed_channels", ()) or ())
        if str(channel or "").strip()
    )
    descriptor = " ".join(
        (
            slot_kind,
            semantic_type,
            semantic_subtype,
            parameter_name,
            " ".join(packed_channels),
            str(getattr(texture_input, "texture_name", "") or ""),
            str(getattr(texture_input, "source_texture_path", "") or ""),
            str(getattr(texture_input, "preview_texture_path", "") or ""),
        )
    ).lower()
    compact_descriptor = descriptor.replace("_", "").replace("-", "").replace(" ", "")
    slots: list[str] = []

    def add(slot_name: str) -> None:
        normalized = str(slot_name or "").strip().lower()
        if normalized == "ao":
            normalized = "occlusion"
        elif normalized in {"metallic", "metal"}:
            normalized = "metalness"
        elif normalized in {"gloss", "smooth", "smoothness"}:
            normalized = "glossiness"
        if normalized in _NORMALIZED_MATERIAL_CONTRACT_SLOTS and normalized not in slots:
            slots.append(normalized)

    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
        slot_name=slot_kind or "material",
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    registry_authority = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
    registry_source_kind = str(registry_decode.get("source_kind", "") or "")
    if registry_authority != AUTHORITY_GUESS or registry_source_kind == "explicit_packed_material":
        promoted = registry_decode.get("promoted_channels", {})
        if isinstance(promoted, Mapping) and promoted:
            for channel_name in promoted:
                add(str(channel_name))
            return tuple(slots)
        registry_slot = str(registry_decode.get("slot", "") or "")
        registry_disposition = str(registry_decode.get("disposition", "") or "")
        if registry_slot in {"base", "normal", "emissive", "height", "opacity"} and registry_disposition in {"promoted", "recorded"}:
            add(registry_slot)
            return tuple(slots)
        if registry_disposition in {"layer_only", "layer_material_response", "layer_flow", "layer_direction", "diagnostic_only", "scalar_hint"}:
            return tuple(slots)

    if "specularglossiness" in compact_descriptor or packed_channels[:2] == ("specular", "glossiness"):
        add("specular_glossiness")
        add("specular")
        add("glossiness")
    if semantic_subtype in {"metallic_roughness", "gltf_metallic_roughness"} or {"roughness", "metallic"} <= set(packed_channels):
        if any(channel in {"ao", "occlusion", "ambientocclusion"} for channel in packed_channels):
            add("occlusion")
        add("roughness")
        add("metalness")
    if slot_kind in _NORMALIZED_MATERIAL_CONTRACT_SLOTS:
        add(slot_kind)
    if slot_kind in {"ao", "metallic"}:
        add(slot_kind)
    if semantic_type in {"base", "base_color", "diffuse", "albedo", "color", "normal", "height", "emissive", "opacity"}:
        add("base" if semantic_type in {"base_color", "diffuse", "albedo", "color"} else semantic_type)
    if semantic_type in {"ao", "occlusion", "metallic", "metalness", "roughness", "specular"}:
        add(semantic_type)
    if semantic_subtype in {"ao", "occlusion", "metallic", "metalness", "roughness", "specular", "glossiness", "opacity", "height", "emissive"}:
        add(semantic_subtype)
    if "clearcoat" in compact_descriptor:
        add("clearcoat")
    if "sheen" in compact_descriptor:
        add("sheen")
    if any(marker in compact_descriptor for marker in ("transmission", "volume", "thickness", "ior", "glass")):
        add("transmission")
    if any(marker in compact_descriptor for marker in ("opacity", "alpha", "transparent")):
        add("opacity")
    if "unlit" in compact_descriptor:
        add("unlit")

    technical = _input_texture_kind(texture_input)
    if technical == "packed_material":
        for channel in packed_channels:
            add(channel)
        if not packed_channels:
            add("roughness")
            add("metalness")
    elif technical == "specular_glossiness":
        add("specular_glossiness")
        add("specular")
        add("glossiness")
    elif technical:
        add(technical)
    return tuple(slots)


def _material_input_slot_state(slot_name: str, texture_input: PreviewMaterialTextureInput) -> Dict[str, object]:
    preview_path = str(getattr(texture_input, "preview_texture_path", "") or "")
    source_path = str(getattr(texture_input, "source_texture_path", "") or "")
    source_dds_path = str(getattr(texture_input, "source_dds_path", "") or "")
    confidence = str(getattr(texture_input, "confidence", "") or "").strip().lower() or "medium"
    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=source_dds_path or source_path or preview_path,
        slot_name=slot_name,
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    note_by_slot = {
        "clearcoat": "source clearcoat recorded; native preview approximates it through specular response",
        "sheen": "source sheen recorded; native preview approximates it through soft specular response",
        "transmission": "source transmission/volume recorded; native preview does not render true glass",
        "opacity": "source opacity recorded; not used as material mask to avoid opaque preview blackout",
        "specular_glossiness": "source specular-glossiness recorded; preview generation decodes RGB specular and alpha glossiness",
        "glossiness": "source glossiness recorded; preview generation inverts it to roughness where supported",
        "unlit": "source unlit material recorded; native preview uses flat non-PBR material hints",
    }
    return {
        "slot": slot_name,
        "preview_path": preview_path,
        "source_dds_path": source_dds_path,
        "source_texture_path": source_path,
        "source_width": 0,
        "source_height": 0,
        "direct_dds": False,
        "status": "input_only" if (preview_path or source_path or source_dds_path) else "recorded",
        "confidence": confidence,
        "authority": str(registry_decode.get("authority", "") or (AUTHORITY_SIDECAR if str(getattr(texture_input, "sidecar_kind", "") or getattr(texture_input, "parameter_declared_by", "") or "").strip() else AUTHORITY_GUESS)),
        "source_kind": "material_input",
        "registry_source_kind": str(registry_decode.get("source_kind", "") or ""),
        "parameter_name": str(getattr(texture_input, "parameter_name", "") or ""),
        "semantic_type": str(getattr(texture_input, "semantic_type", "") or ""),
        "semantic_subtype": str(getattr(texture_input, "semantic_subtype", "") or ""),
        "shader_family": str(getattr(texture_input, "shader_family", "") or ""),
        "packed_channels": list(tuple(getattr(texture_input, "packed_channels", ()) or ())),
        "disposition": str(registry_decode.get("disposition", "") or ""),
        "layer_channel": str(registry_decode.get("layer_channel", "") or getattr(texture_input, "layer_channel", "") or ""),
        "blend_flags": list(tuple(getattr(texture_input, "blend_flags", ()) or ())),
        "promoted_channels": dict(registry_decode.get("promoted_channels", {}) or {}),
        "diagnostic": note_by_slot.get(slot_name, "source material input recorded"),
    }


def _batch_has_unlit_material_hint(batch: PreparedModelPreviewBatch) -> bool:
    overrides = getattr(batch, "preview_native_material_overrides", {}) or {}
    if isinstance(overrides, Mapping) and str(overrides.get("material_shader_family", "") or "").strip().lower() == "gltf_unlit":
        return True
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = str(getattr(parameter, "parameter_name", "") or "").strip().lower()
            if parameter_name == "_gltfunlit" or "gltfunlit" in parameter_name.replace("_", ""):
                return True
    return False


def _normalized_material_texture_slot_states(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    states: Dict[str, Dict[str, object]] = {
        slot_name: {
            "slot": slot_name,
            "preview_path": "",
            "source_dds_path": "",
            "source_width": 0,
            "source_height": 0,
            "direct_dds": False,
            "status": "missing",
            "confidence": "missing",
            "source_kind": "missing",
            "diagnostic": "texture slot unresolved",
        }
        for slot_name in _NORMALIZED_MATERIAL_CONTRACT_SLOTS
    }

    def assign(slot_name: str, state: Mapping[str, object], *, replace: bool = False) -> None:
        current = states.get(slot_name)
        if current is None:
            return
        if not replace and str(current.get("status", "") or "") != "missing":
            return
        updated = dict(state)
        updated["slot"] = slot_name
        states[slot_name] = updated

    for slot_name in ("base", "normal", "occlusion", "roughness", "metalness", "specular", "height", "emissive"):
        state = _texture_slot_state(slot_name, textures, dds_textures)
        if str(state.get("status", "") or "") != "missing":
            assign(slot_name, state, replace=True)

    packed_state = _texture_slot_state("material", textures, dds_textures)
    if str(packed_state.get("status", "") or "") != "missing":
        raw_packed = packed_state.get("packed_channels", ())
        state_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in (
                raw_packed
                if isinstance(raw_packed, Sequence) and not isinstance(raw_packed, (str, bytes, bytearray))
                else ()
            )
            if str(channel or "").strip()
        )
        batch_packed_channels = tuple(
            str(channel or "").strip().lower()
            for channel in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
            if str(channel or "").strip()
        )
        registry_decode = decode_crimson_texture_binding(
            shader_family=str(packed_state.get("shader_family", "") or _material_contract_shader_family(batch)),
            parameter_name=str(packed_state.get("parameter_name", "") or ""),
            source_path=str(packed_state.get("source_dds_path", "") or packed_state.get("preview_path", "") or ""),
            slot_name="material",
            semantic_subtype=str(packed_state.get("semantic_subtype", "") or ""),
            packed_channels=state_packed_channels or batch_packed_channels,
            layer_channel=str(packed_state.get("layer_channel", "") or ""),
            blend_flags=tuple(packed_state.get("blend_flags", ()) or ()) if isinstance(packed_state.get("blend_flags", ()), Sequence) and not isinstance(packed_state.get("blend_flags", ()), (str, bytes, bytearray)) else (),
            sidecar_kind=str(packed_state.get("sidecar_kind", "") or ""),
            parameter_declared_by=str(packed_state.get("parameter_declared_by", "") or ""),
        )
        promoted = registry_decode.get("promoted_channels", {})
        promoted_mapping = promoted if isinstance(promoted, Mapping) else {}
        for channel_name, slot_name in (("ao", "occlusion"), ("roughness", "roughness"), ("metalness", "metalness"), ("metallic", "metalness")):
            if str(states[slot_name].get("status", "") or "") != "missing":
                continue
            source_channel = str(promoted_mapping.get(channel_name, "") or "")
            if not source_channel:
                continue
            state = dict(packed_state)
            state["source_kind"] = str(registry_decode.get("source_kind", "") or "packed_material")
            state["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
            state["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
            state["disposition"] = str(registry_decode.get("disposition", "") or "promoted")
            state["source_channel"] = source_channel
            state["diagnostic"] = str(registry_decode.get("reason", "") or f"packed material texture supplies {slot_name}")
            assign(slot_name, state, replace=True)

    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for slot_name in _material_input_contract_slots(texture_input):
            assign(slot_name, _material_input_slot_state(slot_name, texture_input))

    if _batch_has_unlit_material_hint(batch):
        states["unlit"] = {
            "slot": "unlit",
            "preview_path": "",
            "source_dds_path": "",
            "source_width": 0,
            "source_height": 0,
            "direct_dds": False,
            "status": "recorded",
            "confidence": "high",
            "source_kind": "material_parameter",
            "diagnostic": "source unlit material recorded; native preview uses flat non-PBR material hints",
        }
    return states


def _material_sidecar_paths(batch: PreparedModelPreviewBatch) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        for value in (getattr(texture_input, "sidecar_path", ""), getattr(texture_input, "linked_mesh_path", "")):
            path = str(value or "").strip()
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _material_lighting_preset(shader_family: str, hints: Mapping[str, object], diagnostic_mode: str = "") -> str:
    mode = str(diagnostic_mode or "").strip().lower()
    if mode in {"texture_probe", "base_direct", "base_no_tint", "material_raw", "normal_raw", "height_raw"}:
        return "texture_debug"
    family = str(shader_family or "").strip().lower()
    if family in {"cloth", "cloth_v2", "skin", "hair"}:
        return "cloth_skin_inspection"
    if _safe_float(hints.get("metalness"), 0.0) >= 0.25 or _safe_float(hints.get("specular"), 0.0) >= 0.30:
        return "shiny_metal_inspection"
    return "neutral_studio"


def _material_decode_profile(
    shader_family: str,
    hints: Mapping[str, object],
    combiner_metadata: Mapping[str, object],
    packed_channels: Sequence[str],
) -> Dict[str, object]:
    return {
        "profile": shader_family or "generic",
        "shader_family": shader_family or "generic",
        "packed_channels": list(tuple(packed_channels or ())),
        "decode_modes": list(tuple(combiner_metadata.get("decode_modes", ()) or ())),
        "combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
        "pbr_scalar_hints": {
            "roughness": _safe_float(hints.get("roughness"), 0.55),
            "metalness": _safe_float(hints.get("metalness"), 0.0),
            "specular": _safe_float(hints.get("specular"), 0.08),
            "height_scale": _safe_float(hints.get("height_scale"), 0.0),
            "emissive_intensity": _safe_float(hints.get("emissive_intensity"), 0.0),
        },
        "lighting_preset_hint": _material_lighting_preset(shader_family, hints),
    }


_MATERIAL_CONTRACT_SLOTS = ("base", "normal", "material", "occlusion", "roughness", "metalness", "specular", "height", "emissive")
_NORMALIZED_MATERIAL_CONTRACT_SLOTS = (
    "base",
    "normal",
    "occlusion",
    "roughness",
    "metalness",
    "specular",
    "glossiness",
    "specular_glossiness",
    "emissive",
    "opacity",
    "height",
    "clearcoat",
    "sheen",
    "transmission",
    "unlit",
)


def _material_slot_diagnostics(
    slot_states: Mapping[str, Mapping[str, object]],
    slot_order: Sequence[str] = _MATERIAL_CONTRACT_SLOTS,
) -> list[Dict[str, object]]:
    diagnostics: list[Dict[str, object]] = []
    for slot_name in tuple(slot_order or ()):
        slot = slot_states.get(slot_name, {})
        diagnostics.append(
            {
                "slot": slot_name,
                "status": str(slot.get("status", "missing") or "missing"),
                "confidence": str(slot.get("confidence", "missing") or "missing"),
                "authority": str(slot.get("authority", "") or AUTHORITY_GUESS),
                "source_kind": str(slot.get("source_kind", "missing") or "missing"),
                "registry_source_kind": str(slot.get("registry_source_kind", "") or ""),
                "source_dds_path": str(slot.get("source_dds_path", "") or ""),
                "preview_path": str(slot.get("preview_path", "") or ""),
                "source_channel": str(slot.get("source_channel", "") or ""),
                "parameter_name": str(slot.get("parameter_name", "") or ""),
                "shader_family": str(slot.get("shader_family", "") or ""),
                "disposition": str(slot.get("disposition", "") or ""),
                "note": str(slot.get("diagnostic", "") or ""),
            }
        )
    return diagnostics


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
        for slot_name in _MATERIAL_CONTRACT_SLOTS
    }
    normalized_slot_states = _normalized_material_texture_slot_states(
        batch,
        textures=textures,
        dds_textures=dds_textures,
    )
    registry_decodes: list[Dict[str, object]] = []
    for slot_name, slot_state in slot_states.items():
        if str(slot_state.get("status", "") or "") == "missing":
            continue
        registry_decodes.append(
            dict(
                decode_crimson_texture_binding(
                    shader_family=str(slot_state.get("shader_family", "") or shader_family),
                    parameter_name=str(slot_state.get("parameter_name", "") or ""),
                    source_path=str(slot_state.get("source_dds_path", "") or slot_state.get("preview_path", "") or ""),
                    slot_name=slot_name,
                    semantic_subtype=str(slot_state.get("semantic_subtype", "") or ""),
                    packed_channels=tuple(slot_state.get("packed_channels", ()) or ()) if isinstance(slot_state.get("packed_channels", ()), Sequence) and not isinstance(slot_state.get("packed_channels", ()), (str, bytes, bytearray)) else (),
                    layer_channel=str(slot_state.get("layer_channel", "") or ""),
                    blend_flags=tuple(slot_state.get("blend_flags", ()) or ()) if isinstance(slot_state.get("blend_flags", ()), Sequence) and not isinstance(slot_state.get("blend_flags", ()), (str, bytes, bytearray)) else (),
                    sidecar_kind=str(slot_state.get("sidecar_kind", "") or ""),
                    parameter_declared_by=str(slot_state.get("parameter_declared_by", "") or ""),
                )
            )
        )
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        registry_decodes.append(
            dict(
                decode_crimson_texture_binding(
                    shader_family=str(getattr(texture_input, "shader_family", "") or shader_family),
                    parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
                    source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
                    slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
                    semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
                    packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
                    layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
                    blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
                    sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
                    parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
                )
            )
        )
    packed_channels = list(tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()))
    normalized_channels = [str(channel or "").strip().lower() for channel in packed_channels]
    divergence_reasons: list[str] = []
    if normalized_channels and normalized_channels[:3] != ["ao", "roughness", "metallic"]:
        divergence_reasons.append("channel layout differs from default ARM")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("normal",)):
        divergence_reasons.append("missing source normal uses neutral fallback in CD runtime approximation")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("occlusion",)):
        divergence_reasons.append("missing source AO uses profile default in CD runtime approximation")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("roughness", "material")):
        divergence_reasons.append("missing source roughness uses factor/profile fallback")
    if not any(slot_states.get(slot, {}).get("status") != "missing" for slot in ("metalness", "material")):
        divergence_reasons.append("missing source metallic uses factor/profile fallback")
    if str(normalized_slot_states.get("opacity", {}).get("status", "") or "") != "missing":
        divergence_reasons.append("opacity texture recorded but not used as material response map")
    if str(normalized_slot_states.get("transmission", {}).get("status", "") or "") != "missing":
        divergence_reasons.append("transmission/volume recorded but native preview does not render true glass")
    slot_diagnostics = _material_slot_diagnostics(slot_states)
    normalized_slot_diagnostics = _material_slot_diagnostics(
        normalized_slot_states,
        _NORMALIZED_MATERIAL_CONTRACT_SLOTS,
    )
    present_slots = sum(1 for slot in slot_states.values() if str(slot.get("status", "")) != "missing")
    return {
        "schema_version": MATERIAL_CONTRACT_SCHEMA_VERSION,
        "shader_family": shader_family or "generic",
        "shader_registry": registry_manifest(),
        "registry_decodes": registry_decodes,
        "registry_policy": decode_profile_for_family(shader_family),
        "decode_policy": _material_decode_policy(shader_family),
        "decode_profile": _material_decode_profile(shader_family, hints, combiner_metadata, packed_channels),
        "pbr_scalar_hints": {
            "roughness": _safe_float(hints.get("roughness"), 0.55),
            "metalness": _safe_float(hints.get("metalness"), 0.0),
            "specular": _safe_float(hints.get("specular"), 0.08),
            "height_scale": _safe_float(hints.get("height_scale"), 0.0),
            "emissive_intensity": _safe_float(hints.get("emissive_intensity"), 0.0),
        },
        "material_hints": hints,
        "texture_slots": slot_states,
        "resolved_texture_slots": slot_states,
        "normalized_texture_slots": normalized_slot_states,
        "slot_diagnostics": slot_diagnostics,
        "normalized_slot_diagnostics": normalized_slot_diagnostics,
        "source_sidecar_paths": _material_sidecar_paths(batch),
        "packed_channels": packed_channels,
        "preview_modes": {
            "source_pbr_preview": {
                "authority": "gltf_source_textures_and_factors",
                "base": "baseColorTexture * baseColorFactor",
                "material": "metallicRoughnessTexture G/B plus occlusion/emissive inputs",
            },
            "cd_runtime_approx": {
                "authority": "generated_cd_profile_outputs",
                "profile": "arm_standard",
                "material": "_ma RGB=AO/roughness/metallic with neutral support fallbacks",
            },
        },
        "preview_divergence_reasons": divergence_reasons,
        "material_input_count": sum(
            1
            for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
            if isinstance(texture_input, PreviewMaterialTextureInput)
        ),
        "combiner_active": bool(combiner_metadata.get("active", False)),
        "combiner_outputs": list(tuple(combiner_metadata.get("outputs", ()) or ())),
        "status": "ok" if present_slots else "missing_textures",
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
        for slot_name in _MATERIAL_CONTRACT_SLOTS
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


def _material_hex_color_rgb(value: object) -> Tuple[float, float, float]:
    text = str(value or "").strip()
    if not text:
        return ()
    if text.startswith("#"):
        text = text[1:]
    if len(text) not in {6, 8} or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return ()
    try:
        if len(text) == 8:
            # Crimson PAC XML MaterialParameterColor sidecars use RRGGBBAA.
            return (
                int(text[0:2], 16) / 255.0,
                int(text[2:4], 16) / 255.0,
                int(text[4:6], 16) / 255.0,
            )
        return (
            int(text[0:2], 16) / 255.0,
            int(text[2:4], 16) / 255.0,
            int(text[4:6], 16) / 255.0,
        )
    except ValueError:
        return ()


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
    emissive_values: list[float] = []
    emissive_colors: list[str] = []
    for texture_input in inputs:
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            key = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if not key:
                continue
            raw_value = str(getattr(parameter, "value", "") or "").strip()
            if "emissivecolor" in key and raw_value:
                emissive_colors.append(raw_value)
            numeric_value = getattr(parameter, "numeric_value", None)
            if numeric_value is not None:
                numeric = _clamp01(numeric_value)
                if "emissiveintensity" in key:
                    try:
                        emissive_values.append(max(0.0, min(32.0, float(numeric_value))))
                    except (TypeError, ValueError, OverflowError):
                        pass
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
    hints: Dict[str, object] = {
        "shader_families": list(shader_families[:4]),
        "roughness": round(float(max(0.0, min(1.0, roughness_hint))), 4),
        "metalness": round(float(max(0.0, min(1.0, metalness_hint * 0.42))), 4),
        "specular": round(float(max(0.0, min(1.0, specular_hint * 0.72))), 4),
        "height_scale": round(float(max(0.0, min(1.0, max(height_values) if height_values else 0.0))), 4),
        "emissive_intensity": round(float(max(0.0, min(32.0, max(emissive_values) if emissive_values else 0.0))), 4),
        "emissive_intensity_declared": bool(emissive_values),
        "emissive_color": emissive_colors[0] if emissive_colors else "",
        "emissive_active": bool(emissive_values and max(emissive_values) > 0.0),
        "source": "sidecar_parameters" if any((roughness_values, metalness_values, specular_values, height_values, emissive_values)) else "",
    }
    overrides = getattr(batch, "preview_native_material_overrides", None)
    if isinstance(overrides, Mapping):
        override_hints = overrides.get("native_material_hints")
        if isinstance(override_hints, Mapping):
            for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity"):
                if key in override_hints:
                    hints[key] = round(float(max(0.0, min(32.0 if key == "emissive_intensity" else 1.0, _safe_float(override_hints.get(key), _safe_float(hints.get(key), 0.0))))), 4)
                    if key == "emissive_intensity":
                        hints["emissive_intensity_declared"] = True
            if str(override_hints.get("emissive_color", "") or "").strip():
                hints["emissive_color"] = str(override_hints.get("emissive_color", "") or "").strip()
        for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity"):
            if key in overrides:
                hints[key] = round(float(max(0.0, min(32.0 if key == "emissive_intensity" else 1.0, _safe_float(overrides.get(key), _safe_float(hints.get(key), 0.0))))), 4)
                if key == "emissive_intensity":
                    hints["emissive_intensity_declared"] = True
        if str(overrides.get("emissive_color", "") or "").strip():
            hints["emissive_color"] = str(overrides.get("emissive_color", "") or "").strip()
        if any(key in overrides for key in ("roughness", "metalness", "specular", "height_scale", "emissive_intensity", "emissive_color")) or isinstance(override_hints, Mapping):
            hints["source"] = "native_material_overrides"
            hints["emissive_active"] = bool(_safe_float(hints.get("emissive_intensity"), 0.0) > 0.0)
    return hints


def _slot_has_resolved_texture(
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    slot_name: str,
) -> bool:
    slot = str(slot_name or "").strip().lower()
    if str(textures.get(slot, "") or "").strip():
        return True
    entry = dds_textures.get(slot)
    return bool(
        isinstance(entry, Mapping)
        and entry.get("available")
        and str(entry.get("source_path", "") or "").strip()
    )


def _batch_has_explicit_metalness_slot(batch: PreparedModelPreviewBatch) -> bool:
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip().lower()
        semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        if slot_kind in {"metal", "metallic", "metalness"}:
            return True
        if semantic_type in {"metal", "metallic", "metalness"} or semantic_subtype in {
            "metal",
            "metallic",
            "metalness",
            "metallic_roughness",
            "gltf_metallic_roughness",
        }:
            return True
        if ("metallic" in parameter_key or "metalness" in parameter_key) and "colorblendingmask" not in parameter_key:
            return True
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if ("metallic" in parameter_name or "metalness" in parameter_name) and "colorblendingmask" not in parameter_name:
                return True
    return False


def _material_input_descriptor(batch: PreparedModelPreviewBatch) -> str:
    parts: list[str] = [
        str(getattr(batch, "material_name", "") or ""),
        str(getattr(batch, "texture_name", "") or ""),
        str(getattr(batch, "preview_sidecar_shader_family", "") or ""),
        str(getattr(batch, "preview_sidecar_material_primitive", "") or ""),
        str(getattr(batch, "preview_material_texture_name", "") or ""),
        str(getattr(batch, "preview_material_texture_type", "") or ""),
        str(getattr(batch, "preview_material_texture_subtype", "") or ""),
        " ".join(str(value or "") for value in tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())),
    ]
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        parts.extend(
            [
                texture_input.slot_kind,
                texture_input.parameter_name,
                texture_input.source_texture_path,
                texture_input.source_dds_path,
                texture_input.texture_name,
                texture_input.semantic_type,
                texture_input.semantic_subtype,
                " ".join(texture_input.packed_channels),
                texture_input.material_name,
                texture_input.part_name,
                texture_input.shader_family,
                texture_input.layer_role,
                texture_input.layer_channel,
                " ".join(texture_input.blend_flags),
            ]
        )
    return " ".join(part.replace("\\", "/") for part in parts if str(part or "").strip()).lower()


def _descriptor_contains_token(descriptor: str, token: str) -> bool:
    token = str(token or "").strip().lower()
    if not token:
        return False
    start = 0
    while True:
        index = descriptor.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        left_boundary = index == 0 or not descriptor[index - 1].isalnum()
        right_boundary = end >= len(descriptor) or not descriptor[end].isalnum()
        if left_boundary and right_boundary:
            return True
        start = end


def _preview_tint_color_visible(color: Sequence[object]) -> bool:
    values = [_safe_float(value, 1.0) for value in tuple(color or ())[:3]]
    if len(values) < 3:
        return False
    return max(values) - min(values) > 0.055 or abs(max(values) - 1.0) > 0.08


def _preview_tint_color_score(color: Sequence[object]) -> float:
    values = [_safe_float(value, 1.0) for value in tuple(color or ())[:3]]
    if len(values) < 3 or not _preview_tint_color_visible(values):
        return -1.0
    luma = values[0] * 0.299 + values[1] * 0.587 + values[2] * 0.114
    return (max(values) - min(values)) * 1.60 + luma * 0.25 + 0.35


def _descriptor_prefers_sidecar_tint(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return _source_or_descriptor_has_weapon_surface(source_path, descriptor) or any(
        _descriptor_contains_token(text, token)
        for token in ("flag", "banner", "ribbon", "sash", "tassel", "fringe", "flap")
    )


def _descriptor_has_local_strong_nonmetal_token(descriptor: str) -> bool:
    text = str(descriptor or "").replace("\\", "/").lower()
    return any(
        _descriptor_contains_token(text, token)
        for token in (
            "cloth",
            "fabric",
            "flag",
            "banner",
            "tassel",
            "fringe",
            "ribbon",
            "sash",
            "rope",
            "leather",
            "hide",
            "strap",
            "belt",
            "grip",
            "wrap",
            "handle",
            "wood",
            "stick",
            "shaft",
            "haft",
            "skin",
            "hair",
            "fur",
        )
    )


def _descriptor_has_apparel_cloth_slot(descriptor: str) -> bool:
    text = str(descriptor or "").replace("\\", "/").lower()
    return (
        "/9_upperbody/" in text
        or "/10_lowerbody/" in text
        or "_ub_" in text
        or "_lb_" in text
        or any(
            _descriptor_contains_token(text, token)
            for token in ("upperbody", "lowerbody", "sleeve", "pants", "trouser", "shirt", "tunic")
        )
    )


def _descriptor_has_structural_metal_slot(descriptor: str) -> bool:
    text = str(descriptor or "").replace("\\", "/").lower()
    return any(
        _descriptor_contains_token(text, token)
        for token in ("metal", "steel", "iron", "blade", "plate", "chain", "mail")
    )


def _batch_weapon_masked_base_tint_should_stay_masked(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> bool:
    descriptor = _material_input_descriptor(batch)
    if not _source_or_descriptor_has_weapon_surface(source_path, descriptor):
        return False
    local_descriptor = " ".join(
        str(value or "")
        for value in (
            getattr(batch, "material_name", ""),
            getattr(batch, "texture_name", ""),
            getattr(batch, "preview_role", ""),
        )
    )
    if _descriptor_has_local_strong_nonmetal_token(local_descriptor):
        return False
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        if slot_kind and slot_kind != "base":
            continue
        channel = str(getattr(texture_input, "layer_channel", "") or "").strip().lower()
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        if channel in {"g", "b", "a"}:
            return True
        if any(token in parameter_key for token in ("diffusetextureg", "diffusetextureb", "diffusetexturea", "diffusemaskg", "diffusemaskb", "diffusemaska")):
            return True
    return False


def sidecar_preview_texture_tint_for_batch(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> Tuple[float, float, float]:
    descriptor = _material_input_descriptor(batch)
    if not _descriptor_prefers_sidecar_tint(source_path, descriptor):
        return ()
    if _batch_weapon_masked_base_tint_should_stay_masked(batch, source_path=source_path):
        return ()
    best_color: Tuple[float, float, float] = ()
    best_score = -1.0
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        input_descriptor = " ".join(
            str(value or "")
            for value in (
                getattr(texture_input, "slot_kind", ""),
                getattr(texture_input, "parameter_name", ""),
                getattr(texture_input, "material_name", ""),
                getattr(texture_input, "texture_name", ""),
                getattr(texture_input, "layer_role", ""),
                getattr(texture_input, "layer_channel", ""),
            )
        ).lower()
        for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
            parameter_name = _normalized_material_key(getattr(parameter, "parameter_name", ""))
            if not any(token in parameter_name for token in ("tintcolor", "dyeingdetaillayercolormask", "layercolor", "basecolor")):
                continue
            color = tuple(_safe_float(value, 1.0) for value in tuple(getattr(parameter, "color_value", ()) or ())[:3])
            if len(color) < 3:
                continue
            score = _preview_tint_color_score(color)
            if "dyeingdetail" in parameter_name or "detail" in input_descriptor:
                score += 0.18
            if "grime" in input_descriptor:
                score += 0.06
            if score > best_score:
                best_score = score
                best_color = tuple(max(0.02, min(1.35, float(value))) for value in color)
    return best_color if best_score > 0.0 else ()


def _preview_texture_family_key(value: object) -> str:
    name = Path(str(value or "").replace("\\", "/")).name.lower()
    stem = name.rsplit(".", 1)[0]
    for suffix in ("_disp", "_ma", "_mg", "_sp", "_m", "_n", "_o", "_dr"):
        if len(stem) > len(suffix) and stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _preview_texture_family_key_is_specific_material_response(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if "texturelayer" in normalized:
        return False
    if "common" in normalized or "default" in normalized:
        return False
    if normalized.startswith("cd_temp") or "temp" in normalized:
        return False
    return True


def _preview_material_family_keys(source_path: object, batch: PreparedModelPreviewBatch) -> Tuple[str, ...]:
    keys = [
        _preview_texture_family_key(source_path),
        _preview_texture_family_key(getattr(batch, "material_name", "")),
        _preview_texture_family_key(getattr(batch, "texture_name", "")),
        _preview_texture_family_key(getattr(batch, "editor_part_name", "")),
    ]
    return tuple(dict.fromkeys(key for key in keys if key))


def _preview_material_keys_match(candidate_key: str, family_key: str) -> bool:
    candidate = str(candidate_key or "").strip().lower()
    family = str(family_key or "").strip().lower()
    if not candidate or not family:
        return False
    return candidate == family or candidate in family or family in candidate


def _batch_has_authoritative_family_material_response(batch: PreparedModelPreviewBatch, *, source_path: object = "") -> bool:
    family_keys = _preview_material_family_keys(source_path, batch)
    if not family_keys:
        return False
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        authority_text = " ".join(
            (
                str(getattr(texture_input, "sidecar_kind", "") or ""),
                str(getattr(texture_input, "parameter_declared_by", "") or ""),
                str(getattr(texture_input, "material_output_quality", "") or ""),
                str(getattr(texture_input, "confidence", "") or ""),
            )
        ).lower()
        if "exact" not in authority_text and "sidecar" not in authority_text and "technique" not in authority_text:
            continue
        input_kind = _input_texture_kind(texture_input)
        parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
        packed = " ".join(str(channel or "").lower() for channel in tuple(getattr(texture_input, "packed_channels", ()) or ()))
        source = (
            str(getattr(texture_input, "source_dds_path", "") or "")
            or str(getattr(texture_input, "source_texture_path", "") or "")
            or str(getattr(texture_input, "preview_texture_path", "") or "")
            or str(getattr(texture_input, "texture_name", "") or "")
        )
        source_text = source.lower()
        material_response = (
            input_kind in {"packed_material", "material", "specular", "roughness", "metalness", "glossiness", "specular_glossiness"}
            or _batch_has_explicit_metalness_slot(batch)
            or (parameter_key == "colorblendingmasktexture" and "_ma" in source_text)
            or ("occlusion" in packed and "roughness" in packed and ("metalness" in packed or "metallic" in packed))
        )
        if not material_response:
            continue
        texture_family_key = _preview_texture_family_key(source)
        if not _preview_texture_family_key_is_specific_material_response(texture_family_key):
            continue
        if any(_preview_material_keys_match(texture_family_key, family_key) for family_key in family_keys):
            return True
    return False


def _source_or_descriptor_has_armor_equipment(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return (
        "/armor/" in text
        or "/13_hel/" in text
        or "_hel_" in text
        or any(_descriptor_contains_token(text, token) for token in ("helmet", "helm", "armor", "armour", "plate"))
    )


def _source_or_descriptor_has_weapon_surface(source_path: object, descriptor: str) -> bool:
    text = " ".join((str(source_path or ""), str(descriptor or ""))).replace("\\", "/").lower()
    return (
        "/weapon/" in text
        or "/2_twohandweapon/" in text
        or any(_descriptor_contains_token(text, token) for token in ("weapon", "sword", "blade", "guard", "hilt", "pommel"))
    )


def _resolved_batch_material_category(
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    material_hints: Mapping[str, object],
    material_contract: Mapping[str, object],
    source_path: object = "",
) -> Tuple[str, float]:
    family = str(material_contract.get("shader_family", "") or "").strip().lower()
    if family == "skin":
        return "skin", 0.90
    if family == "hair":
        return "hair", 0.90
    if family in {"cloth", "cloth_v2"}:
        return "cloth", 0.84

    descriptor = _material_input_descriptor(batch)
    local_descriptor = " ".join(
        part.replace("\\", "/")
        for part in (
            str(getattr(batch, "material_name", "") or ""),
            str(getattr(batch, "preview_role", "") or ""),
        )
        if part.strip()
    ).lower()
    nonmetal_tokens = {
        "skin",
        "hair",
        "cloth",
        "fabric",
        "flag",
        "banner",
        "vest",
        "tassel",
        "fringe",
        "ribbon",
        "sash",
        "rope",
        "cloak",
        "cape",
        "skirt",
        "dress",
        "mantle",
        "robe",
        "flap",
        "leather",
        "strap",
        "belt",
        "grip",
        "wrap",
        "handle",
        "wood",
        "stick",
        "shaft",
        "haft",
        "glass",
        "gem",
        "jewel",
        "crystal",
        "diamond",
        "ruby",
        "sapphire",
        "emerald",
        "stone",
        "rock",
        "ceramic",
        "eye",
        "iris",
        "pupil",
        "cornea",
        "tooth",
        "teeth",
        "fur",
        "brow",
        "eyebrow",
        "lash",
        "eyelash",
        "face",
        "nonmetal",
        "non_metal",
        "non-metal",
        "non metal",
    }
    local_nonmetal_tokens = nonmetal_tokens | {"hide", "timber"}
    local_strong_nonmetal_descriptor = any(
        _descriptor_contains_token(local_descriptor, token)
        for token in local_nonmetal_tokens
    )
    local_metal_tokens = {
        "metal",
        "steel",
        "iron",
        "blade",
        "guard",
        "hilt",
        "pommel",
        "plate",
        "silver",
        "gold",
        "copper",
        "bronze",
        "brass",
        "chrome",
    }
    if (
        any(_descriptor_contains_token(local_descriptor, token) for token in local_metal_tokens)
        and not local_strong_nonmetal_descriptor
    ):
        return "metal", 0.90 if _batch_has_explicit_metalness_slot(batch) else 0.78
    if any(_descriptor_contains_token(descriptor, token) for token in ("leather", "hide", "strap", "belt", "grip", "wrap", "handle")):
        return "leather", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("wood", "timber", "stick", "shaft", "haft")):
        return "wood", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("glass", "crystal")):
        return "glass", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("gem", "jewel", "diamond", "ruby", "sapphire", "emerald")):
        return "gem", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("stone", "rock", "ceramic")):
        return "stone", 0.72
    if any(_descriptor_contains_token(descriptor, token) for token in ("eye", "iris", "pupil", "cornea")):
        return "eye", 0.76
    if any(_descriptor_contains_token(descriptor, token) for token in ("tooth", "teeth")):
        return "tooth", 0.76
    if any(_descriptor_contains_token(descriptor, token) for token in ("hair", "fur", "beard", "brow", "eyebrow", "lash", "eyelash")):
        return "hair", 0.76

    packed_text = " ".join(str(value or "") for value in tuple(material_contract.get("packed_channels", ()) or ())).lower()
    apparel_cloth_descriptor = (
        _descriptor_has_apparel_cloth_slot(" ".join((str(source_path or ""), descriptor, local_descriptor)))
        and not _descriptor_has_structural_metal_slot(local_descriptor)
    )
    strong_nonmetal_descriptor = any(_descriptor_contains_token(descriptor, token) for token in nonmetal_tokens) or apparel_cloth_descriptor
    if any(
        _descriptor_contains_token(descriptor, token)
        for token in ("cloth", "fabric", "flag", "banner", "vest", "tassel", "fringe", "ribbon", "sash", "rope", "cloak", "cape", "skirt", "dress", "mantle", "robe", "flap")
    ) or apparel_cloth_descriptor:
        return "cloth", 0.72
    explicit_metal = bool(
        not strong_nonmetal_descriptor
        and (
            _safe_float(material_hints.get("metalness"), 0.0) >= 0.16
            and str(material_hints.get("source", "") or "") == "native_material_overrides"
        )
    )
    strong_metal_tokens = {
        "metal",
        "steel",
        "iron",
        "blade",
        "plate",
    }
    color_metal_tokens = {
        "silver",
        "gold",
        "copper",
        "bronze",
        "brass",
        "chrome",
    }
    strong_token_metal = any(_descriptor_contains_token(descriptor, token) for token in strong_metal_tokens) and not any(
        _descriptor_contains_token(descriptor, token) for token in nonmetal_tokens
    )
    color_token_metal = any(_descriptor_contains_token(descriptor, token) for token in color_metal_tokens) and not any(
        _descriptor_contains_token(descriptor, token) for token in nonmetal_tokens
    )
    if explicit_metal:
        return "metal", 0.92
    if (
        _source_or_descriptor_has_armor_equipment(source_path, descriptor)
        and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        and not local_strong_nonmetal_descriptor
        and not strong_nonmetal_descriptor
    ):
        return "metal", 0.90
    if (
        _source_or_descriptor_has_weapon_surface(source_path, descriptor)
        and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        and not local_strong_nonmetal_descriptor
        and (
            any(_descriptor_contains_token(local_descriptor, token) for token in local_metal_tokens)
            or _batch_has_explicit_metalness_slot(batch)
            or _safe_float(material_hints.get("metalness"), 0.0) >= 0.35
        )
    ):
        return "metal", 0.90
    if strong_token_metal:
        return "metal", 0.90 if _batch_has_explicit_metalness_slot(batch) else 0.78
    if color_token_metal:
        return "metal", 0.62
    return "generic", 0.35


def _resolved_batch_material_category_reason(
    category: str,
    batch: PreparedModelPreviewBatch,
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
    material_hints: Mapping[str, object],
    material_contract: Mapping[str, object],
    source_path: object = "",
) -> str:
    descriptor = _material_input_descriptor(batch)
    if category == "metal":
        if (
            _source_or_descriptor_has_armor_equipment(source_path, descriptor)
            and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        ):
            return "metal:armor_family_material_response"
        if (
            _source_or_descriptor_has_weapon_surface(source_path, descriptor)
            and _batch_has_authoritative_family_material_response(batch, source_path=source_path)
        ):
            return "metal:weapon_family_material_response"
        for token in ("gold", "silver", "copper", "bronze", "brass", "chrome"):
            if _descriptor_contains_token(descriptor, token):
                return "metal:color_token"
        if (
            _safe_float(material_hints.get("metalness"), 0.0) >= 0.16
            or _slot_has_resolved_texture(textures, dds_textures, "metalness")
            or _batch_has_explicit_metalness_slot(batch)
        ):
            return "metal:material_channel"
        return "metal:material_or_part_token"
    if category == "cloth" and _descriptor_has_apparel_cloth_slot(" ".join((str(source_path or ""), descriptor))):
        return "nonmetal:apparel_slot_token"
    if category in {"leather", "wood", "cloth", "skin", "hair", "stone", "tooth"}:
        return f"nonmetal:{category}_token"
    if category in {"glass", "gem", "eye"}:
        return f"glossy_nonmetal:{category}_token"
    return "generic:no_strong_material_token"


def _resolved_batch_material_finish(category: str, material_hints: Mapping[str, object]) -> str:
    normalized = str(category or "").strip().lower()
    if normalized != "metal":
        return normalized or "generic"
    roughness = _safe_float(material_hints.get("roughness"), 0.55)
    metalness = _safe_float(material_hints.get("metalness"), 0.0)
    specular = _safe_float(material_hints.get("specular"), 0.08)
    if roughness <= 0.34 or specular >= 0.42 or metalness >= 0.68:
        return "glossy_metal"
    if roughness >= 0.68 and specular <= 0.18:
        return "dull_metal"
    return "metal"


def _nonmetal_material_scalar_limits(category: str) -> Tuple[float, float, float]:
    normalized = str(category or "").strip().lower()
    limits = {
        "cloth": (0.0, 0.28, 0.48),
        "leather": (0.0, 0.36, 0.38),
        "wood": (0.0, 0.30, 0.44),
        "skin": (0.0, 0.34, 0.30),
        "hair": (0.0, 0.46, 0.36),
        "stone": (0.0, 0.24, 0.58),
        "tooth": (0.0, 0.26, 0.42),
    }
    return limits.get(normalized, (1.0, 1.0, 0.04))


def _apply_nonmetal_material_scalar_limits(
    material_hints: Dict[str, object],
    material_contract: Mapping[str, object],
    category: str,
) -> bool:
    if str(category or "").strip().lower() not in {"cloth", "leather", "wood", "skin", "hair", "stone", "tooth"}:
        return False
    metal_cap, spec_cap, roughness_floor = _nonmetal_material_scalar_limits(category)
    old_metalness = _safe_float(material_hints.get("metalness"), 0.0)
    old_specular = _safe_float(material_hints.get("specular"), 0.08)
    old_roughness = _safe_float(material_hints.get("roughness"), 0.55)
    new_metalness = min(old_metalness, metal_cap)
    new_specular = min(old_specular, spec_cap)
    new_roughness = max(old_roughness, roughness_floor)
    material_hints["metalness"] = round(float(new_metalness), 4)
    material_hints["specular"] = round(float(new_specular), 4)
    material_hints["roughness"] = round(float(new_roughness), 4)
    pbr_hints = material_contract.get("pbr_scalar_hints") if isinstance(material_contract, Mapping) else None
    if isinstance(pbr_hints, dict):
        pbr_hints["metalness"] = material_hints["metalness"]
        pbr_hints["specular"] = material_hints["specular"]
        pbr_hints["roughness"] = material_hints["roughness"]
    decode_profile = material_contract.get("decode_profile") if isinstance(material_contract, Mapping) else None
    if isinstance(decode_profile, dict):
        profile_hints = decode_profile.get("pbr_scalar_hints")
        if isinstance(profile_hints, dict):
            profile_hints["metalness"] = material_hints["metalness"]
            profile_hints["specular"] = material_hints["specular"]
            profile_hints["roughness"] = material_hints["roughness"]
    return bool(
        new_metalness != old_metalness
        or new_specular != old_specular
        or new_roughness != old_roughness
    )


def _effective_emissive_intensity(
    material_hints: Mapping[str, object],
    *,
    textures: Mapping[str, str],
    dds_textures: Mapping[str, object],
) -> float:
    hinted = _safe_float(material_hints.get("emissive_intensity"), 0.0)
    if bool(material_hints.get("emissive_intensity_declared", False)):
        return max(0.0, hinted)
    if hinted > 0.0:
        return hinted
    if _slot_has_resolved_texture(textures, dds_textures, "emissive"):
        return 4.0
    return 0.0


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

    data = {
        field_info.name: to_jsonable(getattr(texture_input, field_info.name))
        for field_info in dataclasses.fields(PreviewMaterialTextureInput)
    }
    registry_decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=str(getattr(texture_input, "source_dds_path", "") or getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") or ""),
        slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    data["authority"] = str(registry_decode.get("authority", "") or AUTHORITY_GUESS)
    data["disposition"] = str(registry_decode.get("disposition", "") or "")
    data["registry_source_kind"] = str(registry_decode.get("source_kind", "") or "")
    data["promoted_channels"] = dict(registry_decode.get("promoted_channels", {}) or {})
    return data


def _manifest_material_diagnostics(material_contract: Mapping[str, object]) -> list[Dict[str, object]]:
    diagnostics: list[Dict[str, object]] = [
        dict(item)
        for item in tuple(material_contract.get("slot_diagnostics", ()) or ())
        if isinstance(item, Mapping)
    ]
    native_slots = set(_MATERIAL_CONTRACT_SLOTS)
    for item in tuple(material_contract.get("normalized_slot_diagnostics", ()) or ()):
        if not isinstance(item, Mapping):
            continue
        slot_name = str(item.get("slot", "") or "")
        status = str(item.get("status", "") or "")
        if status == "missing":
            continue
        if slot_name in native_slots and status in {"direct_dds", "preview_png"}:
            continue
        diagnostics.append(dict(item))
    return diagnostics


def _manifest_source_path_is_local_file(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Path(text).expanduser().is_file()
    except OSError:
        return False


def _sanitize_nonfile_manifest_source_paths(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: Dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "source_path" and str(item or "").strip() and not _manifest_source_path_is_local_file(item):
                sanitized["source_reference"] = str(item or "")
                continue
            sanitized[key_text] = _sanitize_nonfile_manifest_source_paths(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_nonfile_manifest_source_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_nonfile_manifest_source_paths(item) for item in value]
    return value


def _input_source_label(texture_input: PreviewMaterialTextureInput) -> str:
    return (
        str(getattr(texture_input, "source_dds_path", "") or "")
        or str(getattr(texture_input, "source_texture_path", "") or "")
        or str(getattr(texture_input, "preview_texture_path", "") or "")
        or str(getattr(texture_input, "texture_name", "") or "")
    )


def _input_is_true_base_color(texture_input: PreviewMaterialTextureInput) -> bool:
    parameter_key = _normalized_material_key(getattr(texture_input, "parameter_name", ""))
    if parameter_key != "basecolortexture":
        return False
    source = _input_source_label(texture_input).lower()
    if "texturelayer" in source or "common_default" in source or "default_overlay" in source or "overlay_old" in source:
        return False
    decode = decode_crimson_texture_binding(
        shader_family=str(getattr(texture_input, "shader_family", "") or ""),
        parameter_name=str(getattr(texture_input, "parameter_name", "") or ""),
        source_path=_input_source_label(texture_input),
        slot_name=str(getattr(texture_input, "slot_kind", "") or "base"),
        semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
        packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
        layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
        blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
        sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
        parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
    )
    return str(decode.get("disposition", "") or "") == "promoted"


def _masked_texturelayer_records(batch: PreparedModelPreviewBatch) -> list[Dict[str, object]]:
    records: list[Dict[str, object]] = []
    for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        source = _input_source_label(texture_input)
        parameter_name = str(getattr(texture_input, "parameter_name", "") or "")
        parameter_key = _normalized_material_key(parameter_name)
        decode = decode_crimson_texture_binding(
            shader_family=str(getattr(texture_input, "shader_family", "") or ""),
            parameter_name=parameter_name,
            source_path=source,
            slot_name=str(getattr(texture_input, "slot_kind", "") or "material"),
            semantic_subtype=str(getattr(texture_input, "semantic_subtype", "") or ""),
            packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
            layer_channel=str(getattr(texture_input, "layer_channel", "") or ""),
            blend_flags=tuple(getattr(texture_input, "blend_flags", ()) or ()),
            sidecar_kind=str(getattr(texture_input, "sidecar_kind", "") or ""),
            parameter_declared_by=str(getattr(texture_input, "parameter_declared_by", "") or ""),
        )
        disposition = str(decode.get("disposition", "") or "")
        source_kind = str(decode.get("source_kind", "") or "")
        is_layer_color = (
            "texturelayer" in source.lower()
            or any(token in parameter_key for token in ("grimediffuse", "detaildiffuse", "damageblendingdiffuse"))
        )
        if not is_layer_color and disposition not in {"layer_only", "layer_material_response"}:
            continue
        if disposition not in {"layer_only", "layer_material_response", "layer_flow", "layer_direction"}:
            continue
        records.append(
            {
                "code": "texturelayer_kept_masked",
                "parameter_name": parameter_name,
                "source_path": source,
                "layer_channel": str(decode.get("layer_channel", "") or getattr(texture_input, "layer_channel", "") or ""),
                "disposition": disposition,
                "source_kind": source_kind,
                "authority": str(decode.get("authority", "") or AUTHORITY_GUESS),
            }
        )
    return records


def _material_base_policy_for_batch(
    batch: PreparedModelPreviewBatch,
    *,
    material_category: str,
    combiner_metadata: Mapping[str, object],
) -> Dict[str, object]:
    notes = " ".join(
        str(note or "")
        for note in (
            tuple(combiner_metadata.get("notes", ()) or ())
            + (str(combiner_metadata.get("base_note", "") or ""),)
        )
    )
    masked_records = _masked_texturelayer_records(batch)
    has_true_base = any(
        _input_is_true_base_color(texture_input)
        for texture_input in tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
        if isinstance(texture_input, PreviewMaterialTextureInput)
    )
    neutral_metal = "neutral_metal_base_synthesized" in notes
    no_reliable = bool(
        "no_reliable_full_base_albedo" in notes
        or (str(material_category or "").strip().lower() == "metal" and masked_records and not has_true_base)
    )
    diagnostics: list[Dict[str, object]] = []
    if neutral_metal:
        diagnostics.append(
            {
                "code": "neutral_metal_base_synthesized",
                "reason": "weapon/armor metal had no reliable full base albedo; neutral base seeded from vertex/material/category hints",
                "authority": AUTHORITY_AUTHORITATIVE,
            }
        )
    diagnostics.extend(masked_records)
    if no_reliable:
        diagnostics.append(
            {
                "code": "no_reliable_full_base_albedo",
                "reason": "Crimson texturelayer diffuse inputs were retained as masked layer contribution, not whole-surface albedo",
                "authority": AUTHORITY_AUTHORITATIVE if neutral_metal else AUTHORITY_SIDECAR,
            }
        )
    policy = "true_base_color"
    if neutral_metal:
        policy = "neutral_metal_synthesized"
    elif no_reliable:
        policy = "masked_layers_no_full_base"
    return {
        "schema_version": 1,
        "policy": policy,
        "neutral_metal_base_synthesized": neutral_metal,
        "texturelayer_kept_masked": masked_records,
        "no_reliable_full_base_albedo": no_reliable,
        "true_base_color_texture_present": has_true_base,
        "diagnostics": diagnostics,
    }


_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "alpha_cutoff",
        "alpha_threshold",
        "base_tint_strength",
        "height_amount",
        "height_scale",
        "material_analysis",
        "material_category",
        "material_category_confidence",
        "material_category_reason",
        "material_finish",
        "material_layers",
        "material_response_disposition",
        "material_response_promoted",
        "material_shader_family",
        "metalness",
        "native_base_quality",
        "native_material_hints",
        "normal_strength",
        "primary_material_layer",
        "roughness",
        "specular",
    }
)


def _jsonable_native_material_override(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable_native_material_override(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable_native_material_override(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _native_material_overrides_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    raw_overrides = getattr(batch, "preview_native_material_overrides", None)
    if not isinstance(raw_overrides, Mapping):
        return {}
    return {
        str(key): _jsonable_native_material_override(value)
        for key, value in raw_overrides.items()
        if str(key) in _NATIVE_MATERIAL_OVERRIDE_KEYS
    }



__all__ = [
    "_MATERIAL_CONTRACT_SLOTS",
    "_NATIVE_MATERIAL_OVERRIDE_KEYS",
    "_NORMALIZED_MATERIAL_CONTRACT_SLOTS",
    "_apply_nonmetal_material_scalar_limits",
    "_batch_has_authoritative_family_material_response",
    "_batch_has_explicit_metalness_slot",
    "_batch_has_unlit_material_hint",
    "_batch_weapon_masked_base_tint_should_stay_masked",
    "_byte4_channels",
    "_combiner_generated_authoritative_albedo",
    "_descriptor_contains_token",
    "_descriptor_has_local_strong_nonmetal_token",
    "_descriptor_prefers_sidecar_tint",
    "_effective_emissive_intensity",
    "_input_is_true_base_color",
    "_input_source_label",
    "_jsonable_native_material_override",
    "_manifest_material_diagnostics",
    "_manifest_source_path_is_local_file",
    "_masked_texturelayer_records",
    "_material_base_policy_for_batch",
    "_material_contract_for_batch",
    "_material_contract_shader_family",
    "_material_decode_policy",
    "_material_decode_profile",
    "_material_hex_color_rgb",
    "_material_input_contract_slots",
    "_material_input_descriptor",
    "_material_input_slot_state",
    "_material_input_to_dict",
    "_material_lighting_preset",
    "_material_sidecar_paths",
    "_material_slot_diagnostics",
    "_native_material_hints_for_batch",
    "_native_material_overrides_for_batch",
    "_nonmetal_material_scalar_limits",
    "_normalized_material_key",
    "_normalized_material_texture_slot_states",
    "_normalized_shader_family",
    "_preview_material_family_keys",
    "_preview_material_keys_match",
    "_preview_texture_family_key",
    "_preview_texture_family_key_is_specific_material_response",
    "_preview_tint_color_score",
    "_preview_tint_color_visible",
    "_render_settings_to_dict",
    "_resolved_batch_material_category",
    "_resolved_batch_material_category_reason",
    "_resolved_batch_material_finish",
    "_sanitize_nonfile_manifest_source_paths",
    "sidecar_preview_texture_tint_for_batch",
    "_slot_has_resolved_texture",
    "_source_or_descriptor_has_armor_equipment",
    "_source_or_descriptor_has_weapon_surface",
    "_texture_quality_summary",
    "_texture_slot_state",
]
