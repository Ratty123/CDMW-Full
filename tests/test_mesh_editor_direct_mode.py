from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QSettings, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QToolButton

from cdmw.domain.mesh import MeshEditSelection, MeshExportValidationReport, MeshObjectTransformState
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services.mesh_dotnet_experiment import mesh_dotnet_experiment_command
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import _MeshGeometryLayer
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
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


def _archive_source_identity(entry: ArchiveEntry) -> dict[str, object]:
    return {
        "normalized_path": entry.identity.normalized_path,
        "source_pamt": entry.identity.source_pamt,
        "paz_index": entry.identity.paz_index,
        "entry_offset": entry.identity.entry_offset,
    }


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
        assert thread.wait(1_000), "the direct worker thread did not stop"
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


def test_archive_loader_auto_attaches_a_resolved_pab_without_blocking_mesh_load(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/cd_pgm_00_nude_00_0001.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    skeleton_entry = ArchiveEntry(
        path="character/skeleton/cd_pgm_00.pab",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=8,
        comp_size=3,
        orig_size=3,
        flags=0,
        paz_index=0,
    )
    parsed_skeleton = SimpleNamespace(path=skeleton_entry.path, bones=(object(),))
    attached: list[tuple[object, ...]] = []

    class FakeService:
        def load_mesh_bytes(self, _data, _source_path, *, run_roundtrip=False):
            assert run_roundtrip is True
            return _mesh(two_parts=False)

        def open_edit_session(self, _mesh_value, *, session_id, mode):
            assert mode == "edit"
            return SimpleNamespace(session_id=session_id, mode=mode)

        def attach_skeleton(self, session_id, skeleton, **metadata):
            attached.append((session_id, skeleton, metadata))

    path_index = {skeleton_entry.path: (skeleton_entry,)}
    basename_index = {"cd_pgm_00.pab": (skeleton_entry,)}
    worker = MeshArchiveSessionLoadWorker(
        9,
        entry,
        session_id="direct-archive-rig",
        archive_entries_by_normalized_path=path_index,
        archive_entries_by_basename=basename_index,
    )
    loaded: list[object] = []
    worker.loaded.connect(lambda _request, result: loaded.append(result))
    report = SimpleNamespace(
        reason="candidate basename",
        blocking_errors=(),
        skeleton_descriptor_path="character/model/body.pac_xml",
        skeleton_variation_path="",
        animation_constraint_path="",
        socket_path="",
    )

    def read_payload(candidate, **_kwargs):
        return ((b"pab" if candidate is skeleton_entry else b"mesh"), False, "")

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data",
        side_effect=read_payload,
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.resolve_skeleton_for_model",
        return_value=(skeleton_entry, report),
    ) as resolve, patch(
        "cdmw.workers.mesh_editor_aux_workers.parse_pab",
        return_value=parsed_skeleton,
    ) as parse, patch(
        "cdmw.workers.mesh_editor_aux_workers.MeshService",
        FakeService,
    ):
        worker.run()

    assert len(loaded) == 1
    assert loaded[0].source_skeleton is parsed_skeleton
    assert loaded[0].skeleton_source_path == skeleton_entry.path
    assert loaded[0].skeleton_resolution_reason == "candidate basename"
    assert attached[0][0:2] == ("direct-archive-rig", parsed_skeleton)
    assert attached[0][2]["source_path"] == skeleton_entry.path
    assert attached[0][2]["skeleton_descriptor_source"] == "character/model/body.pac_xml"
    assert resolve.call_args.kwargs["archive_entries_by_normalized_path"] is path_index
    assert resolve.call_args.kwargs["archive_entries_by_basename"] is basename_index
    parse.assert_called_once_with(b"pab", skeleton_entry.path)


def test_archive_session_waits_for_lazy_indexes_before_starting_automatic_pab_load(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/cd_pgm_00_nude_00_0001.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    skeleton_entry = ArchiveEntry(
        path="character/skeleton/cd_pgm_00.pab",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=8,
        comp_size=3,
        orig_size=3,
        flags=0,
        paz_index=0,
    )
    path_index: dict[str, tuple[ArchiveEntry, ...]] = {}
    basename_index: dict[str, tuple[ArchiveEntry, ...]] = {}
    ensure_calls: list[bool] = []
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshLazySkeletonIndex"),
        get_archive_texture_entries_by_normalized_path=lambda: path_index,
        get_archive_texture_entries_by_basename=lambda: basename_index,
        get_archive_sidecar_entries_by_texture_path=lambda: {},
        get_archive_sidecar_entries_by_texture_basename=lambda: {},
        ensure_archive_texture_indexes=lambda: ensure_calls.append(True) or True,
    )
    callbacks: list[object] = []

    with patch.object(tab, "_start_archive_session_load_worker") as start, patch(
        "cdmw.ui.mesh_editor.tab_session_runtime.QTimer.singleShot",
        side_effect=lambda _milliseconds, callback: callbacks.append(callback),
    ):
        request_id = tab.open_archive_session(entry)
        assert not start.called
        assert ensure_calls == [True]
        assert len(callbacks) == 1
        assert "matching skeleton" in tab.standalone_status_label.text()

        path_index[skeleton_entry.path] = (skeleton_entry,)
        basename_index[skeleton_entry.basename.casefold()] = (skeleton_entry,)
        callbacks.pop()()

    start.assert_called_once()
    args = start.call_args.args
    kwargs = start.call_args.kwargs
    assert args[0] == request_id
    assert args[1].identity == entry.identity
    assert args[1] is not entry
    assert kwargs["archive_path_index"] is path_index
    assert kwargs["archive_basename_index"] is basename_index
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_archive_session_keeps_verified_archive_browser_material_graph_for_rust(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/layered_equipment.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    preview_model = SimpleNamespace(
        path=entry.path,
        meshes=(
            SimpleNamespace(
                source_submesh_index=0,
                preview_texture_dds_path=str(tmp_path / "layered_base.dds"),
                preview_pac_material_parameters=(
                    ("_dyeingDetailLayerColorMaskR", "#162fffff"),
                ),
            ),
        ),
    )
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshVerifiedRustMaterialGraph"),
        get_archive_texture_entries_by_normalized_path=lambda: {},
        get_archive_texture_entries_by_basename=lambda: {},
        get_archive_sidecar_entries_by_texture_path=lambda: {},
        get_archive_sidecar_entries_by_texture_basename=lambda: {},
    )

    with patch.object(tab, "_start_archive_session_load_when_indexes_ready"):
        tab.open_archive_session(
            entry,
            material_preview_model=preview_model,
            material_context_verified_for_rust=True,
            material_source_identity=entry.identity,
        )

    assert tab.archive_session_load_material_model is preview_model
    assert tab.archive_material_context_verified_for_rust
    assert tab.archive_material_context_source_identity == entry.identity
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_archive_session_rejects_verified_materials_from_a_same_path_collision(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/layered_equipment.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    stale_entry = copy.deepcopy(entry)
    stale_entry.pamt_path = tmp_path / "0010" / "0.pamt"
    stale_entry.paz_index = 1
    stale_entry.offset = 8
    preview_model = SimpleNamespace(
        path=entry.path,
        meshes=(SimpleNamespace(preview_texture_dds_path="stale.dds"),),
    )
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshRejectsStaleMaterialIdentity"),
    )

    with patch.object(tab, "_start_archive_session_load_when_indexes_ready"):
        tab.open_archive_session(
            entry,
            material_preview_model=preview_model,
            material_context_verified_for_rust=True,
            material_source_identity=stale_entry.identity,
        )

    assert not tab.archive_material_context_verified_for_rust
    assert tab.archive_material_context_source_identity is None
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_archive_open_waits_for_terminal_rust_finish_then_starts_once(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    first = ArchiveEntry(
        path="character/model/first.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    second = ArchiveEntry(
        path="character/model/second.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    preview_model = SimpleNamespace(
        path=second.path,
        meshes=(SimpleNamespace(preview_texture_dds_path="second.dds"),),
    )
    releases: list[bool] = []
    carried_lease = SimpleNamespace(release=lambda: releases.append(True))
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshDeferredRustFinishOpen"),
    )
    tab.current_archive_selection = first
    tab.archive_material_context_package_path = str(tmp_path / "textured-package")
    tab.archive_material_context_package_lease = carried_lease
    starts: list[tuple[int, ArchiveEntry, dict[str, object]]] = []

    def record_start(
        request_id: int,
        entry: ArchiveEntry,
        **kwargs: object,
    ) -> None:
        starts.append((request_id, entry, kwargs))

    with patch.object(
        tab,
        "_defer_standalone_close_for_rust_finish",
        side_effect=(True, False, False),
    ), patch.object(
        tab,
        "_start_archive_session_load_when_indexes_ready",
        side_effect=record_start,
    ):
        deferred = tab.open_archive_session(
            second,
            material_preview_model=preview_model,
            material_package_path=tab.archive_material_context_package_path,
            material_package_lease=carried_lease,
            material_context_verified_for_rust=True,
            material_source_identity=second.identity,
        )

        assert deferred is None
        assert starts == []
        assert tab.current_archive_selection is first
        assert tab.archive_material_context_package_lease is carried_lease
        assert tab.archive_session_open_pending is not None
        assert tab.close_standalone_session()
        app.processEvents()

    assert len(starts) == 1
    assert starts[0][1].identity == second.identity
    assert tab.current_archive_selection.identity == second.identity
    assert tab.archive_material_context_package_lease is carried_lease
    assert tab.archive_material_context_verified_for_rust
    assert tab.archive_session_open_pending is None
    assert releases == []
    tab.close_standalone_session()
    assert releases == [True]
    tab.deleteLater()
    app.processEvents()


