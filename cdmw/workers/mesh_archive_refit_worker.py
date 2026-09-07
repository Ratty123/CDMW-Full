"""Prepare archive geometry, rig and material context on the protocol worker."""

from PySide6.QtCore import Qt

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_archive_refit import ArchiveRefitPreviewLease
from cdmw.services.mesh_rust_authoring import _prepare_shadow_mesh_materials
from cdmw.workers.mesh_editor_aux_workers import (
    MeshArchiveMaterialContextWorker, MeshArchiveSessionLoadWorker,
)


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
        materials = MeshArchiveMaterialContextWorker(
            1, entry, entries_by_normalized_path=dependencies.entries_by_normalized_path,
            entries_by_basename=dependencies.entries_by_basename,
        )
        context = _run(materials, materials.context_resolved, stop_event)
        lease = ArchiveRefitPreviewLease(context)
        _count, reason = _prepare_shadow_mesh_materials(snapshot.mesh, context, "", stop_event)
        raise_if_cancelled(stop_event, "Archive Refit loading cancelled")
        return {**args, "_archive_snapshot": snapshot, "_archive_preview_lease": lease,
                "_archive_material_reason": reason}
    finally:
        loaded.service.close_edit_session(loaded.view.session_id, force_without_saving=True)
