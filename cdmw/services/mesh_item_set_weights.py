"""Run named weight edits against each PAC's own palette, then commit once."""
from __future__ import annotations

import copy
from dataclasses import replace

from cdmw.domain.mesh import MeshEditSelection
from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.services.mesh_asset_context import ORIGIN_ATTRIBUTE, PART_ATTRIBUTE, item_set_bindings


def asset_session(session, asset, mesh, indices):
    local = copy.copy(session)
    local.archive_refit_context = None
    local.base_mesh = copy.copy(asset.source.mesh)
    origins = {asset.source_part_id(i): part for i, part in enumerate(asset.source.mesh.submeshes)}
    local.base_mesh.submeshes = [origins[getattr(mesh.submeshes[i], ORIGIN_ATTRIBUTE)] for i in indices]
    local.base_mesh.lod_levels = []
    local.base_mesh_is_original_parse = True
    local.source_coordinate_base_mesh = local.base_mesh
    local.working_mesh = copy.copy(asset.source.mesh)
    local.working_mesh.submeshes = [mesh.submeshes[i] for i in indices]
    local.working_mesh.lod_levels = []
    local.original_data = asset.source.original_data
    local.skeleton = getattr(asset.source.mesh, "interchange_skeleton", None)
    return local


def item_set_weight_capability(session):
    from cdmw.services.mesh_rust_authoring import _rust_skin_weight_capability, _RustSkinWeightCapability

    mesh = session.working_mesh
    context = session.archive_refit_context
    bindings = item_set_bindings(mesh, context)
    eligible, first = [], None
    for asset in context.assets:
        indices = bindings[asset.asset_id]
        capability = _rust_skin_weight_capability(asset_session(session, asset, mesh, indices))
        if first is None:
            first = capability
        if capability.enabled:
            eligible.extend(indices[index] for index in capability.eligible_submesh_indices)
    if not eligible:
        return _RustSkinWeightCapability(False, first.reason if first else "Item set has no editable skin weights")
    return replace(first, enabled=True, reason="Exact PAC LOD 0 skin-weight replacement is available.",
                   eligible_submesh_indices=tuple(eligible))


def item_set_weight_display(session, skeleton_state, bone_index):
    """Resolve display rows using the same source palettes as weight commands."""
    from cdmw.services.mesh_rust_authoring import _rust_skin_weight_capability
    from cdmw.services.mesh_rust_rig import selected_bone_influence, MAX_INFLUENCE_VERTICES

    mesh, context = session.working_mesh, session.archive_refit_context
    bindings = item_set_bindings(mesh, context)
    primary_bones = tuple(getattr(session.skeleton, "bones", ()) or ())
    primary = {(bone.name_hash, bone.name): bone.index for bone in primary_bones}
    chosen = next((bone for bone in primary_bones if bone.index == bone_index), None)
    result = {"bone_index": bone_index, "available": chosen is not None,
              "reason": "" if chosen is not None else "Choose a bone to inspect its influence.",
              "vertex_count": 0, "parts": []}
    for asset in context.assets:
        indices = bindings[asset.asset_id]
        local = asset_session(session, asset, mesh, indices)
        capability = _rust_skin_weight_capability(local)
        bones = tuple(getattr(local.skeleton, "bones", ()) or ())
        slot_map = {slot: primary.get((bones[ordinal].name_hash, bones[ordinal].name))
                    for slot, ordinal in enumerate(capability.palette) if 0 <= ordinal < len(bones)}
        for row in skeleton_state["selected_vertex_weights"]:
            if row["submesh_index"] not in indices:
                continue
            slots = row["influence_slots"]
            resolved = bool(slots) and all(slot_map.get(slot) is not None for slot, _ in slots)
            row["influences_resolved"] = resolved
            row["influences"] = [[slot_map[slot], weight] for slot, weight in slots] if resolved else []
            row["influence_labels"] = [] if resolved else [[f"Slot {slot}", weight] for slot, weight in slots]
            row["selected_bone_weight"] = sum(weight for slot, weight in slots if slot_map.get(slot) == bone_index)
        if chosen is None:
            continue
        matching = [bone.index for bone in bones if (bone.name_hash, bone.name) == (chosen.name_hash, chosen.name)]
        if not matching:
            continue
        influence = selected_bone_influence(local, matching[0], capability.palette)
        if not influence["available"]:
            result.update(available=False, reason=influence["reason"], vertex_count=0, parts=[])
            break
        result["vertex_count"] += influence["vertex_count"]
        if result["vertex_count"] > MAX_INFLUENCE_VERTICES:
            result.update(available=False, reason="This bone exceeds the weight display limit; no partial influence is shown.",
                          vertex_count=0, parts=[])
            break
        result["parts"].extend({**part, "submesh_index": indices[part["submesh_index"]]} for part in influence["parts"])
    skeleton_state["weight_edit_capability"]["per_asset"] = True
    return result


