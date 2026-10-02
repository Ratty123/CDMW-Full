"""Cloth influence controls backed by the reversible replacement output state."""

from __future__ import annotations

from dataclasses import replace

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_profile_admission
from cdmw.services.mesh_replacement_import import (
    commit_replacement, initial_replacement_state, mesh_with_part_ids,
)


def cloth_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.replacement_state
    reason = replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Cloth influence requires an original PAC mesh."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before editing cloth influence."
    if reason:
        return {"available": False, "reason": reason, "parts": []}
    from cdmw.services.mesh_rust_cloth_guides import authored_cloth_source
    try:
        data, _ = authored_cloth_source(authoring, session)
    except ValueError as exc:
        return {"available": False, "reason": str(exc), "parts": []}
    appearance = state.neutral_appearance if state and state.neutral_appearance is not None else authoring.neutral_appearance
    cached = authoring.cloth_source_cache
    if cached is None or cached[0] is not data or cached[1] is not appearance:
        try:
            guides = decode_pac_cloth_guides(data)
            guide_state = ({"status": "available", "guide_count": len(guides.vertices),
                            "fixed_count": guides.channel_b.count(255),
                            **inspect_guide_profile_admission(guides.metadata_flags, len(guides.vertices))}
                           if guides and guides.vertices else {"status": "absent", "guide_count": 0})
        except ValueError as exc:
            guide_state = {"status": "unsupported", "reason": str(exc)}
        try:
            levels = pac_cloth_lods(data)
            displayed = appearance.to_neutral(levels[0]) if appearance is not None else levels[0]
            rows = []
            for index, part in enumerate(levels[0].submeshes):
                bindings = [[pac_cloth_binding(data, offset) for offset in level.submeshes[index].source_vertex_offsets]
                            for level in levels]
                heights = [point[1] for point, offset in zip(displayed.submeshes[index].vertices, part.source_vertex_offsets, strict=True)
                           if pac_cloth_binding(data, offset) is not None]
                counts = [sum(binding is not None for binding in level) for level in bindings]
                rows.append({"source_count": len(heights), "lod_counts": counts,
                             "lod_vertices": [len(level.submeshes[index].vertices) for level in levels],
                             "max_guide_index": max((slot for level in bindings for binding in level
                                                     if binding is not None for slot in binding[1]), default=-1),
                             "min_y": min(heights, default=0.0), "max_y": max(heights, default=0.0)})
            metadata = {"parts": rows, "lod_count": len(levels), "reason": "", "guides": guide_state}
        except ValueError as exc:
            metadata = {"parts": [], "lod_count": 0, "reason": str(exc), "guides": guide_state}
        authoring.cloth_source_cache = (data, appearance, metadata)
    else:
        metadata = cached[2]
    bindings = {part.part_id: part for part in state.parts} if state else {}
    parts = []
    inspected = []
    for part in replacement["parts"]:
        binding = bindings.get(part["id"])
        index = binding.target_index if binding else part["index"]
        if not 0 <= index < len(metadata["parts"]):
            continue
        source = metadata["parts"][index]
        row = {**part, **source, "rule": binding.cloth.to_dict() if binding and binding.cloth else None}
        inspected.append(row)
        if not any(source["lod_counts"]):
            continue
        parts.append(row)
    reason = metadata["reason"] or ("This PAC has no existing cloth bindings." if not parts else "")
    return {"available": not reason, "reason": reason, "parts": parts, "lod_count": metadata["lod_count"],
            "inspected_parts": inspected, "inspection_reason": metadata["reason"], "guides": metadata["guides"]}


