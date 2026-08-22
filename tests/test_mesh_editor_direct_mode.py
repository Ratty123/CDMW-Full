from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QEventLoop, QObject, QSettings, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QToolButton

from cdmw.domain.mesh import MeshEditSelection, MeshObjectTransformState
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_dotnet_experiment import mesh_dotnet_experiment_command
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import _MeshGeometryLayer
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.workers.mesh_editor_aux_workers import (
    MeshArchiveMaterialContextWorker,
    MeshArchiveSessionLoadResult,
    MeshArchiveSessionLoadWorker,
)
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker


class _ImmediateWorker(QObject):
    finished = Signal()

    @Slot()
    def run(self) -> None:
        self.finished.emit()


def _mesh(*, two_parts: bool = True) -> ParsedMesh:
    first = SubMesh(
        name="first",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    submeshes = [first]
    if two_parts:
        submeshes.append(
            SubMesh(
                name="second",
                vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
                vertex_count=3,
                face_count=1,
            )
        )
    return ParsedMesh(format="pac", path="character/model/test.pac", submeshes=submeshes)


@pytest.mark.parametrize(
    "finish_method",
    ("_finish_direct_session_worker_thread", "_finish_mesh_direct_output_worker_thread"),
)
def test_direct_workers_return_to_the_ui_thread_before_native_teardown(finish_method: str) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", f"DirectWorkerAffinity-{finish_method}"))
    worker = _ImmediateWorker()
    thread = QThread(tab)
    worker.moveToThread(thread)
    finish = getattr(tab, finish_method)
    worker.finished.connect(lambda: finish(worker), Qt.DirectConnection)
    thread.started.connect(worker.run)
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(2_000, loop.quit)
    thread.start()
    loop.exec()
    try:
        assert thread.wait(0), "the direct worker thread did not stop"
        assert worker.thread() is tab.thread()
    finally:
        if not thread.wait(0):
            thread.quit()
            thread.wait(1_000)
        worker.deleteLater()
        thread.deleteLater()
        tab.deleteLater()
        app.processEvents()


def _fake_affine(submeshes, *, position_matrices_by_index, normal_matrices_by_index=None, **_kwargs):
    changed = set()
    for index, matrix in position_matrices_by_index.items():
        submesh = submeshes[index]
        submesh.vertices = [
            (
                matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
                matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
                matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
            )
            for x, y, z in submesh.vertices
        ]
        changed.add(index)
    return changed


def _bounds_center(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [vertex for submesh in mesh.submeshes for vertex in submesh.vertices]
    return tuple(
        (min(vertex[axis] for vertex in vertices) + max(vertex[axis] for vertex in vertices)) * 0.5
        for axis in range(3)
    )


def test_object_transform_updates_every_part_around_fixed_pivot_and_preserves_selection() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="object-transform", mode="edit")
    session = service._sessions[view.session_id]
    session.selection = MeshEditSelection.from_maps(source_indices=(1,), vertices_by_submesh={1: (0,)})
    session.geometry_layers = (
        _MeshGeometryLayer("base", "Base", (0,), visible=True, base=True),
        _MeshGeometryLayer("hidden", "Hidden", (1,), visible=False),
    )
    before = clone_mesh_for_editing(service.working_mesh(view.session_id))

    with patch(
        "cdmw.services.mesh_service_object_transform.apply_native_mesh_affine_transform_submeshes",
        side_effect=_fake_affine,
    ) as native:
        result = service.set_object_transform(
            view.session_id,
            location=(4.0, -2.0, 1.0),
            rotation_degrees=(0.0, 0.0, 90.0),
            scale=(2.0, 1.5, 0.5),
        )

    assert result.ok
    assert result.affected_submesh_indices == (0, 1)
    assert set(native.call_args.kwargs["position_matrices_by_index"]) == {0, 1}
    assert service.session_view(view.session_id).selection == session.selection
    assert service.session_view(view.session_id).object_transform.pivot == (1.5, 0.5, 0.0)
    expected_center = tuple(value + delta for value, delta in zip(_bounds_center(before), (4.0, -2.0, 1.0), strict=True))
    assert _bounds_center(service.working_mesh(view.session_id)) == pytest.approx(expected_center)


def test_object_transform_undo_redo_and_package_import_restore_control_state() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="object-history", mode="edit")
    with patch(
        "cdmw.services.mesh_service_object_transform.apply_native_mesh_affine_transform_submeshes",
        side_effect=_fake_affine,
    ):
        service.set_object_transform(view.session_id, location=(1.0, 2.0, 3.0), scale=(1.2, 1.2, 1.2))
    transformed = service.session_view(view.session_id).object_transform
    assert not transformed.is_identity
    assert service.undo(view.session_id).ok
    assert service.session_view(view.session_id).object_transform.is_identity
    assert service.redo(view.session_id).ok
    assert service.session_view(view.session_id).object_transform == transformed

    imported = service.working_mesh(view.session_id, clone=True)
    service.replace_working_mesh(view.session_id, imported)
    reset = service.session_view(view.session_id).object_transform
    assert reset.is_identity
    assert reset.pivot == transformed.pivot


