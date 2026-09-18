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
    if session.archive_refit_context is not None:
        reason = "Undo active Morph & Refit archive bindings before replacing parts."
    elif getattr(authoring.shadow_service._morph_sessions.get(authoring.shadow_session_id), "profile", None) is not None:
        reason = "Clear the active Morph & Refit profile before replacing parts."
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
               "experimental": experimental,
               "comparison": authoring.replacement_comparison, "parts": parts,
               "has_import": bool(state and any(part.import_positions for part in state.parts))}
    if pending is not None:
        payload["pending"] = {
            "token": pending.token,
            "source": Path(pending.source_path).name,
            "revision": pending.snapshot.mesh_revision,
            "targets": [part for part in parts if part["id"] in pending.target_part_ids],
            "sources": [{"name": part.name or f"Source {index}", "target": pending.suggested_targets[index]}
                        for index, part in enumerate(pending.source.mesh.submeshes)],
        }
    return payload


def run_replacement_command(authoring, command, args, stop_event):
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    if command == "replacement_cancel":
        authoring.pending_replacement = None
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
    ui = replacement_ui_state(authoring)
    if not ui["available"]:
        raise ValueError(ui["reason"])
    if command == "replacement_choose" and args.get("cancelled"):
        return {"status": "cancelled"}
    snapshot = service.capture_export_snapshot(session_id, stop_event=stop_event)
    entry = args.get("_archive_entry")
    dependencies = ()
    if snapshot.replacement_state is None and command in {"replacement_choose", "replacement_include", "replacement_cloth", "replacement_jiggle"}:
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
                                 entry=entry, dependencies=dependencies, stop_event=stop_event)
        authoring._raise_if_cancelled(stop_event)
        authoring.pending_replacement = pending
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
        mesh, state = compose_import(pending, targets, material_choice=choice, companion_files=files)
        authoring._preflight_mesh_document_capacity(mesh)
        from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
        stage_replacement_materials(authoring, mesh, state, stop_event)
        result = commit_replacement(service, snapshot, mesh, state, label="Import replacement", stop_event=stop_event)
        authoring.pending_replacement = None
    elif command == "replacement_include":
        result = set_part_inclusion(service, snapshot, args.get("part_ids", ()), bool(args.get("included", True)),
                                    entry=entry, dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_cloth":
        from cdmw.services.mesh_rust_cloth import set_cloth_rule
        result = set_cloth_rule(authoring, snapshot, args, entry=entry,
                               dependencies=dependencies, stop_event=stop_event)
    elif command == "replacement_jiggle":
        from cdmw.services.mesh_rust_jiggle import set_jiggle_rule
        result = set_jiggle_rule(authoring, snapshot, args, entry=entry,
                                dependencies=dependencies, stop_event=stop_event)
    elif command in {"replacement_fit", "replacement_reset"}:
        result = reset_or_fit_import(service, snapshot, fit=command == "replacement_fit", stop_event=stop_event)
    else:
        raise ValueError(f"Unsupported replacement command: {command}")
    authoring.replacement_comparison = "edit"
    return result
