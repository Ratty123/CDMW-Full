"""Replacement commands and compact UI state for the existing Rust editor."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
from cdmw.services.mesh_replacement_import import (
    initial_replacement_state, prepare_import, compose_import, commit_replacement,
    set_part_inclusion, reset_or_fit_import,
    mesh_with_part_ids,
)


def replacement_ui_state(authoring):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.replacement_state
    experimental = authoring.neutral_appearance is not None or bool(state and state.neutral_appearance is not None)
    reason = ""
    blocked_by = ""
    if session.archive_refit_context is not None:
        reason = "Finish Morph & Refit, then choose Start next edit pass before changing part inclusion or importing replacements."
        blocked_by = "morph_refit"
    elif getattr(authoring.shadow_service._morph_sessions.get(authoring.shadow_session_id), "profile", None) is not None:
        reason = "Finish Morph & Refit, then choose Start next edit pass before changing part inclusion or importing replacements."
        blocked_by = "morph_refit"
    elif session.output_policy == "free_edit_rebuild":
        reason = (
            "Free Edit exports OBJ geometry without rig weights. "
            "Import Replacement requires an original game mesh with Exact output."
        )
    elif session.mesh_format not in {"pac", "pam", "pamlod"} or not session.original_data or session.lod_index != 0:
        reason = "Replacement requires an eligible original PAC, PAM or PAMLOD at LOD0."
    elif session.output_policy not in {"exact_game_asset", "replacement_game_asset"}:
        reason = "Use an original archive mesh with Exact output before replacing parts."
    digest = state.target_sha256 if state else (session.mesh_asset_source_hash or hashlib.sha256(session.original_data).hexdigest()).lower()
    bindings = {part.part_id: part for part in state.parts} if state else {}
    parts = []
    for index, part in enumerate(session.working_mesh.submeshes):
        key = str(getattr(part, PART_ID_ATTRIBUTE, "")) if state else f"{digest[:16]}:{index}"
        binding = bindings.get(key)
        parts.append({"index": index, "id": key, "name": part.name or f"Part {index}",
                      "included": binding.included if binding else True})
    pending = authoring.pending_replacement
    payload = {"available": not reason, "reason": reason, "active": state is not None,
               "blocked_by": blocked_by,
               "experimental": experimental,
               "comparison": authoring.replacement_comparison, "parts": parts,
               "weight_notes": list(authoring.replacement_weight_notes),
               "rig_export": rig_export_state(session),
               "has_import": bool(state and any(part.import_positions for part in state.parts))}
    if pending is not None:
        payload["pending"] = {
            "token": pending.token,
            "source": pending.label,
            "revision": pending.snapshot.mesh_revision,
            "targets": [part for part in parts if part["id"] in pending.target_part_ids],
            "sources": [{"name": part.name or f"Source {index}", "target": pending.suggested_targets[index]}
                        for index, part in enumerate(pending.source.mesh.submeshes)],
            "materials": imported_material_status(pending),
            "weights": pending.skin.payload() if pending.skin is not None else {"rigged": False},
        }
    return payload


def rig_export_state(session):
    """Whether Export Rig GLB can write this model's skeleton, and if not, why."""
    if str(session.mesh_format or "").lower() != "pac" or not session.original_data:
        return {"available": False, "reason": "Export Rig GLB needs an original skinned PAC from Archive Browser."}
    if not tuple(getattr(session.skeleton, "bones", ()) or ()):
        reason = str(getattr(session, "skeleton_resolution_reason", "") or "").strip()
        return {"available": False, "reason": reason or (
            "No matching PAB skeleton was attached automatically. Open this PAC from Archive Browser "
            "with its skeleton dependencies available.")}
    return {"available": True, "reason": ""}


def export_rig(authoring, args):
    """Write the open PAC skinned to its skeleton as GLB, to weight a new model against."""
    from cdmw.services.mesh_skinning_preflight import export_rig_glb

    folder_text = str(args.get("folder", "") or "").strip()
    folder = Path(folder_text).expanduser() if folder_text else None
    if folder is None or not folder.is_dir():
        raise ValueError("Choose an existing folder for the rig GLB.")
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    with session.export_lock:
        state = rig_export_state(session)
        if not state["available"]:
            raise ValueError(state["reason"])
        data, skeleton = bytes(session.original_data), session.skeleton
        path = str(getattr(session.base_mesh, "path", "") or getattr(session.working_mesh, "path", "") or "model.pac")
    paths = export_rig_glb(data, path, skeleton, folder)
    return {"status": "exported", "paths": [str(item) for item in paths], "glb": str(paths[0])}