def physics_detection_ui_state(replacement, cloth, jiggle, profiles):
    """Combine proven vertex ownership, guide resources and exact assignments.

    A shared profile or a suggestive part name alone never establishes physics.
    The PAC mode is only a default; exact variant assignments take precedence.
    Detection stays useful without a preview rig and does not change output.
    """
    inspected = {part["id"]: part for part in cloth.get("inspected_parts", ())}
    jiggle_parts = {part["id"]: part for part in jiggle.get("parts", ())}
    profile_parts = {part["id"]: part for part in profiles.get("parts", ())}
    overlays = {part["index"]: part["preview"] for part in jiggle.get("overlay_parts", ())}
    by_path = {}
    for profile in profiles.get("profiles", ()):
        by_path.setdefault(profile["path"].casefold(), set()).add(
            profile.get("authored", {}).get("simulationmode", "").casefold())
    guides = cloth.get("guides", {})
    rows = []
    for part in replacement["parts"]:
        source = inspected.get(part["id"])
        guide_counts = source["lod_counts"] if source else []
        jiggle_source = jiggle_parts.get(part["id"])
        jiggle_counts = (jiggle_source["lod_counts"] if jiggle_source else
                         [0] * len(guide_counts) if jiggle.get("lod_count") == len(guide_counts) else [])
        kind, mode_source, reason = "unknown", "", ""
        assignments = []
        for binding in profile_parts.get(part["id"], {}).get("bindings", ()):
            modes = by_path.get(binding["path"].casefold(), set())
            assignments.append({**binding, "mode": next(iter(modes)) if len(modes) == 1 else ""})
        if source is None or not jiggle_counts:
            reason = cloth.get("inspection_reason") or cloth.get("reason") or jiggle.get("reason", "")
        elif not any(guide_counts):
            kind = "jiggle" if any(jiggle_counts) else "none"
        else:
            kind = "guide"
            if guides.get("status") != "available":
                reason = guides.get("reason") or "guide_mesh_missing"
            elif source["max_guide_index"] >= guides["guide_count"]:
                reason = "guide_indices_out_of_range"
            elif not assignments:
                kind = guides["default_profile_mode"]
                mode_source = "pac_default"
                reason = profiles.get("reason") or "profile_assignment_missing"
            else:
                modes = {assignment["mode"] for assignment in assignments if assignment["profile"]}
                variants = [assignment["variant"] for assignment in assignments]
                if any(assignment["reason"] or (assignment["profile"] and not assignment["mode"])
                       for assignment in assignments) or len(set(variants)) != len(variants):
                    mode_source = "unresolved"
                    reason = "profile_assignment_unresolved"
                elif len(modes) == 1 and modes <= {"cloth", "spline"}:
                    kind = next(iter(modes))
                    mode_source = "profile"
                elif not modes:
                    mode_source = "variants"
                    reason = "profile_assignment_empty"
                elif len(modes) > 1:
                    mode_source = "variants"
                    reason = "profile_modes_mixed"
                else:
                    mode_source = "profile"
                    reason = "profile_mode_unsupported"
        overlay = overlays.get(part["index"], {})
        current_guides = overlay.get("current_cloth_bytes") if overlay.get("available") else None
        current_jiggle = overlay.get("current_bytes") if overlay.get("available") else None
        decoded = jiggle.get("decoded", {})
        preview_reason = ""
        if any(guide_counts):
            preview_reason = ("spline_preview_approximate" if kind == "spline" else
                              decoded.get("reason") if not decoded.get("available") else
                              decoded.get("cloth", {}).get("reason", ""))
        rows.append({"id": part["id"], "index": part["index"], "name": part["name"],
                     "kind": kind, "mode_source": mode_source, "reason": reason,
                     "guide_counts": guide_counts, "vertex_counts": source["lod_vertices"] if source else [],
                     "jiggle_counts": jiggle_counts, "guides": dict(guides), "profiles": assignments,
                     "current_guide_count": sum(value < 63 for value in current_guides) if current_guides is not None else None,
                     "current_jiggle_count": sum(value & 15 != 15 for value in current_jiggle) if current_jiggle is not None else None,
                     "preview_reason": preview_reason or ""})
    return {"parts": rows}


def set_cloth_rule(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    ui = cloth_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid cloth reset request.")
    keys = args.get("part_ids")
    if not isinstance(keys, (list, tuple)) or not keys or any(not isinstance(key, str) for key in keys):
        raise ValueError("Choose at least one cloth part.")
    if len(set(keys)) != len(keys):
        raise ValueError("Cloth parts must be unique.")
    available = {part["id"] for part in ui["parts"] if part["included"]}
    if not set(keys) <= available:
        raise ValueError("Choose included parts with existing cloth bindings.")
    rule = None if reset else PacClothRule.from_dict(args.get("rule"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, cloth=rule) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    mesh = mesh_with_part_ids(snapshot, state)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore cloth influence" if reset else "Edit cloth influence",
                              stop_event=stop_event)
