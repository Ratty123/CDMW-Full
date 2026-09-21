"""New-guide controls through the existing shadow replacement transaction."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import guide_creation_layout
from cdmw.services.mesh_replacement_import import commit_replacement, initial_replacement_state, mesh_with_part_ids


def authored_cloth_source(authoring, session):
    """Retain generated bindings even when an influence rule disables them.

    This runs on the existing host worker. Cache the output and parsed LOD0 by
    mesh revision; UI state and the decoded preview share that one immutable copy.
    """
    state = session.replacement_state
    if (not state or not any(p.included and p.cloth_guides for p in state.parts)
            or authoring.replacement_comparison == "original"):
        return session.original_data, None
    key = (session.revision, session.material_generation, id(session.original_data), state)
    cached = authoring.cloth_guide_output_cache
    if cached is None or cached[0] != key:
        from cdmw.services.mesh_replacement_output import prepare_replacement_output
        snapshot = authoring.shadow_service.capture_export_snapshot(authoring.shadow_session_id)
        base = replace(state, parts=tuple(replace(p, cloth=None) for p in state.parts))
        data = prepare_replacement_output(replace(snapshot, replacement_state=base)).data
        authoring.cloth_guide_output_cache = (key, data, pac_cloth_lods(data)[0].submeshes)
    return authoring.cloth_guide_output_cache[1:]


def guide_authoring_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.replacement_state
    saved = {p.part_id: p for p in state.parts} if state else {}
    reason = replacement["reason"]
    if session.mesh_format != "pac" or session.hair_state is not None:
        reason = "Guide creation requires an original PAC outside the hair workflow."
    rows, palette, levels = [], (), ()
    cache = authoring.cloth_guide_layout_cache
    if not reason:
        if cache is None or cache[0] is not session.original_data:
            try:
                layout = guide_creation_layout(session.original_data)
                cache = (session.original_data, layout, "")
            except ValueError as exc:
                cache = (session.original_data, None, str(exc))
            authoring.cloth_guide_layout_cache = cache
        reason = cache[2]
        if not reason:
            _, _, palette, levels = cache[1]
            hashes = Counter(bone.name_hash for bone in getattr(session.skeleton, "bones", ()))
            retained = any(p.cloth_guides and p.cloth_guides.bone_palette == palette for p in saved.values())
            if not retained and any(hashes[value] != 1 for value in palette):
                reason = "Attach the matching skeleton before creating guides on its existing bones."
            appearance = state.neutral_appearance if state else authoring.neutral_appearance
            displayed = appearance.to_neutral(levels[0]) if appearance else levels[0]
            for part in replacement["parts"]:
                binding = saved.get(part["id"])
                index = binding.target_index if binding else part["index"]
                if not 0 <= index < len(displayed.submeshes):
                    continue
                points = displayed.submeshes[index].vertices
                rows.append({**part, "lod_vertices": [len(level.submeshes[index].vertices) for level in levels],
                    "min_y": min((p[1] for p in points), default=0.0),
                    "max_y": max((p[1] for p in points), default=0.0),
                    "rule": binding.cloth_guides.to_dict() if binding and binding.cloth_guides else None})
    return {"available": not reason, "reason": reason, "parts": rows,
            "lod_count": len(levels), "guide_limit": 1024,
            "active": any(p.cloth_guides is not None for p in saved.values())}


def set_guide_rule(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    ui = guide_authoring_ui_state(authoring, replacement_ui_state(authoring))
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid guide reset request.")
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys
            or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)):
        raise ValueError("Choose unique included parts for guide creation.")
    if not ui["available"]:
        raise ValueError(ui["reason"])
    available = {part["id"] for part in ui["parts"] if part["included"] or reset and part["rule"]}
    if not set(keys) <= available:
        raise ValueError("Choose included parts for guide creation.")
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    rule = None
    if not reset:
        _, _, palette, _ = guide_creation_layout(snapshot.original_data)
        rule = PacClothGuideRule(args.get("source_lod"), args.get("fixed_above"), palette, args.get("reduce_skinning", False))
    parts = tuple(replace(p, cloth_guides=rule, cloth=None if reset else p.cloth) if p.part_id in keys else p for p in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    return commit_replacement(authoring.shadow_service, snapshot, mesh_with_part_ids(snapshot, state), state,
        label="Restore source guides" if reset else "Create cloth guides", stop_event=stop_event)
