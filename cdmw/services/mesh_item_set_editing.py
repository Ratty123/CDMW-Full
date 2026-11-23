"""Compose an editable set, then return each part to its captured PAC owner."""
from __future__ import annotations

from cdmw.domain.archives.item_sets import MAX_SET_FILES

import copy
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
import hashlib
import threading
import weakref
from pathlib import Path
from typing import NamedTuple

from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.services.mesh_asset_context import (
    ASSET_ATTRIBUTE, PART_ATTRIBUTE, ORIGIN_ATTRIBUTE, MeshAsset, MeshAssetContext,
    is_item_set, item_set_bindings,
)

# Set pieces prepared side by side (PAC parse, then the piece's Preview Core
# job). Four keeps a five-file set's parses in flight without oversubscribing.
ITEM_SET_PREPARATION_WORKERS = 4


#: Milliseconds per step of the last set preparation, for the runtime record (P4 V4).
LAST_ITEM_SET_PREPARATION_MS: dict[str, float | str] = {}


def item_set_material_cache(session_root: Path) -> Path:
    """Where a set's pieces run their Preview Core jobs (P4 V6).

    Browse's own Preview Core cache when the session lives in the workspace
    cache, so a piece reuses the textures Browse decoded for the set and its
    packages; a cache of the sessions' own otherwise (sessions in temp).
    """

    return preview_core_job_cache_root(Path(session_root).parent)


def preview_core_job_cache_root(sessions: Path) -> Path:
    """The Preview Core cache for jobs the editor runs, given its sessions folder."""

    from cdmw.services.cache_layout import runtime_cache_layout

    sessions = Path(sessions)
    if sessions.name == "mesh_editor_sessions":
        native = runtime_cache_layout(sessions.parent).native_preview_root
        if native.is_dir():
            return native
    return sessions / "item-set-native-cache"


_HEAD_COMPANION_CACHE_LOCK = threading.Lock()
_HEAD_COMPANION_CACHES: dict[int, tuple[dict, threading.Lock]] = {}

_BROWSE_SET_MATERIAL_PACKAGE_LOCK = threading.Lock()
_BROWSE_SET_MATERIAL_PACKAGES: dict[int, dict[str, str]] = {}
_BROWSE_SET_MATERIAL_FINALIZERS: dict[int, weakref.finalize] = {}


def _drop_browse_set_packages_for_service_id(service_id: int) -> None:
    with _BROWSE_SET_MATERIAL_PACKAGE_LOCK:
        _BROWSE_SET_MATERIAL_PACKAGES.pop(service_id, None)
        _BROWSE_SET_MATERIAL_FINALIZERS.pop(service_id, None)


def register_item_set_browse_material_package(
    service: object,
    session_id: str,
    package_path: Path | str | None,
) -> None:
    """Attach (or clear) Browse's conserved set material package for an open edit session."""

    path_text = str(package_path or "").strip()
    key = str(session_id or "")
    if service is None or not key:
        return
    service_id = id(service)
    with _BROWSE_SET_MATERIAL_PACKAGE_LOCK:
        entries = _BROWSE_SET_MATERIAL_PACKAGES.get(service_id)
        if path_text:
            if entries is None:
                entries = {}
                _BROWSE_SET_MATERIAL_PACKAGES[service_id] = entries
                try:
                    _BROWSE_SET_MATERIAL_FINALIZERS[service_id] = weakref.finalize(
                        service,
                        _drop_browse_set_packages_for_service_id,
                        service_id,
                    )
                except TypeError:
                    pass
            entries[key] = path_text
        elif entries is not None:
            entries.pop(key, None)
            if not entries:
                _BROWSE_SET_MATERIAL_PACKAGES.pop(service_id, None)
                finalizer = _BROWSE_SET_MATERIAL_FINALIZERS.pop(service_id, None)
                if finalizer is not None:
                    finalizer.detach()


def lookup_item_set_browse_material_package(service: object, session_id: str) -> str:
    """Return Browse's registered set material package path for ``(service, session_id)``."""

    key = str(session_id or "")
    if service is None or not key:
        return ""
    with _BROWSE_SET_MATERIAL_PACKAGE_LOCK:
        entries = _BROWSE_SET_MATERIAL_PACKAGES.get(id(service))
        return entries.get(key, "") if entries is not None else ""


def _set_head_companion_cache(contexts: object) -> tuple[dict, threading.Lock]:
    cache = ({}, threading.Lock())
    with _HEAD_COMPANION_CACHE_LOCK:
        _HEAD_COMPANION_CACHES[id(contexts)] = cache
    return cache


def _clear_head_companion_cache(contexts: object) -> None:
    with _HEAD_COMPANION_CACHE_LOCK:
        _HEAD_COMPANION_CACHES.pop(id(contexts), None)