_IMAGE_SUFFIXES = {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


def imported_material_status(pending):
    """What Imported Materials & Textures could use, so the mapping step can
    say when Keep Original Materials will draw the game's textures on the
    imported model's own UVs."""
    files = {str(path).casefold() for path, _digest in pending.material_source_files
             if Path(path).suffix.lower() in _IMAGE_SUFFIXES}
    # Embedded glTF/GLB images have no file of their own; their bindings do.
    files.update(str(texture).casefold()
                 for binding in getattr(pending.source, "material_bindings", ()) or ()
                 for _role, texture in getattr(binding, "texture_slots", ()) or ())
    return {"error": pending.material_error, "textures": len(files)}


def run_replacement_command(authoring, command, args, stop_event):
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    if command == "replacement_cancel":
        authoring.pending_replacement = None
        authoring.replacement_weight_notes = ()
        return {"status": "cancelled"}
    if command == "replacement_compare":
        mode = str(args.get("mode", "edit"))
        if mode not in {"edit", "original", "output"}:
            raise ValueError("Unknown replacement comparison mode.")
        if mode == "output":
            snapshot = service.capture_export_snapshot(session_id)
            if snapshot.replacement_state is None:
                raise ValueError("Import a replacement or change output inclusion before previewing output.")
            service._replacement_output_for_snapshot(snapshot)
        authoring.replacement_comparison = mode
        return {"comparison": mode}
    if command == "replacement_export_rig":
        # Reads the original PAC and its skeleton only; works whatever the output mode.
        return export_rig(authoring, args)
    ui = replacement_ui_state(authoring)
    if not ui["available"]:
        raise ValueError(ui["reason"])
    if command == "replacement_choose" and args.get("cancelled"):
        return {"status": "cancelled"}
    snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    entry = args.get("_archive_entry")
    dependencies = ()
    if snapshot.replacement_state is None and command in {"replacement_choose", "replacement_include", "replacement_islands", "replacement_cloth", "replacement_guides", "replacement_weapon_collisions", "replacement_jiggle", "replacement_physics_profile", "replacement_translucency", "replacement_emission", "replacement_shader_controls"}:
        from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies
        dependencies = capture_replacement_dependencies(entry, args.get("_archive_dependencies"), stop_event)
        if authoring.neutral_appearance is not None:
            state = replace(initial_replacement_state(snapshot, entry, dependencies),
                            neutral_appearance=authoring.neutral_appearance, neutral_coordinates=True)
            snapshot = replace(snapshot, mesh=mesh_with_part_ids(snapshot, state), replacement_state=state)
    if command == "replacement_choose":
        selected = tuple(str(value) for value in args.get("part_ids", ()))
        if args.get("scope") == "selected" and not selected:
            raise ValueError("Select at least one target part before importing a replacement.")
        pending = prepare_import(snapshot, args.get("source_path", ""), target_part_ids=selected,
                                 entry=entry, dependencies=dependencies, stop_event=stop_event,
                                 blender=args.get("_blender"), work_dir=authoring.root / "fbx-import")
        authoring._raise_if_cancelled(stop_event)
        authoring.pending_replacement = pending
        authoring.replacement_weight_notes = ()
        return {"status": "choose_mapping"}
    if command == "replacement_apply":
        pending = authoring.pending_replacement
        if pending is None:
            raise ValueError("Choose a replacement model first.")
        if str(args.get("token", "")) != pending.token:
            raise ValueError("This replacement mapping belongs to an older import. Review the current import before applying.")
        if pending.snapshot.mesh_revision != snapshot.mesh_revision:
            raise ValueError("The mesh changed after import preparation. Import again before applying.")
        choice = str(args.get("materials", "original"))
        targets = tuple(args.get("targets", ()))
        files = None
        if choice == "imported":
            from cdmw.services.mesh_replacement_materials import prepare_imported_materials
            files = prepare_imported_materials(pending, targets, authoring.root, stop_event)
        weights = str(args.get("weights", "") or "") or None
        skin_notes = []
        mesh, state = compose_import(pending, targets, material_choice=choice, companion_files=files,
                                     skin_policy=weights, skin_notes=skin_notes)
        authoring._preflight_mesh_document_capacity(mesh)
        from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
        stage_replacement_materials(authoring, mesh, state, stop_event)
        result = commit_replacement(service, snapshot, mesh, state, label="Import replacement", stop_event=stop_event)
        authoring.pending_replacement = None
        authoring.replacement_weight_notes = tuple(dict.fromkeys(skin_notes))
    elif command == "replacement_include":
        result = set_part_inclusion(service, snapshot, args.get("part_ids", ()), bool(args.get("included", True)),
                                    entry=entry, dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_islands":
        from cdmw.services.mesh_island_authoring import set_island_inclusion
        result = set_island_inclusion(authoring, snapshot, args, entry=entry,
                                     dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_cloth":
        from cdmw.services.mesh_rust_cloth import set_cloth_rule
        result = set_cloth_rule(authoring, snapshot, args, entry=entry,
                               dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_guides":
        from cdmw.services.mesh_rust_cloth_guides import set_guide_rule
        result = set_guide_rule(authoring, snapshot, args, entry=entry,
                               dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_weapon_collisions":
        from cdmw.services.mesh_rust_weapon_collisions import set_weapon_collisions
        result = set_weapon_collisions(authoring, snapshot, args, entry=entry,
                                      dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_shader_controls":
        from cdmw.services.mesh_shader_controls import set_shader_controls
        result = set_shader_controls(authoring, snapshot, args, entry=entry, dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_emission":
        from cdmw.services.mesh_emission import set_emission
        result = set_emission(authoring, snapshot, args, entry=entry, dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_translucency":
        from cdmw.services.mesh_translucency import set_translucency
        result = set_translucency(authoring, snapshot, args, entry=entry,
                                  dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_jiggle":
        from cdmw.services.mesh_rust_jiggle import set_jiggle_rule
        result = set_jiggle_rule(authoring, snapshot, args, entry=entry,
                                dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_physics_profile":
        from cdmw.services.mesh_rust_physics_profiles import set_physics_profile_rule
        result = set_physics_profile_rule(authoring, snapshot, args, entry=entry,
                                        dependencies=dependencies, stop_event=stop_event)
    elif command in {"replacement_fit", "replacement_reset"}:
        result = reset_or_fit_import(service, snapshot, fit=command == "replacement_fit", stop_event=stop_event)
    else:
        raise ValueError(f"Unsupported replacement command: {command}")
    authoring.replacement_comparison = "edit"
    return result