def test_object_transform_rejects_cancel_before_publication() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="object-cancel", mode="edit")
    before = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
    stop = threading.Event()

    def cancel_after_candidate(*args, **kwargs):
        changed = _fake_affine(*args, **kwargs)
        stop.set()
        return changed

    with patch(
        "cdmw.services.mesh_service_object_transform.apply_native_mesh_affine_transform_submeshes",
        side_effect=cancel_after_candidate,
    ), pytest.raises(Exception, match="cancelled"):
        service.set_object_transform(view.session_id, location=(9.0, 0.0, 0.0), stop_event=stop)
    assert tuple(service.working_mesh(view.session_id).submeshes[0].vertices) == before
    assert service.session_view(view.session_id).object_transform.is_identity


def test_object_transform_panel_commits_one_payload_per_completed_control_gesture() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = MeshEditorWorkspace()
    workspace.update_action_state(has_target=True, mode="edit")
    emitted: list[dict[str, tuple[float, float, float]]] = []
    workspace.object_transform_requested.connect(emitted.append)

    location_x = workspace.object_transform_spins["location"][0]
    location_x.setValue(2.5)
    location_x.editingFinished.emit()
    assert len(emitted) == 1
    assert emitted[-1]["location"] == (2.5, 0.0, 0.0)

    scale_y = workspace.object_transform_spins["scale"][1]
    scale_y.setValue(1.5)
    scale_y.editingFinished.emit()
    assert len(emitted) == 2
    assert emitted[-1]["scale"] == (1.5, 1.5, 1.5)

    tilt_button = workspace.findChild(
        QPushButton,
        "MeshEditorObjectTransformTilt1Button",
    )
    assert tilt_button is not None
    tilt_button.click()
    assert len(emitted) == 3
    assert emitted[-1]["rotation_degrees"][0] == 15.0
    app.processEvents()