def head_companion_appearance(contexts, context, source, stop_event):
    """The head's own shape for a set piece that a head in the same set declares.

    A head's eyes and teeth are shared PACs posed by the head's skeleton
    variation, not by one of their own. Each piece otherwise resolves its own
    appearance, so the head opens reshaped while its eyes stay at their source
    rig's pose inside the skull. Returns None when no head in the set declares
    the piece, or its shape cannot be applied; the piece keeps its own then.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_mesh_appearance import apply_archive_mesh_appearance
    from cdmw.core.skeleton_resolver import resolve_skeleton_descriptor_for_model
    from cdmw.workers.archive_preview_native import native_preview_model_property_indices

    def key(path):
        return str(path or "").replace("\\", "/").casefold()

    with _HEAD_COMPANION_CACHE_LOCK:
        shared = _HEAD_COMPANION_CACHES.get(id(contexts))
    head_cache, head_cache_lock = shared if shared is not None else (None, None)

    piece = context.selected_entry
    read = lambda candidate: read_archive_entry_data(candidate, stop_event=stop_event)[0]
    for head_context in contexts:
        head = head_context.selected_entry
        if head_context is context or "/head/head/" not in key(head.path):
            continue
        cache_key = getattr(head, "identity", key(head.path))
        declared = None
        if head_cache is not None and head_cache_lock is not None:
            with head_cache_lock:
                declared = head_cache.get(("declared", cache_key))
        if declared is None:
            stem = Path(head.path).stem.casefold()
            prefabs = tuple(entry for entry in head_context.entries
                            if entry.extension.casefold() == ".prefab" and Path(entry.path).stem.casefold() == stem)
            declared = native_preview_model_property_indices(prefabs, stop_event)
            if head_cache is not None and head_cache_lock is not None:
                with head_cache_lock:
                    head_cache[("declared", cache_key)] = declared
        if key(head.path) not in declared or key(piece.path) not in declared:
            continue
        paths = {**context.entries_by_normalized_path, **head_context.entries_by_normalized_path}
        basenames = {**context.entries_by_basename, **head_context.entries_by_basename}
        resolution = None
        if head_cache is not None and head_cache_lock is not None:
            with head_cache_lock:
                resolution = head_cache.get(("resolution", cache_key))
        if resolution is None:
            resolution = resolve_skeleton_descriptor_for_model(head, head_context.entries,
                archive_entries_by_normalized_path=paths, archive_entries_by_basename=basenames, read_entry_data=read)
            if head_cache is not None and head_cache_lock is not None:
                with head_cache_lock:
                    head_cache[("resolution", cache_key)] = resolution
        descriptor = resolution.skeleton_descriptor_entry or resolution.descriptor_entry
        if descriptor is None or resolution.skeleton_variation_entry is None:
            continue
        entries = {entry.identity: entry for entry in (*head_context.entries, *context.entries)}
        try:
            shaped, _notes = apply_archive_mesh_appearance(piece, source.mesh, source.original_data,
                archive_entries_by_normalized_path=paths, archive_entries_by_basename=basenames,
                context_entries=tuple(entries.values()), authored_descriptor=descriptor, stop_event=stop_event)
        except ValueError:
            return None
        return getattr(shaped, "_cdmw_neutral_appearance", None)
    return None


class PreparedItemSet(NamedTuple):
    mesh: object
    context: object
    #: The set's files that are references, not edited (with the primary first), or ().
    references: tuple
    bounded_references: dict
    materials: object
    #: Which files open read-only and why, said before the editor shows ("" when none).
    budget_notice: str = ""


def item_set_budget_notice(contexts, bounded_references, reason: str = "") -> str:
    """Which files open read-only and why, or "" when every file is editable (P5).

    The status line translates it.
    """

    if not bounded_references:
        return ""
    names = ", ".join(context.selected_entry.basename for context in contexts
                      if context.selected_entry.identity in bounded_references)
    if reason == "geometry":
        return (f"Read-only in this session, with reduced detail: {names}. The files you opened have more geometry "
                "together than one Mesh Editor session holds; open fewer at once to edit these.")
    if reason == "textures":
        return (f"Read-only in this session, with reduced detail: {names}. The files you opened have more texture "
                "data together than one Mesh Editor session holds; open fewer at once to edit these.")
    return (f"Read-only in this session, with reduced detail: {names}. The files you opened are larger together "
            "than one Mesh Editor session holds; open fewer at once to edit these.")


def prepare_editable_item_set(
    service,
    session_id,
    material_mesh,
    contexts,
    stop_event,
    progress,
    root,
    root_identity,
    *,
    browse_material_package_path: Path | str | None = None,
):
    """Called only by the existing cancellable session preparation worker."""
    import time as _time

    timings: dict[str, float | str] = {}
    started = _time.perf_counter()
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.mesh_item_set_budget import pop_budget_neutral_meshes, prepare_item_set_budget
    from cdmw.services.mesh_preview_material_source import (
        bind_item_set_piece_from_preview_core_package,
        load_preview_core_set_package,
        prepare_item_set_material_source,
    )
    from cdmw.workers.mesh_archive_refit_worker import attach_archive_refit_materials, prepare_archive_refit_source

    stop_event = stop_event or threading.Event()
    primary = service.capture_export_snapshot(session_id, stop_event=stop_event)
    if (not 1 <= len(contexts) <= MAX_SET_FILES or contexts[0].selected_entry.path.casefold() != primary.mesh.path.casefold()
            or len({context.selected_entry.identity for context in contexts}) != len(contexts)
            or (contexts[0].selected_entry.prepared_sha256 and contexts[0].selected_entry.prepared_sha256.casefold()
                != hashlib.sha256(primary.original_data).hexdigest())):
        raise ValueError("Item set dependencies do not match the selected mesh")
    for name in ("interchange_skeleton", "interchange_bone_palette"):
        if hasattr(primary.mesh, name):
            setattr(material_mesh, name, getattr(primary.mesh, name))
    setattr(material_mesh, "_cdmw_item_set_direct_native_materials", True)
    primary = replace(primary, mesh=material_mesh)
    material_cache = item_set_material_cache(Path(root))
    package_started = _time.perf_counter()
    resolved_browse_package = (
        str(browse_material_package_path or "").strip()
        or lookup_item_set_browse_material_package(service, session_id)
    )
    browse_set_package = (
        load_preview_core_set_package(
            resolved_browse_package,
            cache_root=material_cache,
            stop_event=stop_event,
        )
        if resolved_browse_package
        else None
    )
    if browse_set_package is not None:
        timings["browse_package_load_ms"] = round((_time.perf_counter() - package_started) * 1000.0, 1)
    # Where each file's layers came from, for the open's runtime record: Browse's set
    # package (no job), the file's own Preview Core job, or neither.
    timings["browse_package_registered"] = int(bool(resolved_browse_package))
    timings["browse_package_loaded"] = int(browse_set_package is not None)
    _set_head_companion_cache(contexts)

    def record_source(name, from_browse, native_lease):
        timings[f"piece_layers:{name}"] = "browse" if from_browse else ("job" if native_lease is not None else "none")

    def prepare_primary():
        native_lease = (
            bind_item_set_piece_from_preview_core_package(
                material_mesh, contexts[0], browse_set_package, stop_event,
            )
            if browse_set_package is not None
            else None
        )
        from_browse = native_lease is not None
        if native_lease is None:
            native_lease = prepare_item_set_material_source(material_mesh, contexts[0], material_cache, stop_event)
        record_source(contexts[0].selected_entry.basename, from_browse, native_lease)
        if native_lease is None and not any(
            getattr(part, "preview_material_texture_inputs", ()) for part in material_mesh.submeshes
        ):
            # Fallback only when Preview Core did not bind the primary piece and no
            # pre-resolved materials were attached (e.g. skipped upfront worker).
            try:
                fallback_lease, _ = attach_archive_refit_materials(
                    contexts[0].selected_entry, contexts[0], material_mesh, stop_event,
                )
                return fallback_lease
            except Exception:
                return None
        return native_lease

    def prepare_piece(context):
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        piece_started = _time.perf_counter()
        prepared = prepare_archive_refit_source({"_archive_entry": context.selected_entry,
                                                "_archive_dependencies": context,
                                                "_skip_materials": True}, stop_event)
        source = prepared["_archive_snapshot"]
        setattr(source.mesh, "_cdmw_item_set_direct_native_materials", True)
        parsed = _time.perf_counter()
        native_lease = (
            bind_item_set_piece_from_preview_core_package(
                source.mesh, context, browse_set_package, stop_event,
            )
            if browse_set_package is not None
            else None
        )
        from_browse = native_lease is not None
        if native_lease is None:
            native_lease = prepare_item_set_material_source(source.mesh, context, material_cache, stop_event)
        record_source(context.selected_entry.basename, from_browse, native_lease)
        preview_lease = prepared.get("_archive_preview_lease")
        if native_lease is None and prepared.get("_archive_materials_skipped"):
            preview_lease, _ = attach_archive_refit_materials(
                context.selected_entry, context, source.mesh, stop_event,
                physics_profile_context=prepared.get("_archive_physics_profile_context"),
            )
        name = context.selected_entry.basename
        timings[f"piece_parse_ms:{name}"] = round((parsed - piece_started) * 1000.0, 1)
        timings[f"piece_material_ms:{name}"] = round((_time.perf_counter() - parsed) * 1000.0, 1)
        leases = (preview_lease, native_lease)
        appearance = (head_companion_appearance(contexts, context, source, stop_event)
                      or prepared.get("_archive_neutral_appearance"))
        return (context.selected_entry, source, appearance, leases, context)

    progress("Preparing editable item set...")
    # Each piece loads into its own mesh service and binds from Browse's set
    # package when present (or runs its own Preview Core job on fallback).
    # Preparing them side by side overlaps parsing and material binding; results
    # keep the set's order, and a failure surfaces after the others have finished;
    # their leases release themselves when dropped, as before.
    workers = max(1, min(ITEM_SET_PREPARATION_WORKERS, len(contexts)))
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cdmw-item-set") as pool:
            primary_future = pool.submit(prepare_primary)
            piece_futures = [pool.submit(prepare_piece, context) for context in contexts[1:]]
            wait([primary_future, *piece_futures])
    finally:
        _clear_head_companion_cache(contexts)
        if browse_set_package is not None:
            release = getattr(browse_set_package.lease, "release", None)
            if callable(release):
                release()
    primary_lease = primary_future.result()
    timings["pieces_ms"] = round((_time.perf_counter() - started) * 1000.0, 1)
    sources = [(contexts[0].selected_entry, primary, service._session(session_id).neutral_appearance, primary_lease, contexts[0])]
    sources.extend(future.result() for future in piece_futures)
    raise_if_cancelled(stop_event, "Item set loading cancelled")
    progress("Preparing material textures for Mesh Editor...")
    budget_started = _time.perf_counter()
    budget = prepare_item_set_budget(sources, root, root_identity, stop_event)
    neutral_meshes = pop_budget_neutral_meshes(id(sources))
    admitted, bounded_references, materials = budget.admitted, budget.references, budget.materials
    notice = item_set_budget_notice(contexts, bounded_references, budget.reason)
    if notice:
        progress(notice)  # while the set prepares, before the editor shows
    timings["budget_ms"] = round((_time.perf_counter() - budget_started) * 1000.0, 1)
    references = [contexts[0]]
    for index, context in enumerate(contexts[1:], 1):
        if index not in admitted:
            references.append(context)
    raise_if_cancelled(stop_event, "Item set loading cancelled")
    compose_started = _time.perf_counter()
    admitted_sources = [source for index, source in enumerate(sources) if index in admitted]
    admitted_neutral = (
        [neutral_meshes.get(index) for index in range(len(sources)) if index in admitted]
        if neutral_meshes else None
    )
    mesh, context = compose_item_set(admitted_sources, pre_neutralized=admitted_neutral)
    timings["compose_ms"] = round((_time.perf_counter() - compose_started) * 1000.0, 1)
    LAST_ITEM_SET_PREPARATION_MS.clear()
    LAST_ITEM_SET_PREPARATION_MS.update(timings)
    return PreparedItemSet(mesh, context, tuple(references) if len(references) > 1 else (), bounded_references,
                           materials, notice)


def compose_item_set(sources, *, pre_neutralized=None):
    """Each row supplies (entry, immutable snapshot, appearance, material lease)."""
    from cdmw.services.mesh_archive_refit import _clone

    combined = None
    assets = []
    for source_index, (entry, source, appearance, lease, *dependencies) in enumerate(sources):
        if not source.original_data or not source.mesh.submeshes or source.replacement_state is not None:
            raise ValueError(f"Item set needs an original game mesh: {entry.basename}")
        if assets and entry.identity in {asset.entry.identity for asset in assets}:
            raise ValueError("Item set contains duplicate source files")
        reused = (
            pre_neutralized[source_index]
            if pre_neutralized is not None and source_index < len(pre_neutralized)
            else None
        )
        if reused is not None and appearance is not None:
            mesh = reused
        else:
            # The clone skips the bound Preview Core material sources and gets them
            # back by part (P4 V4): they were most of the clone's JSON work.
            from cdmw.services.mesh_preview_material_source import (
                restore_preview_core_sources, set_aside_preview_core_sources,
            )

            set_aside = set_aside_preview_core_sources(source.mesh)
            try:
                mesh = appearance.to_neutral(source.mesh) if appearance is not None else _clone(source.mesh)
            finally:
                originals = list(source.mesh.submeshes)
                copies = list(mesh.submeshes) if "mesh" in locals() else []
                onto = ({id(original): copy_ for original, copy_ in zip(originals, copies)}
                        if len(originals) == len(copies) else None)
                restore_preview_core_sources(set_aside, onto=onto)
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
