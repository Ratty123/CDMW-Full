"""Prepare archive geometry, rig and material context on the protocol worker."""

from types import SimpleNamespace
from collections import OrderedDict
import copy
import threading

from PySide6.QtCore import Qt

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_archive_refit import ArchiveRefitPreviewLease
from cdmw.services.mesh_rust_authoring import (
    _RUST_PREVIEW_MATERIAL_CONTEXT_ATTR, _prepare_shadow_mesh_materials,
    prime_rust_mesh_preview_context,
)
from cdmw.workers.mesh_editor_aux_workers import (
    MeshArchiveMaterialContextWorker, MeshArchiveSessionLoadWorker,
)


# Bounded geometry cache for the immutable character context. Material leases
# belong to each preparation; cached neutral fitting geometry needs no DDS lease.
_hair_references = OrderedDict()
_hair_reference_lock = threading.Lock()


def prepare_hair_reference_source(args, stop_event):
    generation = args.get("_hair_context_identity")
    if not generation:
        return _prepare_hair_geometry_source(args, stop_event)
    entry = args["_archive_entry"]
    descriptors = args.get("_hair_authored_descriptors")
    authored = descriptors is not None and entry.path.casefold() in descriptors
    descriptor = descriptors.get(entry.path.casefold()) if authored else None
    key = (tuple(generation), entry.identity, descriptor.identity if descriptor is not None else None, authored)
    with _hair_reference_lock:
        cached = _hair_references.get(key)
        if cached is not None:
            _hair_references.move_to_end(key)
    raise_if_cancelled(stop_event, "Hair reference loading cancelled")
    if cached is not None:
        restored = copy.deepcopy(cached[0])
        raise_if_cancelled(stop_event, "Hair reference loading cancelled")
        return {**args, **restored, "_archive_preview_lease": None}
    prepared = _prepare_hair_geometry_source(args, stop_event)
    try:
        raise_if_cancelled(stop_event, "Hair reference loading cancelled")
        retained = {field: prepared[field] for field in (
            "_archive_snapshot", "_archive_neutral_appearance", "_archive_appearance_warning", "_archive_material_reason")}
        retained["_archive_skeleton"] = prepared.get("_archive_skeleton")
        # A conservative per-row bound avoids recursively walking millions of
        # scalar objects just to budget this known, geometry-only cache record.
        snapshot = prepared["_archive_snapshot"]
        parts = {id(part): part for part in snapshot.mesh.submeshes}
        for lod in getattr(snapshot.mesh, "lod_levels", ()):
            parts.update((id(part), part) for part in lod)
        size = len(snapshot.original_data) * 2 + sum(
            len(part.vertices) * 2048 + len(part.faces) * 128 for part in parts.values())
        size += len(getattr(prepared.get("_archive_skeleton"), "bones", ())) * 4096
        if size <= 64 * 1024 * 1024:
            saved = copy.deepcopy(retained)
            with _hair_reference_lock:
                raise_if_cancelled(stop_event, "Hair reference loading cancelled")
                for old in tuple(_hair_references):
                    if old[0] != key[0]:
                        _hair_references.pop(old)
                _hair_references[key] = (saved, size)
                while len(_hair_references) > 4 or sum(row[1] for row in _hair_references.values()) > 128 * 1024 * 1024:
                    _hair_references.popitem(last=False)
        else:
            raise_if_cancelled(stop_event, "Hair reference loading cancelled")
        return prepared
    except BaseException:
        # This lease has not been handed to a session. Release it even while an
        # exception traceback still retains the prepared snapshot and our frame.
        owner = prepared.get("_archive_preview_lease")
        if owner is not None and owner.lease is not None:
            try:
                owner.lease.release()
                owner.lease = None
            except Exception:
                pass  # The lease destructor can retry without hiding the error.
        raise