def test_archive_open_cannot_race_a_scheduled_terminal_rust_close(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    first = ArchiveEntry(
        path="character/model/first.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    second = ArchiveEntry(
        path="character/model/second.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    releases: list[bool] = []
    carried_lease = SimpleNamespace(release=lambda: releases.append(True))
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshTerminalCloseRace"),
    )
    tab.current_archive_selection = first
    tab.archive_material_context_package_lease = carried_lease
    tab.standalone_rust_terminal_close_pending = True
    starts: list[ArchiveEntry] = []

    with patch.object(
        tab,
        "_start_archive_session_load_when_indexes_ready",
        side_effect=lambda _request_id, entry, **_kwargs: starts.append(entry),
    ):
        assert (
            tab.open_archive_session(
                second,
                material_package_lease=carried_lease,
                material_source_identity=second.identity,
            )
            is None
        )
        assert starts == []
        assert tab.current_archive_selection is first
        tab._complete_deferred_rust_session_close()
        app.processEvents()

    assert [entry.identity for entry in starts] == [second.identity]
    assert tab.current_archive_selection.identity == second.identity
    assert tab.archive_material_context_package_lease is carried_lease
    assert not tab.standalone_rust_terminal_close_pending
    assert tab.archive_session_open_pending is None
    assert releases == []
    tab.close_standalone_session()
    assert releases == [True]
    tab.deleteLater()
    app.processEvents()


def test_stale_terminal_rust_close_cannot_close_a_replacement_controller(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshStaleTerminalClose"),
    )
    original = SimpleNamespace(active_session_id="original")
    replacement = SimpleNamespace(active_session_id="replacement")
    tab.standalone_controller = replacement  # type: ignore[assignment]
    tab.standalone_rust_terminal_close_pending = True
    tab.standalone_rust_close_session_pending = True

    with patch.object(tab, "close_standalone_session") as close_session:
        tab._complete_deferred_rust_session_close(original)

    close_session.assert_not_called()
    assert tab.standalone_controller is replacement
    assert not tab.standalone_rust_terminal_close_pending
    assert not tab.standalone_rust_close_session_pending

    tab.standalone_rust_terminal_close_pending = True
    tab.standalone_rust_close_session_pending = True
    tab._reset_rust_session_references()
    assert not tab.standalone_rust_terminal_close_pending
    assert not tab.standalone_rust_close_session_pending
    tab.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("close_action", ("show_empty_state", "request_shutdown"))
def test_explicit_close_or_shutdown_discards_queued_archive_open(
    tmp_path: Path,
    close_action: str,
) -> None:
    app = QApplication.instance() or QApplication([])
    first = ArchiveEntry(
        path="character/model/first.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    second = ArchiveEntry(
        path="character/model/second.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    current_releases: list[bool] = []
    queued_releases: list[bool] = []
    current_lease = SimpleNamespace(
        release=lambda: current_releases.append(True)
    )
    queued_lease = SimpleNamespace(release=lambda: queued_releases.append(True))
    tab = MeshEditorTab(
        settings=QSettings(
            "CDMWTests", f"DirectMeshDiscardQueuedOpen-{close_action}"
        ),
    )
    tab.current_archive_selection = first
    tab.archive_material_context_package_lease = current_lease
    tab.archive_session_open_pending = {
        "entry": second,
        "material_package_lease": queued_lease,
    }
    tab.standalone_rust_terminal_close_pending = True
    starts: list[ArchiveEntry] = []

    with patch.object(
        tab,
        "_start_archive_session_load_when_indexes_ready",
        side_effect=lambda _request_id, entry, **_kwargs: starts.append(entry),
    ):
        getattr(tab, close_action)()
        assert tab.archive_session_open_pending is None
        assert queued_releases == [True]
        assert current_releases == []
        tab._complete_deferred_rust_session_close()
        app.processEvents()

    assert starts == []
    assert current_releases == [True]
    tab.deleteLater()
    app.processEvents()


def test_async_mesh_file_open_reports_deferred_while_rust_finish_closes(
    tmp_path: Path,
) -> None:
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshAsyncFileDeferred"),
    )

    with patch.object(tab, "close_standalone_session", return_value=False):
        request_id = tab.open_mesh_file_session_async(tmp_path / "deferred.obj")

    assert request_id is None
    assert tab.standalone_file_load_worker is None
    assert tab.standalone_file_load_thread is None
    tab.deleteLater()


def test_latest_deferred_archive_open_supersedes_and_releases_the_previous_one(
    tmp_path: Path,
) -> None:
    first = ArchiveEntry(
        path="character/model/first.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    second = copy.deepcopy(first)
    second.path = "character/model/second.pac"
    second.offset = 8
    third = copy.deepcopy(first)
    third.path = "character/model/third.pac"
    third.offset = 16
    old_releases: list[bool] = []
    new_releases: list[bool] = []
    old_lease = SimpleNamespace(release=lambda: old_releases.append(True))
    new_lease = SimpleNamespace(release=lambda: new_releases.append(True))
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshLatestDeferredOpen"),
    )
    tab.current_archive_selection = first
    tab.archive_session_open_pending = {
        "entry": second,
        "material_package_lease": old_lease,
    }
    tab.standalone_rust_terminal_close_pending = True

    assert (
        tab.open_archive_session(third, material_package_lease=new_lease) is None
    )

    assert old_releases == [True]
    assert new_releases == []
    assert tab.archive_session_open_pending is not None
    assert tab.archive_session_open_pending["entry"].identity == third.identity
    tab._discard_queued_archive_session_open()
    assert new_releases == [True]
    tab.standalone_rust_terminal_close_pending = False
    tab.close_standalone_session()
    tab.deleteLater()


def test_closing_archive_session_invalidates_a_lazy_index_loader_before_it_starts(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/cancelled-lazy-load.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "DirectMeshCancelledLazySkeletonIndex"),
        get_archive_texture_entries_by_normalized_path=lambda: {},
        get_archive_texture_entries_by_basename=lambda: {},
        get_archive_sidecar_entries_by_texture_path=lambda: {},
        get_archive_sidecar_entries_by_texture_basename=lambda: {},
        ensure_archive_texture_indexes=lambda: True,
    )
    callbacks: list[object] = []

    with patch.object(tab, "_start_archive_session_load_worker") as start, patch(
        "cdmw.ui.mesh_editor.tab_session_runtime.QTimer.singleShot",
        side_effect=lambda _milliseconds, callback: callbacks.append(callback),
    ):
        request_id = tab.open_archive_session(entry)
        assert len(callbacks) == 1
        tab.close_standalone_session()
        assert tab.archive_session_load_request_id > request_id
        assert tab.archive_session_load_entry is None
        assert tab.archive_session_load_material_model is None
        callbacks.pop()()

    start.assert_not_called()
    tab.deleteLater()
    app.processEvents()


