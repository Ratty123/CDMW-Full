"""Exact profile assignments and supported values for the controlled cloth preview.

Source documents remain immutable. This projection neither selects a live game
variant nor changes PAC output, profile XML, or the preview's dispatch schedule.
"""

from __future__ import annotations

import struct

from cdmw.core.pbd_cloth import _material_scalar_items, _parse_xml
from cdmw.modding._pbd_numeric import f32, round_pbd_half
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth_runtime import update_cloth_frame_stiffness
from cdmw.services.mesh_physics_profiles import _xml_text


_SCALARS = (
    "simulationmode", "stretchingstiffness", "bendingstiffness", "damping",
    "gravity", "solveriterationcount", "usevertexalphapositionblending",
    "userotationcorrection", "useautoweightingpositionblending",
)


def _profile_preview(document):
    result = {"path": document.path, "sha256": document.sha256,
              "authored": {}, "preview": None, "reason": ""}
    root = _parse_xml(_xml_text(document.data))
    items = _material_scalar_items(root) if root is not None else ()
    values = {key: value for key, value in items if key in _SCALARS}
    result["authored"] = values
    if values.get("simulationmode", "").casefold() != "cloth":
        result["reason"] = "Only an explicit cloth profile can supply guide-cloth preview settings."
        return result
    required = ("stretchingstiffness", "bendingstiffness", "damping", "gravity", "solveriterationcount")
    if any(key not in values for key in required):
        result["reason"] = "The profile does not explicitly supply all supported preview coefficients."
        return result
    try:
        stretch, bend, damping, gravity = (f32(float(values[key])) for key in required[:4])
        iterations = int(values["solveriterationcount"])
        # The CPU material parser rounds odd XML counts upward. This preview
        # still uses its controlled loop, not the game's LOD/dispatch admission.
        iterations += iterations & 1
        if not (-100 <= gravity <= 0 and 0 <= damping <= 10 and 1 <= iterations <= 8):
            result["reason"] = "Authored values exceed the supported cloth preview range."
            return result
        # Decoded material initialization: alpha enabled; mode processing resets
        # rotation (cloth=on, spline=off) in XML source order.
        alpha, rotation = True, False
        for key, value in items:
            if key == "simulationmode":
                rotation = value.casefold() == "cloth"
            elif key in ("usevertexalphapositionblending", "userotationcorrection"):
                if value not in ("0", "1"):
                    result["reason"] = "A supported profile flag is not an explicit zero or one."
                    return result
                if key == "usevertexalphapositionblending":
                    alpha = value == "1"
                else:
                    rotation = value == "1"
        # Recovered initialization globals, never presented as captured live
        # settings. Read the packed half coefficients actually supplied to GPU.
        frame = update_cloth_frame_stiffness(
            bytes(100), simulation_mode=1, stretching_stiffness=stretch,
            bending_stiffness=bend, area_stiffness=0, restore_angle_stiffness=0,
            underwater_restore_angle_stiffness=-1, stiffness_denominator=4,
            scale_factors=(5, 1, 1, 1), limits=(.6, .06, .6, .06),
            bend_uses_unit_denominator=True,
        )["per_frame"]
        modified_stretch, modified_bend = struct.unpack_from("<2e", frame, 66)
        result["preview"] = {
            "gravity": -round_pbd_half(gravity), "damping": round_pbd_half(damping),
            "stretch": modified_stretch, "bend": max(0., modified_bend),
            "iterations": iterations, "use_vertex_alpha": alpha, "rotate_guides": rotation,
        }
    except (ValueError, OverflowError):
        result["reason"] = "The profile contains invalid or unsupported preview values."
    return result


def physics_profiles_ui_state(authoring, replacement):
    """Project retained sources using original PAC part names and target indices."""
    context = authoring.physics_profile_context
    if context is None:
        return {"available": False, "reason": "No exact archive physics profile context is available.",
                "parts": [], "profiles": [], "variants": []}
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    data = session.original_data
    cached = authoring.physics_profile_cache
    if cached is None or cached[0] is not data or cached[1] is not context:
        try:
            source = parse_pac(data, context.source_identity.normalized_path)
            names = tuple(part.name for part in source.submeshes)
            problem = ""
        except (ValueError, OSError) as exc:
            names, problem = (), str(exc)
        metadata = {
            "available": context.sidecar is not None and not problem,
            "reason": problem or context.problem,
            "source": context.source_identity.normalized_path,
            "sidecar": context.sidecar.path if context.sidecar else "",
            "sidecar_sha256": context.sidecar.sha256 if context.sidecar else "",
            "profiles": [_profile_preview(document) for document in context.profiles],
            "variants": list(dict.fromkeys(binding.variant_index for binding in context.bindings)),
        }
        cached = (data, context, metadata, names)
        authoring.physics_profile_cache = cached
    _, _, metadata, names = cached
    state = session.replacement_state
    targets = {part.part_id: part.target_index for part in state.parts} if state else {}
    parts = []
    for part in replacement["parts"]:
        # A renamed/replaced part retains its original target. Unmapped parts
        # never acquire an assignment by matching their current display name.
        index = targets.get(part["id"], -1) if state else part["index"]
        name = names[index] if 0 <= index < len(names) else ""
        bindings = [{"variant": binding.variant_index, "profile": binding.profile_name,
                     "path": binding.profile_path, "material": binding.material_name,
                     "reason": binding.problem}
                    for binding in context.bindings if name and binding.submesh_name == name]
        parts.append({**part, "source_name": name, "bindings": bindings})
    return {**metadata, "parts": parts}
