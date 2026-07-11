from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_editable_shape_subject(shape: Mapping[str, object]) -> str:
    name_hint = shape.get("name_hint")
    if isinstance(name_hint, Mapping) and str(name_hint.get("name") or "").strip():
        return str(name_hint.get("name") or "").strip()
    body_contexts = shape.get("body_contexts")
    if isinstance(body_contexts, list):
        for context in body_contexts:
            if not isinstance(context, Mapping):
                continue
            for key in ("body_name", "socket_name", "fixed_socket_name"):
                value = str(context.get(key) or "").strip()
                if value:
                    return value
    shape_index = shape.get("index")
    shape_type = str(shape.get("shape_type") or "hknpShape")
    return f"{shape_type} {shape_index}" if shape_index is not None else shape_type


@bind_archive_hkx_globals()
def _hkx_editable_catalog_semantics(field: Mapping[str, object]) -> Dict[str, str]:
    category = str(field.get("category") or "").casefold()
    name = str(field.get("name") or "").casefold()
    description = str(field.get("description") or "").casefold()
    if name in {"capsule_radius", "sphere_radius"} or "radius" in name:
        return {
            "effect": "collision volume",
            "edit_guidance": "Increase to make the body collide sooner/larger; decrease to shrink collision. Keep positive and make small changes.",
            "value_constraints": "finite positive float; fixed offset; no record or array length changes",
            "suggested_edit_step": "try +/- 5% to 10% first",
        }
    if name in {"capsule_endpoints", "vertices", "planes"} or "vertex" in description or "plane" in description:
        return {
            "effect": "collision shape",
            "edit_guidance": "Moves the fixed collision volume. Keep row counts unchanged; large edits can misalign the body and visible mesh.",
            "value_constraints": "finite floats only; same row count; same component count",
            "suggested_edit_step": "move one axis slightly, then test collision alignment",
        }
    if name == "hull_topology" or "hull" in name:
        return {
            "effect": "collision topology",
            "edit_guidance": "Experimental. Only same-count topology values are patchable; prefer vertex/plane/radius edits first.",
            "value_constraints": "same face/index/edge counts; integer ranges must stay valid",
            "suggested_edit_step": "avoid unless matching another known-good hull layout",
        }
    if "mass" in name or "mass" in category or "inertia" in description:
        return {
            "effect": "mass/inertia",
            "edit_guidance": "Likely affects weight, inertia, and solver behavior. Use small changes; exact Havok 2024.2 field names are not confirmed.",
            "value_constraints": "finite float; fixed offset; keep object count unchanged",
            "suggested_edit_step": "try +/- 10% and compare motion stability",
        }
    if "stiffness" in name or "strength" in name:
        return {
            "effect": "stiffness/strength",
            "edit_guidance": "Higher values usually resist motion more strongly; lower values may loosen jiggle or joint response.",
            "value_constraints": "finite float; fixed offset; avoid negative values unless the source already uses them",
            "suggested_edit_step": "try +/- 10% to 25% and test motion response",
        }
    if "damping" in name or "tau" in name or "response" in name or "recovery" in name:
        return {
            "effect": "damping/response",
            "edit_guidance": "Higher values may settle motion faster or make it more constrained; lower values may allow more oscillation.",
            "value_constraints": "finite float; fixed offset; avoid extreme jumps",
            "suggested_edit_step": "try +/- 10% to 25% and check for jitter",
        }
    if "force" in name or "torque" in name:
        return {
            "effect": "force/torque limit",
            "edit_guidance": "Likely caps motor or friction strength. Larger limits can make constraints hold harder; smaller limits can allow more movement.",
            "value_constraints": "finite float; fixed offset; keep sign convention unless understood",
            "suggested_edit_step": "try +/- 10% to 25%; keep min/max pairs ordered",
        }
    if "limit" in name or "angle" in name or "constraint" in category:
        return {
            "effect": "joint limit",
            "edit_guidance": "Likely affects angular limits or joint frames. Edit cautiously because axes and units are still inferred.",
            "value_constraints": "finite float; fixed offset; preserve vector/axis grouping",
            "suggested_edit_step": "change one component at a time and compare pose range",
        }
    if "motion" in category or "solver" in category:
        return {
            "effect": "motion solver",
            "edit_guidance": "Likely affects damping, velocity limits, or solver response across one or more bodies. Make small changes and test in game.",
            "value_constraints": "finite float; fixed offset; preserve signs unless source pattern is understood",
            "suggested_edit_step": "try +/- 10% and test for solver instability",
        }
    return {
        "effect": "unknown fixed-size value",
        "edit_guidance": "Patchable only because its byte offset is stable. Meaning is experimental; change one value at a time.",
        "value_constraints": "finite float; fixed offset; same payload length",
        "suggested_edit_step": "make one small change and keep a known-good backup",
    }


@bind_archive_hkx_globals(
    'math',
    'struct',
)
def _hkx_decode_patch_map_original_value(original_bytes: bytes, value_type: str) -> object:
    if not original_bytes:
        return ""
    normalized_type = str(value_type or "").strip().lower()
    try:
        if normalized_type == "float32" and len(original_bytes) >= 4:
            value = struct.unpack_from("<f", original_bytes, 0)[0]
            return float(value) if math.isfinite(value) else ""
        if normalized_type in {"uint8", "byte"} and len(original_bytes) >= 1:
            return int(original_bytes[0])
        if normalized_type in {"uint16", "ushort"} and len(original_bytes) >= 2:
            return int(struct.unpack_from("<H", original_bytes, 0)[0])
        if normalized_type in {"uint32", "int32"} and len(original_bytes) >= 4:
            return int(struct.unpack_from("<I", original_bytes, 0)[0])
    except (struct.error, ValueError, OverflowError):
        return original_bytes.hex(" ").upper()
    return original_bytes.hex(" ").upper()