def _prepare_hair_geometry_source(args, stop_event):
    """Load the fitting mannequin without editor sessions or material decoding."""
    from cdmw.services.mesh_refit_loading import MAX_REFIT_INPUT_BYTES
    from cdmw.services.archive_read_service import read_archive_entry_data
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
    from cdmw.core.archive_mesh_appearance import apply_archive_mesh_appearance

    entry = args["_archive_entry"]
    dependencies = args["_archive_dependencies"]
    if not 0 < max(int(entry.orig_size), int(entry.comp_size), int(entry.prepared_size or 0)) <= MAX_REFIT_INPUT_BYTES:
        raise ValueError("Hair reference must be a non-empty mesh no larger than 256 MiB")
    if entry.prepared_path is not None and entry.prepared_path.stat().st_size > MAX_REFIT_INPUT_BYTES:
        raise ValueError("Prepared hair reference exceeds 256 MiB")
    if dependencies.entry_matching(entry) is None:
        raise ValueError("The selected archive mesh is outside its prepared dependency context")
    raise_if_cancelled(stop_event, "Hair reference loading cancelled")
    payloads = {}
    def read(candidate):
        if candidate.identity not in payloads:
            payloads[candidate.identity] = read_archive_entry_data(candidate, stop_event=stop_event)[0]
        return payloads[candidate.identity]
    payload = read(entry)
    mesh = parse_mesh(payload, entry.path)
    raise_if_cancelled(stop_event, "Hair reference loading cancelled")
    skeleton_entry, _report = resolve_skeleton_for_model(entry,
        archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
        archive_entries_by_basename=dependencies.entries_by_basename,
        pac_data=payload, read_entry_data=read)
    skeleton = parse_pab(read(skeleton_entry), skeleton_entry.path) if skeleton_entry is not None else None
    descriptors = args.get("_hair_authored_descriptors")
    authored = descriptors is not None and entry.path.casefold() in descriptors
    descriptor = descriptors.get(entry.path.casefold()) if authored else None
    appearance = None
    # A mounted component without a PABC is authoritative too: do not apply
    # another character's basename-matched appearance to a shared body.
    if not authored or descriptor is not None:
        transformed, _notes = apply_archive_mesh_appearance(entry, mesh, payload,
            archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
            archive_entries_by_basename=dependencies.entries_by_basename,
            context_entries=dependencies.entries, authored_descriptor=descriptor,
            skeleton=skeleton, stop_event=stop_event)
        appearance = getattr(transformed, "_cdmw_neutral_appearance", None)
    raise_if_cancelled(stop_event, "Hair reference loading cancelled")
    return {**args, "_archive_snapshot": SimpleNamespace(mesh=mesh, original_data=payload),
        "_archive_skeleton": skeleton, "_archive_neutral_appearance": appearance,
        "_archive_preview_lease": None, "_archive_material_reason": "", "_archive_appearance_warning": ""}


def _run(worker, signal, stop_event):
    results, failures = [], []
    worker.stop_event = stop_event
    signal.connect(lambda _request, result: results.append(result), Qt.DirectConnection)
    worker.error.connect(lambda _request, message: failures.append(message), Qt.DirectConnection)
    worker.run()
    if stop_event.is_set():
        for result in results:
            if hasattr(result, "service"):
                result.service.close_edit_session(result.view.session_id, force_without_saving=True)
            elif hasattr(result, "release"):
                result.release()
    raise_if_cancelled(stop_event, "Archive Refit loading cancelled")
    if failures or not results:
        raise RuntimeError(failures[0] if failures else "Archive Refit source preparation returned no mesh")
    return results[0]


