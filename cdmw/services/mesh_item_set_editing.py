"""Compose an editable set, then return each part to its captured PAC owner."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
import hashlib
import threading

from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.services.mesh_asset_context import (
    ASSET_ATTRIBUTE, PART_ATTRIBUTE, ORIGIN_ATTRIBUTE, MeshAsset, MeshAssetContext,
    is_item_set, item_set_bindings,
)

# Set pieces prepared side by side (PAC parse, then the piece's Preview Core
# job). Four keeps a five-file set's parses in flight without oversubscribing.
ITEM_SET_PREPARATION_WORKERS = 4


def prepare_editable_item_set(service, session_id, material_mesh, contexts, stop_event, progress, root, root_identity):
    """Called only by the existing cancellable session preparation worker."""
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.mesh_item_set_budget import prepare_item_set_budget
    from cdmw.services.mesh_preview_material_source import prepare_item_set_material_source
    from cdmw.workers.mesh_archive_refit_worker import prepare_archive_refit_source

    stop_event = stop_event or threading.Event()
    primary = service.capture_export_snapshot(session_id, stop_event=stop_event)
    if (not 1 <= len(contexts) <= 33 or contexts[0].selected_entry.path.casefold() != primary.mesh.path.casefold()
            or len({context.selected_entry.identity for context in contexts}) != len(contexts)
            or (contexts[0].selected_entry.prepared_sha256 and contexts[0].selected_entry.prepared_sha256.casefold()
                != hashlib.sha256(primary.original_data).hexdigest())):
        raise ValueError("Item set dependencies do not match the selected mesh")
    for name in ("interchange_skeleton", "interchange_bone_palette"):
        if hasattr(primary.mesh, name):
            setattr(material_mesh, name, getattr(primary.mesh, name))
    primary = replace(primary, mesh=material_mesh)
    material_cache = root.parent / "item-set-native-cache"

    def prepare_piece(context):
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        prepared = prepare_archive_refit_source({"_archive_entry": context.selected_entry,
                                                "_archive_dependencies": context}, stop_event)
        source = prepared["_archive_snapshot"]
        native_lease = prepare_item_set_material_source(source.mesh, context, material_cache, stop_event)
        leases = (prepared.get("_archive_preview_lease"), native_lease)
        return (context.selected_entry, source, prepared.get("_archive_neutral_appearance"), leases, context)

    progress("Preparing editable item set...")
    # Each piece loads into its own mesh service and runs its own Preview Core
    # job. The service runs one job at a time, so its jobs queue while the other
    # pieces parse; preparing them side by side overlaps the two. Results keep
    # the set's order, and a failure surfaces after the others have finished;
    # their leases release themselves when dropped, as before.
    workers = max(1, min(ITEM_SET_PREPARATION_WORKERS, len(contexts)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cdmw-item-set") as pool:
        primary_future = pool.submit(prepare_item_set_material_source, material_mesh, contexts[0],
                                     material_cache, stop_event)
        piece_futures = [pool.submit(prepare_piece, context) for context in contexts[1:]]
        wait([primary_future, *piece_futures])
    primary_lease = primary_future.result()
    sources = [(contexts[0].selected_entry, primary, service._session(session_id).neutral_appearance, primary_lease, contexts[0])]
    sources.extend(future.result() for future in piece_futures)
    raise_if_cancelled(stop_event, "Item set loading cancelled")
    progress("Preparing material textures for Mesh Editor...")
    admitted, bounded_references, materials = prepare_item_set_budget(sources, root, root_identity, stop_event)
    references = [contexts[0]]
    for index, context in enumerate(contexts[1:], 1):
        if index not in admitted:
            references.append(context)
    raise_if_cancelled(stop_event, "Item set loading cancelled")
    mesh, context = compose_item_set([source for index, source in enumerate(sources) if index in admitted])
    return mesh, context, tuple(references) if len(references) > 1 else (), bounded_references, materials


def compose_item_set(sources):
    """Each row supplies (entry, immutable snapshot, appearance, material lease)."""
    from cdmw.services.mesh_archive_refit import _clone

    combined = None
    assets = []
    for entry, source, appearance, lease, *dependencies in sources:
        if not source.original_data or not source.mesh.submeshes or source.replacement_state is not None:
            raise ValueError(f"Item set needs an original game mesh: {entry.basename}")
        if assets and entry.identity in {asset.entry.identity for asset in assets}:
            raise ValueError("Item set contains duplicate source files")
        mesh = appearance.to_neutral(source.mesh) if appearance is not None else _clone(source.mesh)
        first = len(combined.submeshes) if combined is not None else 0
        asset = MeshAsset(copy.copy(entry), replace(source, archive_refit_context=None),
                          tuple(range(first, first + len(mesh.submeshes))), "editable", lease, appearance,
                          dependencies[0] if dependencies else None)
        for index, part in enumerate(mesh.submeshes):
            setattr(part, ASSET_ATTRIBUTE, asset.asset_id)
            setattr(part, PART_ATTRIBUTE, asset.source_part_id(index))
            setattr(part, ORIGIN_ATTRIBUTE, asset.source_part_id(index))
        assets.append(asset)
        if combined is None:
            combined = mesh
        else:
            combined.submeshes.extend(mesh.submeshes)
            combined.has_bones |= mesh.has_bones
            combined.has_uvs |= mesh.has_uvs
    if combined is None:
        raise ValueError("Item set contains no editable files")
    # Each PAC retains its other LODs in its immutable source; they are never
    # mistaken for parts of the combined LOD0 editing surface.
    combined.lod_levels = []
    combined.active_lod_index = 0
    refresh_mesh_totals(combined)
    context = MeshAssetContext(tuple(assets), neutral_coordinates=True, workflow="item_set")
    item_set_bindings(combined, context)
    return combined, context


def transform_item_set_mesh(mesh, context, *, to_neutral):
    from cdmw.services.mesh_archive_refit import _clone

    bindings = item_set_bindings(mesh, context)
    result = _clone(mesh)
    for asset in context.assets:
        if asset.neutral_appearance is None:
            continue
        indices = bindings[asset.asset_id]
        subset = copy.copy(result)
        subset.submeshes = [result.submeshes[index] for index in indices]
        subset.lod_levels = [subset.submeshes]
        original = copy.copy(asset.source.mesh)
        origins = {asset.source_part_id(i): part for i, part in enumerate(asset.source.mesh.submeshes)}
        original.submeshes = [origins[getattr(part, ORIGIN_ATTRIBUTE)] for part in subset.submeshes]
        original.lod_levels = [original.submeshes]
        converted = (asset.neutral_appearance.to_neutral(subset) if to_neutral
                     else asset.neutral_appearance.to_source(subset, original))
        for index, part in zip(indices, converted.submeshes, strict=True):
            result.submeshes[index] = part
    result.lod_levels = []
    refresh_mesh_totals(result)
    return result


def item_set_snapshots(snapshot):
    from cdmw.services.mesh_archive_refit import _clone

    context = snapshot.archive_refit_context
    bindings = item_set_bindings(snapshot.mesh, context)
    edited = (transform_item_set_mesh(snapshot.mesh, context, to_neutral=False)
              if context.neutral_coordinates else snapshot.mesh)
    components = []
    operations = mesh_edit_operations_from_dicts(snapshot.edit_operations)
    for asset in context.assets:
        mesh = _clone(asset.source.mesh)
        original_parts = mesh.submeshes
        origins = {asset.source_part_id(i): i for i in range(len(original_parts))}
        indices = bindings[asset.asset_id]
        local_parts = []
        mapped_operations = list(mesh_edit_operations_from_dicts(asset.source.edit_operations))
        for combined_index in indices:
            part = copy.deepcopy(edited.submeshes[combined_index])
            origin = origins[getattr(part, ORIGIN_ATTRIBUTE)]
            source = original_parts[origin]
            if (tuple(part.source_bone_palette) != tuple(source.source_bone_palette)
                    or part.source_skin_weight_layout != source.source_skin_weight_layout
                    or bool(part.bone_indices) != bool(source.bone_indices)):
                raise ValueError(f"Part rig differs from its source file: {asset.entry.basename}")
            # Native generations own geometry, not PAC record addresses. Restore
            # each source descriptor by immutable origin, including after reorder.
            for name in ("source_vertex_stride", "source_bbox_min", "source_bbox_extent", "source_lod_count"):
                setattr(part, name, copy.deepcopy(getattr(source, name)))
            identity = getattr(part, PART_ATTRIBUTE)
            if identity == getattr(part, ORIGIN_ATTRIBUTE):
                part.source_descriptor_offset = source.source_descriptor_offset
                part.source_index_offset = source.source_index_offset
                part.source_index_count = source.source_index_count
            else:
                part.source_descriptor_offset = -1
                part.source_index_offset = -1
                part.source_index_count = 0
            for name in ("cdmw_mesh_edit_material_source_submesh_index", "cdmw_mesh_edit_topology_source_submesh_index"):
                if hasattr(part, name):
                    setattr(part, name, origin)
            # Include is export-only. Keep the original part in the draft; the
            # source descriptor still tells the exact writer what is omitted.
            if identity in context.excluded_part_ids:
                continue
            local_index = len(local_parts)
            local_parts.append(part)
            for operation in operations:
                target = operation.metadata.get("asset_part_id")
                if target == identity or (not target and operation.lod_index == 0
                                          and operation.submesh_index == combined_index):
                    mapped_operations.append(replace(operation, submesh_index=local_index, lod_index=0,
                        metadata={**operation.metadata, "asset_part_id": identity}))
        # Entire-file Include off omits its output. Retain a source snapshot for
        # ordered validation/reporting; publication checks inclusion separately.
        if not local_parts:
            mesh = _clone(asset.source.mesh)
            mapped_operations = list(mesh_edit_operations_from_dicts(asset.source.edit_operations))
            inclusion = ()
        else:
            from cdmw.services.mesh_item_set_output import fold_asset_parts
            local_parts, inclusion, mapped_operations = fold_asset_parts(asset, local_parts, mapped_operations)
            mesh.submeshes = local_parts
            mesh.lod_levels = [local_parts, *mesh.lod_levels[1:]] if mesh.lod_levels else []
            # Resident sculpt strokes can leave normals deferred. Complete only
            # those recorded sculpt results, on the isolated source-coordinate
            # snapshot, before the exact writer validates them.
            deferred = {row.submesh_index for row in mapped_operations
                        if row.metadata.get("service_action") == "brush"
                        and 0 <= row.submesh_index < len(local_parts)
                        and len(local_parts[row.submesh_index].normals) != len(local_parts[row.submesh_index].vertices)}
            if deferred:
                from cdmw.modding.mesh_native_normals import apply_native_mesh_recalculate_normals
                if apply_native_mesh_recalculate_normals(mesh, deferred) is None:
                    raise ValueError(f"Cannot finish sculpted normals for source file: {asset.entry.basename}")
        refresh_mesh_totals(mesh)
        components.append((asset.entry, replace(asset.source, mesh=mesh, archive_refit_context=None,
            mesh_revision=snapshot.mesh_revision, native_edit_revision=snapshot.native_edit_revision,
            edit_operations=tuple(mapped_operations), asset_part_inclusion=inclusion)))
    return tuple(components)


def selected_asset_ids(mesh, context, selection):
    item_set_bindings(mesh, context)
    indices = (set(selection.source_indices) | set(selection.vertex_map())
               | set(selection.edge_map()) | set(selection.face_map()))
    if any(index < 0 or index >= len(mesh.submeshes) for index in indices):
        raise ValueError("Item set selection no longer matches its parts")
    return {getattr(mesh.submeshes[index], ASSET_ATTRIBUTE) for index in indices}, indices


def guard_item_set_topology(session, mesh, action, selection, params):
    context = session.archive_refit_context
    owners, indices = selected_asset_ids(mesh, context, selection)
    if action == "paste":
        copied = session.item_set_clipboard_assets
        if len(copied) != 1 or (owners and owners != set(copied)):
            raise ValueError("Cannot paste geometry between source files; select its original file")
    elif len(owners or {asset.asset_id for asset in context.assets}) != 1:
        raise ValueError("Topology edits must stay within one source file")
    if action == "delete":
        bindings = item_set_bindings(mesh, context)
        emptied = set(selection.source_indices)
        if not params.get("delete_parts"):
            for index in indices - emptied:
                part = mesh.submeshes[index]
                faces = set(selection.face_map().get(index, ()))
                vertices = set(selection.vertex_map().get(index, ()))
                edges = {tuple(sorted(edge)) for edge in selection.edge_map().get(index, ())}
                if all(face_index in faces or vertices.intersection(face)
                       or any(tuple(sorted((face[n], face[(n + 1) % 3]))) in edges for n in range(3))
                       for face_index, face in enumerate(part.faces)):
                    emptied.add(index)
        for asset in context.assets:
            if set(bindings[asset.asset_id]).issubset(emptied):
                raise ValueError(f"Cannot delete every part of a source file: {asset.entry.basename}")


def item_set_omitted_assets(snapshot):
    context = snapshot.archive_refit_context
    bindings = item_set_bindings(snapshot.mesh, context)
    return {asset.entry.identity for asset in context.assets
            if all(getattr(snapshot.mesh.submeshes[index], PART_ATTRIBUTE) in context.excluded_part_ids
                   for index in bindings[asset.asset_id])}


def set_item_set_inclusion(service, session_id, part_ids, included):
    session = service._session(session_id)
    with session.export_lock:
        mesh = service.working_mesh(session_id)
        context = session.archive_refit_context
        if not is_item_set(context):
            raise ValueError("No editable item set is open")
        item_set_bindings(mesh, context)
        live = {getattr(part, PART_ATTRIBUTE) for part in mesh.submeshes}
        selected = frozenset(part_ids)
        if not selected or not selected.issubset(live) or type(included) is not bool:
            raise ValueError("Item set inclusion no longer matches its parts")
        service._push_history(session, prefer_native=True, action="item_set_include", label="Include")
        session.undo_stack[-1].restore_archive_refit_context = True
        session.undo_stack[-1].archive_refit_context = context
        excluded = context.excluded_part_ids - selected if included else context.excluded_part_ids | selected
        session.archive_refit_context = replace(context, excluded_part_ids=frozenset(excluded))
        session.revision += 1
        service._schedule_mesh_layer_autosave(session)