def test_archive_loader_is_cancellable_and_publishes_one_direct_edit_session(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class FakeService:
        def load_mesh_bytes(self, data, source_path, *, run_roundtrip=False):
            assert data == b"mesh"
            assert source_path == entry.path
            assert run_roundtrip is True
            mesh = _mesh(two_parts=False)
            setattr(mesh, "_cdmw_mesh_asset_source_hash", "a" * 64)
            return mesh

        def open_edit_session(self, mesh, *, session_id, mode):
            assert mode == "edit"
            return SimpleNamespace(session_id=session_id, mode=mode)

    worker = MeshArchiveSessionLoadWorker(7, entry, session_id="direct-archive")
    loaded: list[object] = []
    finished: list[bool] = []
    worker.loaded.connect(lambda _request, result: loaded.append(result))
    worker.finished.connect(lambda: finished.append(True))
    with patch("cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data", return_value=(b"mesh", False, "")), patch(
        "cdmw.workers.mesh_editor_aux_workers.MeshService", FakeService
    ):
        worker.run()
    assert finished == [True]
    assert loaded[0].view.session_id == "direct-archive"
    assert loaded[0].source_sha256 == "a" * 64

    cancelled = MeshArchiveSessionLoadWorker(8, entry)
    cancelled_loaded: list[object] = []
    cancelled.loaded.connect(lambda *_args: cancelled_loaded.append(object()))
    cancelled.stop()
    cancelled.run()
    assert cancelled_loaded == []


def test_archive_material_context_uses_the_archive_preview_resolver_off_thread(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    texture_entry = ArchiveEntry(
        path="character/texture/test_base.dds",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    path_index = {texture_entry.path: (texture_entry,)}
    basename_index = {texture_entry.basename.casefold(): (texture_entry,)}
    sidecar_path_index = {"material/test_base": (texture_entry,)}
    sidecar_basename_index = {"test_base": (texture_entry,)}
    preview_model = SimpleNamespace(
        meshes=(SimpleNamespace(source_submesh_index=0, preview_texture_path="resolved.dds"),)
    )
    worker = MeshArchiveMaterialContextWorker(
        9,
        entry,
        entries_by_normalized_path=path_index,
        entries_by_basename=basename_index,
        sidecar_entries_by_texture_path=sidecar_path_index,
        sidecar_entries_by_texture_basename=sidecar_basename_index,
    )
    resolved: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.resolved.connect(lambda _request_id, model: resolved.append(model))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(preview_model=preview_model),
    ) as resolver:
        worker.run()

    assert resolved == [preview_model]
    assert errors == []
    assert finished == [True]
    assert resolver.call_args.args[:2] == (entry, ())
    assert resolver.call_args.kwargs["texture_entries_by_normalized_path"] is path_index
    assert resolver.call_args.kwargs["sidecar_entries_by_texture_path"] is sidecar_path_index
    assert resolver.call_args.kwargs["sidecar_entries_by_texture_basename"] is sidecar_basename_index
    assert resolver.call_args.kwargs["stop_event"] is worker.stop_event


def test_loaded_archive_session_prefetches_materials_when_handoff_is_geometry_only(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshMaterialPrefetch"))
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    service = MeshService()
    view = service.open_edit_session(_mesh(two_parts=False), session_id="direct-material-prefetch", mode="edit")
    tab.archive_session_load_request_id = 4
    tab.archive_session_load_entry = entry
    tab.archive_session_load_material_model = SimpleNamespace(
        meshes=(SimpleNamespace(source_submesh_index=0),)
    )
    result = MeshArchiveSessionLoadResult(
        service=service,
        view=view,
        mesh=service.working_mesh(view.session_id, clone=True),
        source_sha256="a" * 64,
    )

    with patch.object(tab, "_show_standalone_session"), patch.object(
        tab,
        "_start_archive_material_context_resolution",
        return_value=True,
    ) as start:
        tab._handle_archive_session_loaded(4, result)

    start.assert_called_once_with(entry)
    tab.close_standalone_session()
    app.processEvents()


def test_direct_textured_request_waits_for_material_context_and_publishes_it() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshMaterialContext"))
    tab.archive_material_context_pending = True
    tab.standalone_archive_material_preview_model = None

    with patch.object(tab, "_imported_working_model_owns_materials", return_value=False), patch.object(
        tab,
        "_start_archive_material_context_resolution",
    ) as start:
        assert tab._request_direct_textures_for_textured_view() == "started"
    start.assert_not_called()

    tab.archive_material_context_pending = False
    tab.standalone_archive_material_preview_model = SimpleNamespace(
        meshes=(SimpleNamespace(source_submesh_index=0),)
    )
    with patch.object(tab, "_imported_working_model_owns_materials", return_value=False), patch.object(
        tab,
        "_start_archive_material_context_resolution",
        return_value=True,
    ) as start:
        assert tab._request_direct_textures_for_textured_view() == "started"
    start.assert_called_once_with()

    preview_model = SimpleNamespace(
        meshes=(SimpleNamespace(source_submesh_index=0, preview_texture_path="resolved.dds"),)
    )
    tab.archive_material_context_request_id = 12
    tab.standalone_dotnet_pending_textured_view = True
    with patch.object(tab, "apply_resident_clone_material_resources", return_value=True) as publish:
        tab._handle_archive_material_context_resolved(12, preview_model)

    assert tab.standalone_archive_material_preview_model is preview_model
    assert not tab.archive_material_context_pending
    publish.assert_called_once_with(preview_model)
    app.processEvents()


def test_direct_resident_editor_does_not_disable_qt_owned_output_controls(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshOutputControls"))
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    tab.current_archive_selection = entry
    tab.standalone_controller = SimpleNamespace(active_session_id="direct-output-controls")
    tab.standalone_native_editor_available = True
    tab.standalone_last_export_validation_report = SimpleNamespace(ok=True)
    tab.standalone_dotnet_embedded_state = "launching"
    tab.standalone_dotnet_target_embedded = False

    with patch.object(tab, "_standalone_dotnet_editor_process_running", return_value=True):
        tab.update_editor_action_state(publish_native=False)

        assert tab.standalone_run_validation_report_button.isEnabled()
        assert tab.standalone_export_mesh_file_button.isEnabled()
        assert tab.standalone_build_mod_button.isEnabled()
        assert tab.standalone_install_overlay_button.isEnabled()

        tab.standalone_dotnet_target_embedded = True
        tab.update_editor_action_state(publish_native=False)
        assert not tab.standalone_run_validation_report_button.isEnabled()
    app.processEvents()


def test_direct_output_button_clicks_reach_each_tab_handler() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshOutputButtonClicks"))
    workspace = tab.standalone_workspace
    emitted: list[str] = []
    messages: list[tuple[str, bool]] = []
    controls = (
        ("run_validation_report_button", "validation_report_requested", "validation"),
        ("export_mesh_file_button", "export_mesh_file_requested", "export_mesh"),
        ("build_mod_button", "build_mod_requested", "build_mod"),
        ("install_overlay_button", "install_overlay_requested", "install_overlay"),
        ("restore_overlay_button", "restore_overlay_requested", "restore_overlay"),
    )
    tab.status_message_requested.connect(
        lambda message, error=False: messages.append((str(message), bool(error)))
    )
    workspace.setEnabled(True)

    for button_name, signal_name, action_name in controls:
        getattr(workspace, signal_name).connect(lambda name=action_name: emitted.append(name))
        button = getattr(workspace, button_name)
        button.setEnabled(True)
        button.click()

    assert emitted == ["validation", "export_mesh", "build_mod", "install_overlay", "restore_overlay"]
    assert messages == [
        ("Open a mesh session before running validation.", True),
        ("Run validation successfully before rebuilding a patched asset.", True),
        ("Open an archive mesh before creating a Mesh Editor output.", True),
        ("Open an archive mesh before creating a Mesh Editor output.", True),
        ("No Mesh Editor overlay install receipt is available.", True),
    ]
    tab.deleteLater()
    app.processEvents()


def test_mesh_editor_inventory_is_mesh_only_and_direct_authoring_is_explicit(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshInventory"))
    workspace = tab.standalone_workspace
    assert tab.builder_host() is None
    assert not hasattr(tab, "open_texture_source_requested")
    assert workspace.findChild(QToolButton, "MeshEditorOpenTextureButton") is None
    assert workspace.findChild(QToolButton, "MeshEditorExportMeshFileButton") is not None
    assert workspace.findChild(QToolButton, "MeshEditorBuildModButton") is not None
    assert workspace.findChild(QToolButton, "MeshEditorInstallOverlayButton") is not None
    assert workspace.findChild(QToolButton, "MeshEditorRestoreOverlayButton") is not None

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    package = SimpleNamespace(
        package_dir=tmp_path,
        status_path=output_dir / "status.json",
        edit_operations_path=output_dir / "edits.json",
        evaluation_path=output_dir / "evaluation.md",
        scene_mesh_path=tmp_path / "scene.obj",
        mesh_path=tmp_path / "mesh.obj",
        cdmeta_path=tmp_path / "mesh.cdmeta.json",
        output_dir=output_dir,
    )
    _program, arguments = mesh_dotnet_experiment_command(
        tmp_path / "helper.exe",
        package,
        embedded_parent_hwnd=123,
        profile="authoring",
        direct_authoring=True,
    )
    assert "--direct-authoring" in arguments
    app.processEvents()


def test_direct_authoring_source_inventory_excludes_colour_and_texture_region_capability() -> None:
    root = Path("tools/dotnet_mesh_editor_experiment")
    runtime = (root / "RuntimeSupport.cs").read_text(encoding="utf-8")
    program = (root / "Program.cs").read_text(encoding="utf-8")
    tools = (root / "EditMeshToolListContract.cs").read_text(encoding="utf-8")
    provenance = (root / "HelperBuildProvenance.cs").read_text(encoding="utf-8")
    protocol = (root / "ExperimentForm.Protocol.cs").read_text(encoding="utf-8")
    assert 'values.ContainsKey("direct-authoring")' in runtime
    assert 'options.DirectAuthoring && options.Authoring' in program
    assert "Keys.Colour" not in tools
    assert '"direct_authoring_host_v1"' in provenance
    assert '"resident_texture_region_updates_v1"' not in provenance
    assert 'case "texture_region_update":' not in protocol


def test_loose_output_captures_after_pending_work_and_never_writes_source_archives(tmp_path: Path) -> None:
    archive_dir = tmp_path / "game" / "0009"
    archive_dir.mkdir(parents=True)
    pamt = archive_dir / "0.pamt"
    paz = archive_dir / "0.paz"
    pamt.write_bytes(b"source index")
    paz.write_bytes(b"source payload")
    before = (pamt.read_bytes(), paz.read_bytes())
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=pamt,
        paz_file=paz,
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    pending_drained: list[bool] = []

    class FakeService:
        def capture_export_snapshot(self, session_id, *, stop_event, expected_mesh_revision):
            assert session_id == "direct-output"
            assert pending_drained == [True]
            assert expected_mesh_revision is None
            assert not stop_event.is_set()
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=12,
                native_edit_revision=7,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / "loose-mesh-mod"
    worker = MeshDirectOutputWorker(
        41,
        FakeService(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
        texture_updates_waiter=lambda _timeout: pending_drained.append(True) or True,
    )
    completed: list[object] = []
    worker.completed.connect(lambda _request_id, result: completed.append(result))
    worker.run()

    assert len(completed) == 1
    assert (output_root / entry.path).read_bytes() == b"rebuilt mesh"
    metadata = (output_root / "mesh-editor-session.json").read_text(encoding="utf-8")
    assert '"materials": "inherited_unchanged"' in metadata
    assert '"textures": "inherited_unchanged"' in metadata
    assert sorted(path.relative_to(output_root).as_posix() for path in output_root.rglob("*") if path.is_file()) == [
        "character/model/test.pac",
        "mesh-editor-session.json",
    ]
    assert (pamt.read_bytes(), paz.read_bytes()) == before


def test_direct_output_cancellation_before_capture_writes_nothing(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    output_root = tmp_path / "cancelled-output"
    worker = MeshDirectOutputWorker(
        42,
        SimpleNamespace(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
    )
    cancelled: list[str] = []
    worker.cancelled.connect(lambda _request_id, message: cancelled.append(message))
    worker.stop()
    worker.run()

    assert cancelled == ["Mesh output cancelled."]
    assert not output_root.exists()


def test_archive_session_handlers_reject_stale_results_and_close_cancels_load_and_output() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshCorrelation"))
    tab.archive_session_load_request_id = 17
    tab.standalone_status_label.setText("current state")
    tab._handle_archive_session_load_error(16, "stale failure")
    assert tab.standalone_status_label.text() == "current state"
    discarded: list[tuple[str, bool]] = []
    stale_result = MeshArchiveSessionLoadResult(
        service=SimpleNamespace(
            close_edit_session=lambda session_id, *, force_without_saving: discarded.append(
                (session_id, force_without_saving)
            )
        ),
        view=SimpleNamespace(session_id="stale-session"),
        mesh=_mesh(two_parts=False),
        source_sha256="a" * 64,
    )
    tab._handle_archive_session_loaded(16, stale_result)
    assert discarded == [("stale-session", True)]

    class Stoppable:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    class ThreadStub:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_requested = False

        def requestInterruption(self) -> None:
            self.interrupted = True

        def quit(self) -> None:
            self.quit_requested = True

    load_worker = Stoppable()
    load_thread = ThreadStub()
    material_worker = Stoppable()
    material_thread = ThreadStub()
    output_worker = Stoppable()
    tab.archive_session_load_worker = load_worker
    tab.archive_session_load_thread = load_thread
    tab.archive_material_context_worker = material_worker
    tab.archive_material_context_thread = material_thread
    tab.standalone_output_worker = output_worker
    tab.close_standalone_session()

    assert load_worker.stopped
    assert load_thread.interrupted and load_thread.quit_requested
    assert material_worker.stopped
    assert material_thread.interrupted and material_thread.quit_requested
    assert output_worker.stopped
    assert tab.archive_session_load_request_id > 17
    app.processEvents()


def test_replacing_an_edited_archive_session_requires_confirmation(tmp_path: Path) -> None:
    current = ArchiveEntry(
        path="character/model/current.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    replacement = ArchiveEntry(
        path="character/model/replacement.pac",
        pamt_path=current.pamt_path,
        paz_file=current.paz_file,
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class TabStub:
        standalone_controller = SimpleNamespace(
            session_view=lambda: SimpleNamespace(revision=3),
        )

        def __init__(self) -> None:
            self.closed = False

        def active_builder(self):
            return None

        def has_active_standalone_session(self):
            return True

        def _current_target_entry(self):
            return current

        def close_standalone_session(self):
            self.closed = True

    class Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.mesh_editor_tab = TabStub()
            self._modeless_alignment_dialogs = {}
            self.activated = False

        def _activate_tool_widget(self, _widget):
            self.activated = True

        def set_status_message(self, *_args, **_kwargs):
            pass

    harness = Harness()
    with patch("cdmw.ui.mesh_editor.shell_bridge.QMessageBox.question", return_value=0):
        assert harness._prepare_mesh_editor_archive_launch(replacement) is False
    assert not harness.mesh_editor_tab.closed
    assert harness.activated

    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.QMessageBox.question",
        return_value=QMessageBox.Yes,
    ):
        assert harness._prepare_mesh_editor_archive_launch(replacement) is True
    assert harness.mesh_editor_tab.closed
