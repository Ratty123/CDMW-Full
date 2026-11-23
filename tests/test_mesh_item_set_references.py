import json
import threading
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_authoring import (RustMeshAuthoringSession, RustMeshCancellationError,
    RustMeshProtocolError, read_owned_payload_reference)
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _Settings, _prepared_dds_entry
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextWorker


def _sources(tmp_path):
    source = _pac_fixture()
    entries = [_prepared_dds_entry(tmp_path, name, source) for name in ("upper.pac", "lower.pac")]
    contexts = tuple(ArchiveWorkflowDependencyContext(entry, (entry,),
        {entry.path: entry}, {entry.basename: (entry,)}, True) for entry in entries)
    mesh = parse_pac(source, entries[0].path)
    mesh._cdmw_original_data = source
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(mesh, mode="edit")
    return source, service, SimpleNamespace(mesh_service=service, active_session_id=view.session_id), contexts


def test_reference_package_keeps_authority_and_export_per_pac(tmp_path, monkeypatch):
    # The owned PAC fixture has geometry but no game material sidecar. Exercise
    # the real archive/session loaders with a resolved, untextured context.
    monkeypatch.setattr(MeshArchiveMaterialContextWorker, "run", lambda worker:
        worker.context_resolved.emit(worker.request_id, SimpleNamespace(
            preview_model=None, material_package_path="", material_package_lease=None)))
    source, service, controller, contexts = _sources(tmp_path)
    session = None
    try:
        session = RustMeshAuthoringSession.create(controller, tmp_path / "session", process_generation=1,
                                                  item_set_contexts=contexts)
        manifest = json.loads(session.manifest_path.read_text())
        assert manifest["item_set_files"] == ["upper.pac", "lower.pac"]
        reference, = manifest["reference_pieces"]
        assert reference["role"] == "reference" and reference["index"] == 1
        assert reference["document"]["path"] == "reference-01.bin"
        assert (session.root / reference["document"]["path"]).is_file()
        with pytest.raises(RustMeshProtocolError):
            read_owned_payload_reference(session.root, reference["document"])
        for owner, key in ((service, controller.active_session_id), (session.shadow_service, session.shadow_session_id)):
            snapshot = owner.capture_export_snapshot(key)
            assert snapshot.mesh.path == "upper.pac"
            assert len(snapshot.mesh.submeshes) == 1
        assert contexts[1].selected_entry.prepared_path.read_bytes() == source
        assert "reference_pieces" not in session.state_payload(include_document=False)
    finally:
        if session is not None:
            session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_cancel_during_reference_preparation_removes_unpublished_session(tmp_path):
    _, service, controller, contexts = _sources(tmp_path)
    stop = threading.Event()
    def progress(message):
        if message == "Preparing reference meshes...":
            stop.set()
    try:
        with pytest.raises(RustMeshCancellationError):
            RustMeshAuthoringSession.create(controller, tmp_path / "session", process_generation=1,
                item_set_contexts=contexts, stop_event=stop, progress=progress)
        assert not (tmp_path / "session").exists()
        assert service.session_view(controller.active_session_id).revision == 0
    finally:
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_view_only_set_binds_each_file_to_its_preview_core_layers(tmp_path, monkeypatch):
    """Browse's Mesh button with an Item Finder set in scope (2026-11-23): the editable file and
    every reference piece take Browse's layered materials, not 256 px maps baked from them."""
    from cdmw.services import mesh_rust_authoring
    from cdmw.workers import mesh_archive_refit_worker

    monkeypatch.setattr(MeshArchiveMaterialContextWorker, "run", lambda worker:
        worker.context_resolved.emit(worker.request_id, SimpleNamespace(
            preview_model=None, material_package_path="", material_package_lease=None)))
    loads = []
    load = mesh_archive_refit_worker.prepare_archive_refit_source

    def recording_load(args, stop_event, **kwargs):
        loads.append((args["_archive_entry"].basename, bool(args.get("_skip_materials"))))
        return load(args, stop_event, **kwargs)

    bound = []

    def binder(mesh, contexts, service, session_id, root, stop_event):
        bound.append((contexts[0].selected_entry.basename, mesh.path))
        return SimpleNamespace(lease=None)  # an owned lease the caller holds

    monkeypatch.setattr(mesh_archive_refit_worker, "prepare_archive_refit_source", recording_load)
    monkeypatch.setattr(mesh_rust_authoring, "_bind_item_set_file_preview_core_materials", binder)
    _source, service, controller, contexts = _sources(tmp_path)
    session = None
    try:
        session = RustMeshAuthoringSession.create(controller, tmp_path / "session", process_generation=1,
                                                  item_set_contexts=contexts)
        assert bound == [("upper.pac", "upper.pac"), ("lower.pac", "lower.pac")]
        # The reference piece is read without resolving materials it would then replace.
        assert loads == [("lower.pac", True)]
        assert session.item_set_primary_material_lease is not None
    finally:
        if session is not None:
            session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_a_reference_piece_without_preview_core_layers_resolves_its_materials(monkeypatch):
    from cdmw.services import mesh_item_set_references, mesh_rust_authoring
    from cdmw.workers import mesh_archive_refit_worker

    session = SimpleNamespace(authoritative_service=object(), authoritative_session_id="s1", root="root")
    entry, context, mesh = SimpleNamespace(basename="lower.pac"), SimpleNamespace(), SimpleNamespace()
    monkeypatch.setattr(mesh_rust_authoring, "_bind_item_set_file_preview_core_materials",
                        lambda *_args: "native-lease")
    prepared = {"_archive_preview_lease": None}
    mesh_item_set_references._bind_reference_piece_materials(session, entry, context, mesh, prepared, None)
    assert prepared == {"_archive_preview_lease": None, "_preview_core_lease": "native-lease"}

    attached = []
    monkeypatch.setattr(mesh_rust_authoring, "_bind_item_set_file_preview_core_materials", lambda *_args: None)
    monkeypatch.setattr(mesh_archive_refit_worker, "attach_archive_refit_materials",
                        lambda *args, **kwargs: attached.append((args, kwargs)) or ("refit-lease", None))
    prepared = {"_archive_preview_lease": None, "_archive_physics_profile_context": "physics"}
    mesh_item_set_references._bind_reference_piece_materials(session, entry, context, mesh, prepared, None)
    assert prepared["_archive_preview_lease"] == "refit-lease"
    assert attached == [((entry, context, mesh, None), {"physics_profile_context": "physics"})]