def prepare_hair_editor_session(entry, dependencies, args, draft_root, stop_event):
    """Prepare target, mounted references and materials without replacing live work."""
    from dataclasses import replace
    from cdmw.services.mesh_rust_hair import prepare_hair_setup, validate_hair_donor
    loader = MeshArchiveSessionLoadWorker(1, entry, draft_root=draft_root,
        archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
        archive_entries_by_basename=dependencies.entries_by_basename)
    loaded = _run(loader, loader.loaded, stop_event)
    leases = []
    try:
        validate_hair_donor(loaded.mesh, args["character"])
        prepared = prepare_hair_reference_source(args, stop_event)
        leases.append(prepared.get("_archive_preview_lease"))
        body = prepare_hair_reference_source({**args, "_archive_entry": args["_body_archive_entry"],
            "_archive_dependencies": args["_body_archive_dependencies"]}, stop_event)
        leases.append(body.get("_archive_preview_lease"))
        prepared.update(_body_snapshot=body["_archive_snapshot"],
            _body_neutral_appearance=body["_archive_neutral_appearance"], _body_skeleton=body.get("_archive_skeleton"))
        prepared["_prepared_head_details"] = []
        for detail_entry, scale in args.get("_head_details", ()):
            detail = prepare_hair_reference_source({**args, "_archive_entry": detail_entry}, stop_event)
            leases.append(detail.get("_archive_preview_lease"))
            detail["_scale"] = scale
            prepared["_prepared_head_details"].append(detail)
        prepared.update(_target_entry=entry, _target_dependencies=dependencies)
        session = loaded.service._session(loaded.view.session_id)
        prepare_hair_setup(loaded.service, session.session_id, prepared, stop_event,
            neutral_appearance=session.neutral_appearance, neutral_coordinates=False)
        raise_if_cancelled(stop_event, "Hair setup cancelled")
        return replace(loaded, view=loaded.service.session_view(session.session_id), mesh=session.working_mesh)
    except BaseException:
        loaded.service.close_edit_session(loaded.view.session_id, force_without_saving=True)
        raise
    finally:
        for owner in leases:
            if owner is not None and owner.lease is not None:
                owner.lease.release()
                owner.lease = None


def prepare_archive_refit_source(args, stop_event):
    from cdmw.services.mesh_refit_loading import MAX_REFIT_INPUT_BYTES

    entry = args["_archive_entry"]
    if not 0 < max(int(entry.orig_size), int(entry.comp_size), int(entry.prepared_size or 0)) <= MAX_REFIT_INPUT_BYTES:
        raise ValueError("Archive Refit source must be a non-empty mesh no larger than 256 MiB")
    if entry.prepared_path is not None and entry.prepared_path.stat().st_size > MAX_REFIT_INPUT_BYTES:
        raise ValueError("Prepared archive Refit source exceeds 256 MiB")
    dependencies = args["_archive_dependencies"]
    if dependencies.entry_matching(entry) is None:
        raise ValueError("The selected archive mesh is outside its prepared dependency context")
    loader = MeshArchiveSessionLoadWorker(
        1, entry, archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
        archive_entries_by_basename=dependencies.entries_by_basename,
    )
    loaded = _run(loader, loader.loaded, stop_event)
    try:
        snapshot = loaded.service.capture_export_snapshot(loaded.view.session_id, stop_event=stop_event)
        appearance = loaded.service._session(loaded.view.session_id).neutral_appearance
        materials = MeshArchiveMaterialContextWorker(
            1, entry, entries_by_normalized_path=dependencies.entries_by_normalized_path,
            entries_by_basename=dependencies.entries_by_basename,
        )
        context = _run(materials, materials.context_resolved, stop_event)
        lease = ArchiveRefitPreviewLease(context)
        controller = SimpleNamespace(mesh_service=loaded.service, active_session_id=loaded.view.session_id)
        prime_rust_mesh_preview_context(
            controller, context.preview_model, material_package_path=context.material_package_path,
            target_entry=entry, entries_by_basename=dependencies.entries_by_basename,
        )
        _count, reason = _prepare_shadow_mesh_materials(
            snapshot.mesh, getattr(controller, _RUST_PREVIEW_MATERIAL_CONTEXT_ATTR), "", stop_event,
        )
        raise_if_cancelled(stop_event, "Archive Refit loading cancelled")
        return {**args, "_archive_snapshot": snapshot, "_archive_preview_lease": lease,
                "_archive_skeleton": loaded.source_skeleton,
                "_archive_material_reason": reason, "_archive_neutral_appearance": appearance,
                "_archive_appearance_warning": getattr(loaded, "appearance_warning", "")}
    finally:
        loaded.service.close_edit_session(loaded.view.session_id, force_without_saving=True)