def test_archive_loader_keeps_mesh_editable_when_resolved_pab_is_invalid(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/body.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    skeleton_entry = ArchiveEntry(
        path="character/model/body.pab",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=8,
        comp_size=3,
        orig_size=3,
        flags=0,
        paz_index=0,
    )

    class FakeService:
        def load_mesh_bytes(self, *_args, **_kwargs):
            return _mesh(two_parts=False)

        def open_edit_session(self, _mesh_value, *, session_id, mode):
            return SimpleNamespace(session_id=session_id, mode=mode)

    worker = MeshArchiveSessionLoadWorker(
        10,
        entry,
        session_id="invalid-pab-nonfatal",
        archive_entries_by_basename={"body.pab": (skeleton_entry,)},
    )
    loaded: list[object] = []
    worker.loaded.connect(lambda _request, result: loaded.append(result))
    report = SimpleNamespace(reason="exact sibling path", blocking_errors=())

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data",
        side_effect=lambda candidate, **_kwargs: (
            b"bad" if candidate is skeleton_entry else b"mesh",
            False,
            "",
        ),
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.resolve_skeleton_for_model",
        return_value=(skeleton_entry, report),
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.parse_pab",
        side_effect=ValueError("invalid PAB"),
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.MeshService",
        FakeService,
    ):
        worker.run()

    assert len(loaded) == 1
    assert loaded[0].source_skeleton is None
    assert loaded[0].skeleton_source_path == ""
    assert "invalid PAB" in loaded[0].skeleton_resolution_reason


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
    companion_entry = ArchiveEntry(
        path="character/model/test_companion.pac",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=16,
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
        path=entry.path,
        meshes=(SimpleNamespace(source_submesh_index=0, preview_texture_path="resolved.dds"),)
    )
    worker = MeshArchiveMaterialContextWorker(
        9,
        entry,
        companion_entry=companion_entry,
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
    ) as resolver, patch(
        "cdmw.workers.mesh_editor_aux_workers.count_dotnet_own_material_bindings",
        return_value=1,
    ):
        worker.run()

    assert resolved == [preview_model]
    assert errors == []
    assert finished == [True]
    assert resolver.call_args.args[:2] == (entry, ())
    assert resolver.call_args.kwargs["companion_entry"] is companion_entry
    assert resolver.call_args.kwargs["texture_entries_by_normalized_path"] is path_index
    assert resolver.call_args.kwargs["sidecar_entries_by_texture_path"] is sidecar_path_index
    assert resolver.call_args.kwargs["sidecar_entries_by_texture_basename"] is sidecar_basename_index
    assert resolver.call_args.kwargs["stop_event"] is worker.stop_event


def test_archive_material_context_publishes_the_package_created_by_full_resolution(
    tmp_path: Path,
) -> None:
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
    geometry_package = tmp_path / "geometry-package"
    geometry_package.mkdir()
    (geometry_package / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": entry.path,
                "source_identity": _archive_source_identity(entry),
                "batches": [{"editor_identity": {"source_local_submesh_index": 0}}],
            }
        ),
        encoding="utf-8",
    )
    textured_package = tmp_path / "textured-package"
    textured_package.mkdir()
    (textured_package / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": entry.path,
                "source_identity": _archive_source_identity(entry),
                "batches": [],
            }
        ),
        encoding="utf-8",
    )
    preview_model = SimpleNamespace(
        path=entry.path,
        meshes=(
            SimpleNamespace(
                source_submesh_index=0,
                preview_texture_dds_path=str(textured_package / "body.dds"),
            ),
        )
    )
    worker = MeshArchiveMaterialContextWorker(
        11,
        entry,
        material_package_path=geometry_package,
    )
    contexts: list[object] = []
    errors: list[str] = []
    worker.context_resolved.connect(
        lambda _request_id, context: contexts.append(context)
    )
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(
            preview_model=preview_model,
            dotnet_preview_package_path=str(textured_package),
        ),
    ) as resolver:
        worker.run()

    assert errors == []
    assert len(contexts) == 1
    context = contexts[0]
    assert context.preview_model is preview_model
    assert context.source_identity == entry.identity
    assert context.material_package_path == str(textured_package)
    assert context.material_package_lease is not None
    assert context.material_package_lease.active
    resolver.assert_called_once()
    context.release()
    assert not context.material_package_lease.active