def edit_item_set_weights(authoring, command, args, selection):
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.mesh_rust_authoring import _selection_payload
    from cdmw.services.mesh_rust_state_cache import RustMeshStateCache

    service, key = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(key)
    candidate = service.working_mesh(key, clone=True)
    context = session.archive_refit_context
    bindings = item_set_bindings(candidate, context)
    selected = set(selection.source_indices) | set(selection.vertex_map())
    if not selected:
        raise ValueError("Select one or more vertices or whole parts before editing skin weights.")
    bones = tuple(getattr(session.skeleton, "bones", ()) or ())
    chosen = next((bone for bone in bones if bone.index == session.selected_bone_index), None)
    operations = list(mesh_edit_operations_from_dicts(session.edit_operations))
    changed = False
    for asset in context.assets:
        indices = bindings[asset.asset_id]
        if not selected.intersection(indices):
            continue
        local = asset_session(session, asset, candidate, indices)
        mesh = copy.deepcopy(local.working_mesh)
        mesh._cdmw_original_data = asset.source.original_data
        temporary = MeshService(max_history=1)
        view = temporary.open_edit_session(mesh, mode="edit", load_layer_project=False)
        try:
            target = temporary._session(view.session_id)
            target.base_mesh = local.base_mesh
            target.source_coordinate_base_mesh = local.base_mesh
            target.base_mesh_is_original_parse = True
            target.original_data = local.original_data
            target.skeleton = local.skeleton
            target.selected_bone_index = -1
            if command == "rig_adjust_weight":
                matches = [bone for bone in getattr(local.skeleton, "bones", ())
                           if chosen is not None and (bone.name_hash, bone.name) == (chosen.name_hash, chosen.name)]
                if len(matches) != 1:
                    raise ValueError(f"Selected bone does not belong to this source rig: {asset.entry.basename}")
                target.selected_bone_index = matches[0].index
            remap = {combined: local for local, combined in enumerate(indices)}
            local_selection = MeshEditSelection.from_maps(
                source_indices=tuple(remap[i] for i in selection.source_indices if i in remap),
                vertices_by_submesh={remap[i]: values for i, values in selection.vertex_map().items() if i in remap})
            proxy = copy.copy(authoring)
            proxy.shadow_service, proxy.shadow_session_id = temporary, view.session_id
            proxy.state_cache = RustMeshStateCache()
            proxy._run_rig_weight_command(command, {**args, "selection": _selection_payload(local_selection)})
            edited = temporary.working_mesh(view.session_id)
            for local_index, combined_index in enumerate(indices):
                before, after = candidate.submeshes[combined_index], edited.submeshes[local_index]
                changed |= before.bone_indices != after.bone_indices or before.bone_weights != after.bone_weights
                before.bone_indices, before.bone_weights = after.bone_indices, after.bone_weights
            for row in mesh_edit_operations_from_dicts(target.edit_operations):
                combined_index = indices[row.submesh_index]
                operations.append(replace(row, submesh_index=combined_index,
                    metadata={**row.metadata, "asset_part_id": getattr(candidate.submeshes[combined_index], PART_ATTRIBUTE)}))
        finally:
            temporary.close_edit_session(view.session_id, force_without_saving=True)
    if not changed:
        return service.session_view(key)
    candidate._cdmw_edit_operations = tuple(operations)
    prepared = service.prepare_working_mesh_replacement(key, candidate, archive_refit_context=context)
    return authoring._commit_morph_preserving_replacement(prepared,
        history_action="adjust_vertex_weights", history_label="Adjust Bone Weight")
