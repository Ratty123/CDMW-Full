"""Cloth influence controls backed by the reversible replacement output state."""

from __future__ import annotations

from dataclasses import replace

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
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
    data = session.original_data
    appearance = state.neutral_appearance if state and state.neutral_appearance is not None else authoring.neutral_appearance
    cached = authoring.cloth_source_cache
    if cached is None or cached[0] is not data or cached[1] is not appearance:
        try:
            levels = pac_cloth_lods(data)
            displayed = appearance.to_neutral(levels[0]) if appearance is not None else levels[0]
            rows = []
            for index, part in enumerate(levels[0].submeshes):
                heights = [point[1] for point, offset in zip(displayed.submeshes[index].vertices, part.source_vertex_offsets, strict=True)
                           if pac_cloth_binding(data, offset) is not None]
                counts = [sum(pac_cloth_binding(data, offset) is not None
                              for offset in level.submeshes[index].source_vertex_offsets) for level in levels]
                rows.append({"source_count": len(heights), "lod_counts": counts,
                             "min_y": min(heights, default=0.0), "max_y": max(heights, default=0.0)})
            metadata = {"parts": rows, "lod_count": len(levels), "reason": ""}
        except ValueError as exc:
            metadata = {"parts": [], "lod_count": 0, "reason": str(exc)}
        authoring.cloth_source_cache = (data, appearance, metadata)
    else:
        metadata = cached[2]
    bindings = {part.part_id: part for part in state.parts} if state else {}
    parts = []
    for part in replacement["parts"]:
        binding = bindings.get(part["id"])
        index = binding.target_index if binding else part["index"]
        if not 0 <= index < len(metadata["parts"]):
            continue
        source = metadata["parts"][index]
        if not any(source["lod_counts"]):
            continue
        parts.append({**part, **source, "rule": binding.cloth.to_dict() if binding and binding.cloth else None})
    reason = metadata["reason"] or ("This PAC has no existing cloth bindings." if not parts else "")
    return {"available": not reason, "reason": reason, "parts": parts, "lod_count": metadata["lod_count"]}


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
