"""Atomic archive Refit loading and explicit body assignment for Edit Mesh."""

from dataclasses import replace
import copy
from pathlib import Path
from uuid import uuid4

from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_archive_refit import append_archive_refit
from cdmw.services.mesh_refit_loading import stage_refit_morph_runtime
from cdmw.services.mesh_service_state import _MeshGeometryLayer


def load_archive_refit(authoring, args, stop_event):
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(session_id)
    role = str(args.get("role", ""))
    incoming = args.get("_archive_snapshot")
    if incoming is None:
        raise ValueError("Choose the Refit source through the game archive browser")
    with session.export_lock:
        if session.output_policy != "exact_game_asset":
            raise ValueError("Archive Refit needs Exact Game Asset output for the loaded game mesh")
        service._require_baked_morph_definition_edit(session)
        state = service.cached_morph_state_from_runtime(session_id)
        if state.refit.garment_submesh_indices:
            raise ValueError("Clear Refit before loading another archive mesh")
        current = service.capture_export_snapshot(session_id, stop_event=stop_event)
        entry = args["_archive_entry"]
        combined, context, indices = append_archive_refit(
            current, args["_primary_entry"], incoming, entry, role,
            args.get("_archive_preview_lease"),
            primary_source=authoring._source_coordinate_snapshot(current),
            primary_appearance=authoring.neutral_appearance,
            incoming_appearance=args.get("_archive_neutral_appearance"),
        )
        prepared = service.prepare_working_mesh_replacement(
            session_id, combined, archive_refit_context=context,
        )
        if not prepared.validation_report.ok:
            raise ValueError(prepared.validation_report.blockers[0].message)
        prepared = replace(prepared, selection=MeshEditSelection(source_indices=indices))
        admitted = authoring._preflight_mesh_document_capacity(prepared.working_mesh)
        stage_archive_refit_materials(authoring, prepared.working_mesh, context, stop_event)
        driver_indices = indices if role == "body" else (
            context.assets[0].part_indices if not state.driver_submesh_indices else None
        )
        morph = stage_refit_morph_runtime(
            service, session_id, prepared.working_mesh,
            driver_indices=driver_indices,
        )
        try:
            layers = (*session.geometry_layers, _MeshGeometryLayer(
                layer_id=f"refit-{uuid4().hex[:12]}",
                name=f"{role.title()} / {Path(entry.path).name}", submesh_indices=indices,
            ))
            authoring._raise_if_cancelled(stop_event)
            view = service.commit_prepared_working_mesh_replacement(
                prepared, history_action="refit_archive_load", history_label=f"Load Archive {role.title()}",
                geometry_layers=layers, active_geometry_layer_id=layers[-1].layer_id,
                morph_session_state=morph, require_reversible_history=True,
            )
        finally:
            try:
                service.dispose_morph_session_state(morph)
            except RuntimeError:
                service.defer_morph_session_state_disposal(morph)
        authoring.max_state_document_bytes = max(authoring.max_state_document_bytes, admitted)
        reason = str(args.get("_archive_material_reason") or "")
        if reason:
            authoring.texture_unavailable_reason = f"{entry.path}: {reason}"
        return {"session_id": view.session_id, "loaded_parts": indices, "role": role,
                "archive_path": entry.path, "material_warning": reason}


def assign_loaded_refit_body(authoring, indices=None):
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(session_id)
    with session.export_lock:
        service._require_baked_morph_definition_edit(session)
        state = service.cached_morph_state_from_runtime(session_id)
        if state.refit.garment_submesh_indices:
            raise ValueError("Clear Refit before changing the body")
        if indices is None:
            context = session.archive_refit_context
            indices = context.assets[0].part_indices if context is not None else tuple(
                range(len(session.working_mesh.submeshes))
            )
        mesh = service.working_mesh(session_id, clone=True)
        prepared = service.prepare_working_mesh_replacement(session_id, mesh)
        morph = stage_refit_morph_runtime(service, session_id, mesh, driver_indices=indices)
        try:
            return service.commit_prepared_working_mesh_replacement(
                prepared, history_action="refit_set_driver", history_label="Set Refit Body",
                morph_session_state=morph, require_reversible_history=True,
            )
        finally:
            try:
                service.dispose_morph_session_state(morph)
            except RuntimeError:
                service.defer_morph_session_state_disposal(morph)


def run_refit_driver_command(authoring, command, args):
    if command == "refit_use_loaded_body":
        return assign_loaded_refit_body(authoring)
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    indices = tuple(args.get("submesh_indices", ()) or ())
    cache = service._morph_sessions.get(session_id)
    if cache is None or cache.profile is None:
        return assign_loaded_refit_body(authoring, indices)
    return service.set_refit_driver(session_id, indices)


def stage_archive_refit_materials(authoring, mesh, context, stop_event):
    """Prepare hashed DDS and presentation references before the geometry commit."""
    from cdmw.services.mesh_rust_authoring import (
        _RustMaterialSynthesisState, _atomic_write_payload, _mesh_material_presentations,
        _mesh_texture_payloads, _mesh_lods, _canonical_json_bytes, _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
    )

    previous = authoring.shadow_service._session(authoring.shadow_session_id).archive_refit_context
    previous_key = previous.context_id if previous is not None else "base"
    retained = authoring.archive_refit_material_cache[previous_key]
    # Archive append preserves every existing Part and its read-only material.
    # Reuse the owned DDS references (including Undo generations), and compile
    # only the newly appended asset's editable LOD instead of the whole scene.
    asset = context.assets[-1]
    incoming = copy.copy(mesh)
    incoming.path = asset.entry.path
    incoming.submeshes = [mesh.submeshes[index] for index in asset.part_indices]
    incoming.lod_levels = [incoming.submeshes]
    synthesis = _RustMaterialSynthesisState()
    added_textures = _mesh_texture_payloads(
        authoring.root, incoming, expected_root_identity=authoring.root_identity,
        stop_event=stop_event, synthesis_state=synthesis,
    )
    lod_count = len(_mesh_lods(mesh))
    for texture in added_textures:
        local_indices = texture["material_indices_by_lod"][0]
        texture["material_indices_by_lod"] = [
            [asset.part_indices[index] for index in local_indices],
            *([] for _ in range(lod_count - 1)),
        ]
    # The cheap presentation translator must see the combined Part table: it
    # resolves both explicit material slots and slots derived from Part indices.
    overrides = {(lod, asset.part_indices[index]): value
                 for (lod, index), value in synthesis.presentation_overrides.items()}
    added_presentations = [row for row in _mesh_material_presentations(mesh, generated_overrides=overrides)
                           if row["lod_index"] == 0 and row["material_index"] in asset.part_indices]
    textures = [*retained["textures"], *added_textures]
    authoring.archive_refit_material_cache[context.context_id] = {
        "key": context.context_id, "textures": textures,
        "material_presentations": [*retained["material_presentations"], *added_presentations],
        "reason": "" if textures else "No readable archive preview textures were resolved for these meshes.",
    }
    for key, payload in authoring.archive_refit_material_cache.items():
        if key in authoring.archive_refit_material_references:
            continue
        authoring._raise_if_cancelled(stop_event)
        if len(_canonical_json_bytes(payload)) > _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES:
            raise ValueError("Archive Refit material metadata exceeds the 16 MiB session limit")
        authoring.archive_refit_material_references[key] = _atomic_write_payload(
            authoring.root, f"material-state-{key}.json", payload,
            data_type="mesh_materials_json", element_count=1,
            expected_root_identity=authoring.root_identity,
        )
