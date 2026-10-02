"""Weapon collider intent through the existing shadow replacement transaction."""

from dataclasses import replace

from cdmw.modding.pac_weapon_collisions import weapon_capsules, weapon_collision_layout
from cdmw.services.mesh_replacement_import import commit_replacement, initial_replacement_state, mesh_with_part_ids


def weapon_collision_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.replacement_state
    active = bool(state and state.weapon_collisions)
    reason = replacement["reason"]
    count = source_count = 0
    if session.mesh_format != "pac" or session.hair_state is not None:
        reason = "Weapon colliders require an original PAC outside the hair workflow."
    if not reason:
        try:
            source, _ = weapon_collision_layout(session.original_data)
            source_count = len(source.volumes)
            included = {row["index"] for row in replacement["parts"] if row["included"]}
            capsules = weapon_capsules(session.original_data, parts=session.working_mesh.submeshes, included=included)
            count = len(capsules)
        except ValueError as exc:
            reason = str(exc)
    return {"available": not reason, "reason": reason, "active": active,
            "source_count": source_count, "capsule_count": count}


def set_weapon_collisions(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    if (not {"enabled"} <= set(args) or set(args) - {"enabled", "_archive_entry", "_archive_dependencies"}
            or type(args["enabled"]) is not bool):
        raise ValueError("Choose whether to create or restore weapon colliders.")
    ui = weapon_collision_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"] and (args["enabled"] or not ui["active"]):
        raise ValueError(ui["reason"])
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    if state.weapon_collisions == args["enabled"]:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, weapon_collisions=args["enabled"], revision=state.revision + 1)
    return commit_replacement(authoring.shadow_service, snapshot, mesh_with_part_ids(snapshot, state), state,
        label="Create weapon colliders" if args["enabled"] else "Restore source colliders", stop_event=stop_event)