def test_archive_material_context_accepts_path_only_package_with_exact_cache_dependency(
    tmp_path: Path,
) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=32,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    package_path = tmp_path / "cache" / "package"
    package_path.mkdir(parents=True)
    (package_path / "manifest.json").write_text(
        json.dumps({"source_path": entry.path, "batches": []}),
        encoding="utf-8",
    )
    (package_path.parent / "cache_entry.json").write_text(
        json.dumps(
            {
                "diagnostics": {
                    "cache_dependency_entries": [
                        {
                            "path": entry.path,
                            "pamt_path": str(entry.pamt_path),
                            "paz_file": str(entry.paz_file),
                            "paz_index": entry.paz_index,
                            "offset": entry.offset,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    worker = MeshArchiveMaterialContextWorker(
        14,
        entry,
        material_package_path=package_path,
    )
    assert worker._package_manifest_matches_entry(package_path)

    same_path_other_archive = ArchiveEntry(
        path=entry.path,
        pamt_path=tmp_path / "0010" / "0.pamt",
        paz_file=tmp_path / "0010" / "0.paz",
        offset=40,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=1,
    )
    stale_worker = MeshArchiveMaterialContextWorker(
        15,
        same_path_other_archive,
        material_package_path=package_path,
    )
    assert not stale_worker._package_manifest_matches_entry(package_path)


def test_archive_material_context_prefers_full_pac_graph_over_native_batch_rows(
    tmp_path: Path,
) -> None:
    entry = ArchiveEntry(
        path="character/model/native_materials.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    package_path = tmp_path / "archive-preview-package"
    package_path.mkdir()
    (package_path / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": entry.path,
                "source_identity": _archive_source_identity(entry),
                "batches": [
                    {
                        "editor_identity": {"source_local_submesh_index": 0},
                        "dds_textures": {
                            "base": {
                                "slot": "base",
                                "source_path": str(tmp_path / "resolved_base.dds"),
                                "semantic_type": "color",
                                "semantic_subtype": "albedo",
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    worker = MeshArchiveMaterialContextWorker(
        10,
        entry,
        material_package_path=package_path,
    )
    full_preview_model = SimpleNamespace(
        path=entry.path,
        meshes=(
            SimpleNamespace(
                source_submesh_index=0,
                preview_texture_dds_path=str(tmp_path / "resolved_full_base.dds"),
                preview_pac_material_parameters=(
                    ("_dyeingDetailLayerColorMaskR", "#162fffff"),
                ),
            ),
        ),
    )
    resolved: list[object] = []
    contexts: list[object] = []
    errors: list[str] = []
    worker.resolved.connect(lambda _request_id, model: resolved.append(model))
    worker.context_resolved.connect(
        lambda _request_id, context: contexts.append(context)
    )
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(
            preview_model=full_preview_model,
            dotnet_preview_package_path="",
        ),
    ) as resolver:
        worker.run()

    assert errors == []
    assert resolved == [full_preview_model]
    assert len(contexts) == 1
    assert contexts[0].preview_model is full_preview_model
    assert contexts[0].source_identity == entry.identity
    assert contexts[0].material_package_path == str(package_path)
    assert contexts[0].material_package_lease is not None
    assert contexts[0].material_package_lease.active
    assert resolved[0].meshes[0].preview_pac_material_parameters == (
        ("_dyeingDetailLayerColorMaskR", "#162fffff"),
    )
    resolver.assert_called_once()
    contexts[0].release()
    assert not contexts[0].material_package_lease.active


def test_archive_material_context_uses_native_batch_rows_only_as_fallback(
    tmp_path: Path,
) -> None:
    entry = ArchiveEntry(
        path="character/model/native_materials.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    package_path = tmp_path / "archive-preview-package"
    package_path.mkdir()
    (package_path / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": entry.path,
                "source_identity": _archive_source_identity(entry),
                "batches": [
                    {
                        "editor_identity": {"source_local_submesh_index": 0},
                        "dds_textures": {
                            "base": {
                                "slot": "base",
                                "source_path": str(tmp_path / "resolved_base.dds"),
                                "semantic_type": "color",
                                "semantic_subtype": "albedo",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = MeshArchiveMaterialContextWorker(
        10,
        entry,
        material_package_path=package_path,
    )
    resolved: list[object] = []
    errors: list[str] = []
    worker.resolved.connect(lambda _request_id, model: resolved.append(model))
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(
            preview_model=None,
            warning_text="full resolver unavailable",
        ),
    ) as resolver:
        worker.run()

    assert errors == []
    assert len(resolved) == 1
    assert resolved[0].meshes[0].preview_texture_dds_path == str(
        tmp_path / "resolved_base.dds"
    )
    resolver.assert_called_once()


@pytest.mark.parametrize(
    ("declared_source_path", "declared_entry_offset"),
    (
        ("character/model/another.pac", None),
        ("character/model/requested.pac", 999),
    ),
)
def test_archive_material_context_rejects_a_package_for_another_archive_entry_before_leasing(
    tmp_path: Path,
    declared_source_path: str,
    declared_entry_offset: int | None,
) -> None:
    entry = ArchiveEntry(
        path="character/model/requested.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=32,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    stale_package = tmp_path / "stale-preview-package"
    stale_package.mkdir()
    manifest: dict[str, object] = {
        "source_path": declared_source_path,
        "batches": [
            {
                "dds_textures": {
                    "base": {
                        "source_path": str(tmp_path / "stale.dds"),
                    }
                }
            }
        ],
    }
    if declared_entry_offset is not None:
        manifest["source_identity"] = {
            "normalized_path": entry.identity.normalized_path,
            "source_pamt": entry.identity.source_pamt,
            "paz_index": entry.identity.paz_index,
            "entry_offset": declared_entry_offset,
        }
    (stale_package / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    fresh_model = SimpleNamespace(
        path=entry.path,
        meshes=(
            SimpleNamespace(
                source_submesh_index=0,
                preview_texture_dds_path=str(tmp_path / "fresh.dds"),
            ),
        ),
    )
    worker = MeshArchiveMaterialContextWorker(
        12,
        entry,
        material_package_path=stale_package,
    )
    contexts: list[object] = []
    errors: list[str] = []
    worker.context_resolved.connect(
        lambda _request_id, context: contexts.append(context)
    )
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(
            preview_model=fresh_model,
            dotnet_preview_package_path="",
        ),
    ) as resolver, patch(
        "cdmw.workers.mesh_editor_aux_workers.acquire_dotnet_preview_package_cache_lease_for_path"
    ) as acquire_lease:
        worker.run()

    assert errors == []
    assert len(contexts) == 1
    assert contexts[0].preview_model is fresh_model
    assert contexts[0].material_package_path == ""
    resolver.assert_called_once()
    acquire_lease.assert_not_called()


@pytest.mark.parametrize(
    "model_path",
    ("character/model/another.pac", ""),
    ids=("different-path", "missing-path"),
)
def test_archive_material_context_rejects_a_resolver_model_for_another_entry(
    tmp_path: Path,
    model_path: str,
) -> None:
    entry = ArchiveEntry(
        path="character/model/requested.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=32,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    wrong_model = SimpleNamespace(
        path=model_path,
        meshes=(
            SimpleNamespace(
                source_submesh_index=0,
                preview_texture_dds_path=str(tmp_path / "wrong.dds"),
            ),
        ),
    )
    worker = MeshArchiveMaterialContextWorker(13, entry)
    contexts: list[object] = []
    errors: list[str] = []
    worker.context_resolved.connect(
        lambda _request_id, context: contexts.append(context)
    )
    worker.error.connect(lambda _request_id, message: errors.append(message))

    with patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        return_value=SimpleNamespace(
            preview_model=wrong_model,
            dotnet_preview_package_path="",
        ),
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.acquire_dotnet_preview_package_cache_lease_for_path"
    ) as acquire_lease:
        worker.run()

    assert contexts == []
    assert len(errors) == 1
    assert "different archive entry" in errors[0]
    acquire_lease.assert_not_called()


def test_archive_browser_handoff_carries_native_package_and_companion(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/body.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    companion = ArchiveEntry(
        path="character/model/body_companion.pac",
        pamt_path=entry.pamt_path,
        paz_file=entry.paz_file,
        offset=8,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    preview_model = object()
    material_package_path = tmp_path / "native-package"
    material_package_lease = object()
    opened: list[tuple[object, dict[str, object]]] = []

    class Bridge(MeshEditorShellBridgeMixin):
        current_archive_preview_result = SimpleNamespace(
            preview_model=preview_model,
            dotnet_preview_package_path=str(material_package_path),
        )
        mesh_editor_tab = SimpleNamespace(
            open_archive_session=lambda target, **kwargs: opened.append((target, kwargs))
        )

        @staticmethod
        def _prepare_mesh_editor_archive_launch(_entry: object) -> bool:
            return True

        @staticmethod
        def _find_archive_preview_companion_entry(_entry: object) -> object:
            return companion

        @staticmethod
        def _strip_archive_preview_heavy_payloads_for_mesh_editor(_entry: object) -> None:
            pass

        @staticmethod
        def _activate_tool_widget(_widget: object) -> None:
            pass

        @staticmethod
        def set_status_message(_message: str, error: bool = False) -> None:
            del error

    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=material_package_lease,
    ):
        Bridge()._launch_archive_mesh_editor_for_entry(entry)

    assert opened == [
        (
            entry,
            {
                "material_preview_model": preview_model,
                "material_companion_entry": companion,
                "material_package_path": str(material_package_path),
                "material_package_lease": material_package_lease,
                "material_context_verified_for_rust": False,
                "material_source_identity": entry.identity,
            },
        )
    ]


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
    released: list[bool] = []
    tab.archive_material_context_package_lease = SimpleNamespace(
        release=lambda: released.append(True)
    )
    tab.close_standalone_session()
    assert released == [True]
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
    tab.standalone_controller = SimpleNamespace(
        active_session_id="direct-output-controls",
        session_view=lambda: SimpleNamespace(revision=7),
    )
    tab.standalone_native_editor_available = True
    tab.standalone_last_export_validation_report = SimpleNamespace(ok=True)
    tab.standalone_export_validation_revision = 7
    tab.standalone_dotnet_embedded_state = "launching"
    tab.standalone_dotnet_target_embedded = False

    with patch.object(tab, "_standalone_dotnet_editor_process_running", return_value=True):
        tab.update_editor_action_state(publish_native=False)

        assert tab.standalone_run_validation_report_button.isEnabled()
        assert tab.standalone_replace_from_archive_button.isEnabled()
        assert tab.standalone_export_mesh_file_button.isEnabled()
        assert tab.standalone_build_mod_button.isEnabled()
        assert tab.standalone_install_overlay_button.isEnabled()

        tab.standalone_dotnet_target_embedded = True
        tab.update_editor_action_state(publish_native=False)
        assert not tab.standalone_run_validation_report_button.isEnabled()
    app.processEvents()


def test_file_only_session_keeps_archive_outputs_disabled_after_current_validation() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "FileOnlyMeshOutputControls")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    tab.open_mesh_session(_mesh(two_parts=False), session_id="file-only-output-controls", mode="edit")
    assert tab.standalone_controller is not None
    revision = tab.standalone_controller.session_view().revision
    tab.standalone_last_export_validation_report = SimpleNamespace(ok=True)
    tab.standalone_export_validation_revision = revision

    tab.update_editor_action_state(publish_native=False)

    assert tab.standalone_run_validation_report_button.isEnabled()
    assert not tab.standalone_replace_from_archive_button.isEnabled()
    assert tab.standalone_export_mesh_file_button.isEnabled()
    assert not tab.standalone_build_mod_button.isEnabled()
    assert not tab.standalone_install_overlay_button.isEnabled()
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_hidden_standalone_panels_do_not_recompute_expensive_derived_reports() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "HiddenDirectDerivedReports"))
    tab.open_mesh_session(_mesh(two_parts=False), session_id="hidden-derived-reports", mode="edit")
    assert tab.standalone_controller is not None
    assert tab.standalone_workspace.right_panels.isHidden()

    with (
        patch.object(tab.standalone_controller, "uv_summary", side_effect=AssertionError("UV summary ran")),
        patch.object(tab.standalone_controller, "compare_summary", side_effect=AssertionError("compare summary ran")),
        patch.object(tab.standalone_controller, "export_validation_report", side_effect=AssertionError("validation ran synchronously")),
    ):
        tab.update_editor_session_state(tab.standalone_controller.session_view())

    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_geometry_revision_invalidates_cached_validation_and_output_authority() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshValidationRevisionAuthority"))
    tab.open_mesh_session(_mesh(two_parts=False), session_id="validation-revision-authority", mode="edit")
    assert tab.standalone_controller is not None
    view = tab.standalone_controller.session_view()
    tab.standalone_last_export_validation_report = MeshExportValidationReport("pac", 1, 3, 1)
    tab.standalone_export_validation_revision = view.revision
    assert tab._standalone_export_validation_ok()

    tab._refresh_standalone_export_validation(
        SimpleNamespace(session_id=view.session_id, revision=view.revision + 1)
    )

    assert tab.standalone_last_export_validation_report is not None and tab.standalone_export_validation_revision == view.revision
    assert tab.standalone_validation_panel_state.status.value == "unavailable" and tab.standalone_validation_panel_state.value is tab.standalone_last_export_validation_report
    assert not tab._standalone_export_validation_ok()
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_direct_result_update_invalidates_the_previous_revision_validation() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectResultValidationInvalidation"))
    tab.open_mesh_session(_mesh(two_parts=False), session_id="direct-result-validation", mode="edit")
    assert tab.standalone_controller is not None
    controller = tab.standalone_controller
    controller.select(vertices_by_submesh={0: (0,)}, operation="replace")
    before = controller.session_view()
    tab.standalone_last_export_validation_report = MeshExportValidationReport("pac", 1, 3, 1)
    tab.standalone_export_validation_revision = before.revision
    result = controller.apply_editor_action("transform_move", delta=(0.1, 0.0, 0.0))
    assert result.ok
    assert result.revision > before.revision

    with (
        patch.object(tab, "_apply_standalone_native_update", return_value=True),
        patch.object(tab, "_send_dotnet_native_update", return_value=True),
        patch.object(tab, "_send_dotnet_session_state", return_value=True),
    ):
        assert tab._apply_dotnet_result_update(controller, result, command_name="transform_move")

    assert tab.standalone_last_export_validation_report is not None
    update = controller.native_update_for_result(result)
    resident_revision = controller.session_view().resident_revision
    tab.standalone_dotnet_update_queue.set_context(
        session_id=controller.active_session_id,
        process_generation=1,
        renderer_revision=resident_revision,
    )
    tab.standalone_dotnet_pending_mutation_commits[17] = {
        "result": result,
        "update": update,
        "command_name": "transform_move",
        "request_payload": {},
        "commit_embedded": False,
        "resident_history": False,
        "target_revision": resident_revision,
    }
    tab._finalize_resident_mutation_ui_commit(
        {
            "request_id": 17,
            "status": "applied",
            "target_revision": resident_revision,
        }
    )

    assert tab.standalone_last_export_validation_report is not None and tab.standalone_export_validation_revision == before.revision
    assert tab.standalone_validation_panel_state.status.value == "unavailable" and tab.standalone_validation_panel_state.value is tab.standalone_last_export_validation_report
    assert not tab._standalone_export_validation_ok() and tab.standalone_workspace_panel_state.revision == result.revision and tab.standalone_uv_panel_state.revision == result.revision
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_user_output_cancel_preserves_request_correlation_until_terminal_feedback() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshOutputCancelFeedback"))

    class Stoppable:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    worker = Stoppable()
    messages: list[tuple[str, bool]] = []
    tab.status_message_requested.connect(lambda text, error=False: messages.append((text, bool(error))))
    tab.standalone_output_request_id = 41
    tab.standalone_output_worker = worker

    tab._cancel_mesh_direct_output_worker()
    tab._handle_mesh_direct_output_cancelled(41, "Mesh output cancelled.")

    assert worker.stopped
    assert tab.standalone_output_request_id == 41
    assert messages[-1] == ("Mesh output cancelled.", False)

    tab._cancel_mesh_direct_output_worker(invalidate_result=True)
    assert tab.standalone_output_request_id == 42
    tab.standalone_output_worker = None
    tab.deleteLater()
    app.processEvents()


def test_direct_dotnet_rejects_unexportable_commands_but_keeps_exact_face_delete() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectAuthoringCommandGate"))
    tab.open_mesh_session(_mesh(two_parts=False), session_id="direct-authoring-command-gate", mode="edit")
    assert tab.standalone_controller is not None
    tab.standalone_dotnet_target_controller = tab.standalone_controller
    tab.standalone_dotnet_target_embedded = False
    before_revision = tab.standalone_controller.session_view().revision
    protocol_messages: list[dict[str, object]] = []
    with patch.object(
        tab,
        "_send_dotnet_protocol_message",
        side_effect=lambda payload: protocol_messages.append(dict(payload)) or True,
    ):
        assert tab._send_dotnet_session_state()
    assert protocol_messages[-1]["exact_output_required"] is True
    results: list[tuple[tuple[object, ...], dict[str, object]]] = []
    blocked = (
        "duplicate",
        "separate",
        "subdivide",
        "refine_smooth",
        "copy",
        "paste",
        "layer_delete",
        "toggle_visibility",
    )

    with patch.object(
        tab,
        "_send_dotnet_command_result",
        side_effect=lambda *args, **kwargs: results.append((args, kwargs)) or True,
    ), patch.object(tab, "_start_dotnet_action_worker") as start_worker:
        for command in blocked:
            assert tab._handle_dotnet_command_request(
                {
                    "command": command,
                    "target_mode": "face",
                    "local_selection": {"faces_by_submesh": {"0": [0]}},
                }
            )
        assert tab._handle_dotnet_command_request(
            {
                "command": "delete",
                "target_mode": "source",
                "local_selection": {"source_indices": [0]},
            }
        )
        assert tab._handle_dotnet_command_request(
            {
                "command": "delete",
                "target_mode": "face",
                "local_selection": {"faces_by_submesh": {"0": [0]}},
            }
        )

    assert tab.standalone_controller.session_view().revision == before_revision
    assert len(results) == len(blocked) + 1
    assert all(kwargs["status"] == "unavailable" for _args, kwargs in results)
    start_worker.assert_called_once()
    safe_command = start_worker.call_args.args[1]
    assert safe_command.action == "delete"
    assert safe_command.selection is not None
    assert safe_command.selection.faces_by_submesh == ((0, (0,)),)
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_exact_output_qt_entry_points_reject_whole_part_and_duplicate_actions() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "ExactOutputQtActionGate")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    tab.open_mesh_session(_mesh(two_parts=False), session_id="exact-output-qt-actions", mode="edit")
    assert tab.standalone_controller is not None
    messages: list[tuple[str, bool]] = []
    tab.status_message_requested.connect(lambda text, error=False: messages.append((text, bool(error))))

    with patch.object(
        tab.standalone_controller,
        "run_editor_action",
        side_effect=AssertionError("blocked exact-output action reached the controller"),
    ), patch.object(
        tab,
        "_start_standalone_action_worker",
        side_effect=AssertionError("blocked exact-output action reached a worker"),
    ):
        assert not tab._handle_part_context_action("duplicate", 0)
        assert not tab._handle_part_context_action("delete", 0)
        assert tab._run_standalone_action(mesh_editor_actions_by_key()["duplicate"])

    assert messages
    assert all(error for _text, error in messages)
    assert all("unavailable" in text.lower() for text, _error in messages)
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_imported_model_direct_session_requires_explicit_free_edit_output_for_topology(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "ImportedModelAuthoringCapability"))
    mesh = _mesh(two_parts=False)
    mesh.path = "imports/new-item-model.glb"
    mesh.format = "gltf"
    tab.open_mesh_session(mesh, session_id="imported-model-authoring", mode="edit")
    assert tab.standalone_controller is not None
    tab.standalone_dotnet_target_controller = tab.standalone_controller
    tab.standalone_dotnet_target_embedded = False
    protocol_messages: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []

    with patch.object(tab, "_start_dotnet_action_worker") as start_worker, patch.object(
        tab,
        "_send_dotnet_command_result",
        side_effect=lambda _command, **payload: rejected.append(dict(payload)),
    ):
        assert tab._handle_dotnet_command_request(
            {
                "command": "duplicate",
                "target_mode": "face",
                "local_selection": {"faces_by_submesh": {"0": [0]}},
            }
        )
    start_worker.assert_not_called()
    assert rejected[-1]["status"] == "unavailable"
    assert "output folder" in rejected[-1]["diagnostics"][0]

    tab.standalone_controller.configure_output_policy(
        MeshOutputPolicy.FREE_EDIT,
        output_destination=tmp_path / "imported-model-free-edit",
    )

    with patch.object(tab, "_start_dotnet_action_worker", return_value=True) as start_worker, patch.object(
        tab,
        "_send_dotnet_command_result",
        side_effect=AssertionError("imported-model topology was rejected"),
    ):
        assert tab._handle_dotnet_command_request(
            {
                "command": "duplicate",
                "target_mode": "face",
                "local_selection": {"faces_by_submesh": {"0": [0]}},
            }
        )
    start_worker.assert_called_once()

    with patch.object(
        tab,
        "_send_dotnet_protocol_message",
        side_effect=lambda payload: protocol_messages.append(dict(payload)) or True,
    ):
        assert tab._send_dotnet_session_state()
    assert protocol_messages[-1]["exact_output_required"] is False

    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_direct_output_button_clicks_reach_each_tab_handler() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshOutputButtonClicks"))
    workspace = tab.standalone_workspace
    emitted: list[str] = []
    messages: list[tuple[str, bool]] = []
    controls = (
        ("run_validation_report_button", "validation_report_requested", "validation"),
        ("replace_from_archive_button", "replace_from_archive_requested", "replace_from_archive"),
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

    assert emitted == [
        "validation",
        "replace_from_archive",
        "export_mesh",
        "build_mod",
        "install_overlay",
        "restore_overlay",
    ]
    assert messages == [
        ("Open a mesh session before running validation.", True),
        ("Select a supported archive mesh first.", True),
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
    assert '"manager_profile": "dmm"' in metadata
    assert sorted(path.relative_to(output_root).as_posix() for path in output_root.rglob("*") if path.is_file()) == [
        "README.txt",
        "character/model/test.pac",
        "manifest.json",
        "mesh-editor-session.json",
        "modinfo.json",
    ]
    assert (pamt.read_bytes(), paz.read_bytes()) == before


@pytest.mark.parametrize(
    ("manager_profile", "payload_path", "metadata_names"),
    (
        ("dmm", "character/model/test.pac", {"manifest.json", "modinfo.json"}),
        ("jmm", "character/model/test.pac", {"mod.json"}),
        ("cdumm", "files/character/model/test.pac", {"manifest.json", "modinfo.json", ".no_encrypt"}),
        ("crimson_sharp", "files/character/model/test.pac", {"manifest.json", "mod.json", ".no_encrypt"}),
    ),
)
def test_loose_mesh_output_uses_manager_layout_and_metadata_without_touching_sources(
    tmp_path: Path,
    manager_profile: str,
    payload_path: str,
    metadata_names: set[str],
) -> None:
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

    class FakeService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert not stop_event.is_set()
            assert expected_mesh_revision == 18
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=18,
                native_edit_revision=9,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / f"mesh-mod-{manager_profile}"
    worker = MeshDirectOutputWorker(
        40,
        FakeService(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
        manager_profile=manager_profile,
        expected_mesh_revision=18,
    )
    completed: list[object] = []
    worker.completed.connect(lambda _request_id, result: completed.append(result))
    worker.run()

    assert len(completed) == 1
    assert completed[0].manager_profile == manager_profile
    assert (output_root / payload_path).read_bytes() == b"rebuilt mesh"
    assert (output_root / "README.txt").is_file()
    for name in metadata_names:
        assert (output_root / name).is_file()
    if (output_root / "manifest.json").is_file():
        manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["kind"] == "mesh_loose_mod"
        assert manifest["manager_targets"] == [manager_profile]
        assert manifest["files"][0]["path"] == entry.path
    if manager_profile == "jmm":
        mod_json = json.loads((output_root / "mod.json").read_text(encoding="utf-8"))
        assert mod_json["target"] == entry.path
        assert mod_json["files"] == [entry.path]
    session = json.loads((output_root / "mesh-editor-session.json").read_text(encoding="utf-8"))
    assert session["manager_profile"] == manager_profile
    readme_words = " ".join((output_root / "README.txt").read_text(encoding="utf-8").split())
    assert "created in the Crimson Desert Mod Workbench Mesh Editor" in readme_words
    assert (pamt.read_bytes(), paz.read_bytes()) == before


def test_loose_mesh_output_rejects_field_json_without_publishing(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "game" / "0009" / "0.pamt",
        paz_file=tmp_path / "game" / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class FakeService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert not stop_event.is_set()
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=1,
                native_edit_revision=1,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / "field-json-mesh"
    worker = MeshDirectOutputWorker(
        39,
        FakeService(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
        manager_profile="field_json",
    )
    errors: list[str] = []
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.run()

    assert len(errors) == 1
    assert "only describes DDS assets" in errors[0]
    assert not output_root.exists()


def test_loose_mesh_output_rejects_destination_claimed_during_staging(tmp_path: Path) -> None:
    from cdmw.workers import mesh_editor_workers as worker_module

    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "game" / "0009" / "0.pamt",
        paz_file=tmp_path / "game" / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class FakeService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert not stop_event.is_set()
            assert expected_mesh_revision == 6
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=6,
                native_edit_revision=3,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / "claimed-loose-mesh-mod"
    competitor_marker = output_root / "competitor.txt"
    write_readme = worker_module.write_mod_package_readme

    def claim_destination_after_staging(*args, **kwargs):
        result = write_readme(*args, **kwargs)
        output_root.mkdir()
        competitor_marker.write_bytes(b"competitor owns this destination")
        return result

    worker = MeshDirectOutputWorker(
        45,
        FakeService(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
        manager_profile="jmm",
        expected_mesh_revision=6,
    )
    errors: list[str] = []
    completed: list[object] = []
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.completed.connect(lambda _request_id, result: completed.append(result))

    with patch.object(
        worker_module,
        "write_mod_package_readme",
        side_effect=claim_destination_after_staging,
    ):
        worker.run()

    assert not completed
    assert len(errors) == 1
    assert "Mesh mod output already exists" in errors[0]
    assert competitor_marker.read_bytes() == b"competitor owns this destination"
    assert sorted(path.name for path in output_root.iterdir()) == ["competitor.txt"]
    assert not list(output_root.parent.glob(f".{output_root.name}.staging-*"))


def test_direct_output_start_pins_capture_to_the_successful_validation_revision(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "DirectMeshOutputRevisionPin"))
    tab.open_mesh_session(_mesh(two_parts=False), session_id="direct-output-revision-pin", mode="edit")
    assert tab.standalone_controller is not None
    expected_revision = tab.standalone_controller.session_view().revision
    tab.standalone_export_validation_revision = expected_revision
    captured: dict[str, object] = {}

    class CapturingOutputWorker(_ImmediateWorker):
        progress_changed = Signal(int, int, str)
        completed = Signal(int, object)
        cancelled = Signal(int, str)
        error = Signal(int, str)

        def __init__(self, *_args, **kwargs) -> None:
            super().__init__()
            captured.update(kwargs)

        def stop(self) -> None:
            pass

    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "game" / "0009" / "0.pamt",
        paz_file=tmp_path / "game" / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    with patch("cdmw.ui.mesh_editor.tab.MeshDirectOutputWorker", CapturingOutputWorker):
        assert tab._start_mesh_direct_output_worker(
            "loose_mod",
            entry,
            output_path=tmp_path / "pinned-output",
            manager_profile="jmm",
        )
        thread = tab.standalone_output_thread
        assert thread is not None
        assert thread.wait(1_000)
        app.processEvents()

    assert captured["expected_mesh_revision"] == expected_revision
    assert captured["manager_profile"] == "jmm"
    tab.close_standalone_session()
    tab.deleteLater()
    app.processEvents()


def test_direct_output_rejects_a_mesh_revision_newer_than_the_validated_revision(tmp_path: Path) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "game" / "0009" / "0.pamt",
        paz_file=tmp_path / "game" / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class StaleService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert not stop_event.is_set()
            assert expected_mesh_revision == 11
            raise RuntimeError("mesh export session changed before capture: expected revision 11, current revision 12")

    output_root = tmp_path / "stale-output"
    worker = MeshDirectOutputWorker(
        42,
        StaleService(),
        "direct-output",
        entry,
        kind="loose_mod",
        output_path=output_root,
        expected_mesh_revision=11,
    )
    errors: list[str] = []
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.run()

    assert len(errors) == 1
    assert "expected revision 11, current revision 12" in errors[0]
    assert not output_root.exists()


def test_dmm_output_publishes_one_complete_staged_directory(tmp_path: Path) -> None:
    source = tmp_path / "game" / "0009"
    source.mkdir(parents=True)
    pamt = source / "0.pamt"
    paz = source / "0.paz"
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

    class FakeService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert not stop_event.is_set()
            assert expected_mesh_revision == 12
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=12,
                native_edit_revision=7,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / "dmm-mesh-mod"

    def fake_export(_requests, *, package_root, metadata_files, **_kwargs):
        assert package_root.parent == output_root.parent
        assert package_root != output_root
        assert not output_root.exists()
        group = package_root / "0036"
        group.mkdir(parents=True)
        (group / "0.pamt").write_bytes(b"rebuilt index")
        (group / "0.paz").write_bytes(b"rebuilt payload")
        for relative, payload in metadata_files:
            target = package_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert not output_root.exists()
        return SimpleNamespace(
            package_root=package_root,
            group="0036",
            file_count=1,
            paths=(entry.path,),
            mount_list_written=False,
        )

    worker = MeshDirectOutputWorker(
        43,
        FakeService(),
        "direct-output",
        entry,
        kind="overlay_package",
        output_path=output_root,
        expected_mesh_revision=12,
    )
    completed: list[object] = []
    with patch("cdmw.workers.mesh_editor_workers.export_archive_overlay_package", side_effect=fake_export):
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.run()

    assert len(completed) == 1
    assert completed[0].output_path == output_root
    assert (output_root / "0036" / "0.pamt").read_bytes() == b"rebuilt index"
    assert (output_root / "0036" / "0.paz").read_bytes() == b"rebuilt payload"
    assert (output_root / "mesh-editor-session.json").is_file()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "archive_override_mod"
    assert manifest["structure"] == "archive_group"
    assert manifest["archive_group"] == "0036"
    assert manifest["manager_targets"] == ["dmm"]
    assert manifest["overrides"] == [entry.path]
    assert (output_root / "modinfo.json").is_file()
    assert (output_root / "README.txt").is_file()
    assert not list(output_root.parent.glob(f".{output_root.name}.staging-*"))
    assert (pamt.read_bytes(), paz.read_bytes()) == before


@pytest.mark.parametrize("cancelled", (False, True), ids=("failure", "cancel"))
def test_dmm_output_failure_or_cancel_cleans_owned_staging_without_partial_final(
    tmp_path: Path,
    cancelled: bool,
) -> None:
    entry = ArchiveEntry(
        path="character/model/test.pac",
        pamt_path=tmp_path / "game" / "0009" / "0.pamt",
        paz_file=tmp_path / "game" / "0009" / "0.paz",
        offset=0,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )

    class FakeService:
        def capture_export_snapshot(self, _session_id, *, stop_event, expected_mesh_revision):
            assert expected_mesh_revision == 5
            return SimpleNamespace(
                texture_resources=(),
                material_generation=0,
                mesh_asset_source_hash="a" * 64,
                mesh_revision=5,
                native_edit_revision=2,
            )

        def rebuild_result_from_snapshot(self, _snapshot):
            return SimpleNamespace(data=b"rebuilt mesh"), {"status": "passed"}

    output_root = tmp_path / "unfinished-dmm-mesh-mod"
    worker = MeshDirectOutputWorker(
        44,
        FakeService(),
        "direct-output",
        entry,
        kind="overlay_package",
        output_path=output_root,
        expected_mesh_revision=5,
    )

    def fail_after_partial_stage(_requests, *, package_root, **_kwargs):
        group = package_root / "0036"
        group.mkdir(parents=True)
        (group / "0.pamt").write_bytes(b"partial")
        if cancelled:
            worker.stop_event.set()
            raise RunCancelled("cancelled while staging")
        raise RuntimeError("failed while staging")

    errors: list[str] = []
    cancellations: list[str] = []
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.cancelled.connect(lambda _request_id, message: cancellations.append(message))
    with patch(
        "cdmw.workers.mesh_editor_workers.export_archive_overlay_package",
        side_effect=fail_after_partial_stage,
    ):
        worker.run()

    assert not output_root.exists()
    assert not list(output_root.parent.glob(f".{output_root.name}.staging-*"))
    if cancelled:
        assert cancellations == ["Mesh output cancelled."]
        assert not errors
    else:
        assert len(errors) == 1 and "failed while staging" in errors[0]
        assert not cancellations


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


def test_same_target_rust_session_relaunches_only_when_child_is_idle(tmp_path: Path) -> None:
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
    controller = SimpleNamespace(active_session_id="preserved-rust-session")

    class TabStub:
        standalone_controller = controller

        def __init__(self) -> None:
            self.closed = False
            self.rust_task_active = False
            self.launched: list[object] = []

        def active_builder(self):
            return None

        def has_active_standalone_session(self):
            return True

        def _current_target_entry(self):
            return current

        def _selected_mesh_editor_backend(self):
            return "rust"

        def _rust_editor_task_active(self):
            return self.rust_task_active

        def _start_selected_mesh_editor(self, active_controller):
            self.launched.append(active_controller)

        def close_standalone_session(self):
            self.closed = True

    class Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.mesh_editor_tab = TabStub()
            self._modeless_alignment_dialogs = {}
            self.activated = False
            self.statuses: list[str] = []

        def _activate_tool_widget(self, _widget):
            self.activated = True

        def set_status_message(self, message: str, **_kwargs):
            self.statuses.append(message)

    harness = Harness()

    assert harness._prepare_mesh_editor_archive_launch(current) is False
    assert harness.mesh_editor_tab.launched == [controller]
    assert harness.mesh_editor_tab.standalone_controller is controller
    assert not harness.mesh_editor_tab.closed
    assert harness.activated
    assert harness.statuses[-1] == "Launching Mesh Editor..."

    harness.mesh_editor_tab.rust_task_active = True
    assert harness._prepare_mesh_editor_archive_launch(current) is False
    assert harness.mesh_editor_tab.launched == [controller]
    assert harness.mesh_editor_tab.standalone_controller is controller
    assert not harness.mesh_editor_tab.closed
    assert harness.statuses[-1] == "Mesh Editor is already open for this target."
