"""Batch conversion output, cancellation and the actual Qt worker/provider route."""

from __future__ import annotations

import os
import struct
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from cdmw.domain.archives.catalogue import ArchiveAssociationResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
from cdmw.domain.archives.mesh_contracts import MeshExportResult
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services import archive_mesh_batch_export as service
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser import mesh_batch_export_controller as controller_module
from cdmw.ui.archive_browser.mesh_batch_export_controller import BatchMeshExportController, BatchMeshSelection, selected_batch_models
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto, _prepared
from tests.test_attachment_async_io import _UtilityOwner, _wait_for


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _entry(root: Path, path="object/triangle.pamlod"):
    data = bytearray(0x50 + 0x210 + 18 + 6)
    geometry = 0x50 + 0x210
    struct.pack_into("<II", data, 0, 1, geometry)
    struct.pack_into("<ffffff", data, 0x10, 0, 0, 0, 1, 1, 1)
    struct.pack_into("<IIII", data, 0x50, 3, 3, 0, 0)
    data[0x50 + 16:0x50 + 26] = b"stone.dds\0"
    data[0x50 + 0x110:0x50 + 0x116] = b"stone\0"
    for index, xyz in enumerate(((0, 0, 0), (65535, 0, 0), (0, 65535, 0))):
        struct.pack_into("<HHH", data, geometry + index * 6, *xyz)
    struct.pack_into("<HHH", data, geometry + 18, 0, 1, 2)
    paz = root / "source.paz"
    paz.write_bytes(data)
    return ArchiveEntry(path, root / "0.pamt", paz, 0, len(data), len(data), 0, 0)


def _request(root, entry, format="obj"):
    return service.BatchMeshExportRequest(17, entry, root / "exports", format,
                                         {entry.path: (entry,)}, {entry.basename: (entry,)})


@pytest.mark.parametrize("format", ["obj", "fbx"])
def test_actual_conversion_has_unique_folders_and_preserves_existing_output(tmp_path, format):
    entry = _entry(tmp_path)
    request = _request(tmp_path, entry, format)
    first = service.export_batch_mesh_item(request, stop_event=threading.Event())
    assert first.status == "exported", first.details
    files = {p.relative_to(first.output_directory): p.read_bytes()
             for p in first.output_directory.rglob("*") if p.is_file()}
    assert any(path.suffix == "." + format for path in files)
    second = service.export_batch_mesh_item(request, stop_event=threading.Event())
    assert second.status == "exported", second.details
    assert second.output_directory != first.output_directory
    assert all((first.output_directory / path).read_bytes() == data for path, data in files.items())
    assert not list(request.output_root.rglob(".cdmw-mesh-export-*"))


def test_cancel_before_work_creates_nothing(tmp_path, monkeypatch):
    event = threading.Event()
    event.set()
    request = _request(tmp_path, _entry(tmp_path))
    monkeypatch.setattr(service, "build_archive_preview_result", lambda *a, **k: pytest.fail("Started after cancellation"))
    assert service.export_batch_mesh_item(request, stop_event=event).status == "cancelled"
    assert not request.output_root.exists()


@pytest.mark.parametrize("failure", ["cancel", "error", "skeleton"])
def test_failed_or_cancelled_conversion_removes_only_its_empty_folder(tmp_path, monkeypatch, failure):
    request = _request(tmp_path, _entry(tmp_path), "fbx")
    request.output_root.mkdir()
    previous = request.output_root / "model_triangle"
    previous.mkdir()
    sentinel = previous / "keep.txt"
    sentinel.write_text("previous export")

    def export(*args, **kwargs):
        if failure == "cancel":
            raise RunCancelled("cancelled")
        if failure == "error":
            raise ValueError("bad geometry")
        return MeshExportResult([], (), requires_confirmation=True)

    monkeypatch.setattr(service, "export_archive_mesh", export)
    result = service.export_batch_mesh_item(request, stop_event=threading.Event())
    assert result.status == ("cancelled" if failure == "cancel" else "failed")
    assert result.output_directory is None
    assert list(request.output_root.iterdir()) == [previous]
    assert sentinel.read_text() == "previous export"


def test_references_options_and_stop_event_reach_existing_exporter(tmp_path, monkeypatch):
    entry = _entry(tmp_path, "character/body.pac")
    texture = replace(entry, path="texture/skin.dds")
    request = replace(_request(tmp_path, entry, "fbx"), allow_missing_skeleton=True)
    event = threading.Event()
    refs = (SimpleNamespace(resolved_entry=texture), SimpleNamespace(resolved_entry=texture))
    monkeypatch.setattr(service, "build_archive_preview_result", lambda *a, **k: SimpleNamespace(model_texture_references=refs, asset_family_graph="graph"))

    def export(source, output, format, **kwargs):
        assert source is entry and format == "fbx"
        assert kwargs["related_entries"] == (texture,)
        assert kwargs["model_texture_references"] == refs
        assert kwargs["allow_missing_skeleton"] and kwargs["stop_event"] is event
        assert kwargs["asset_family_graph"] == "graph" and not kwargs["build_preview_context"]
        target = output / "body.fbx"
        target.write_bytes(b"committed")
        event.set()  # A late cancellation must not relabel committed output.
        return MeshExportResult([target], ("finished",))

    monkeypatch.setattr(service, "export_archive_mesh", export)
    result = service.export_batch_mesh_item(request, stop_event=event)
    assert result.status == "exported" and result.details == ("finished",)


def _archive(owner, entries):
    archive = SimpleNamespace(shell=owner, archive_entries=entries,
        archive_entries_by_normalized_path={e.path: (e,) for e in entries},
        archive_entries_by_basename={e.basename: (e,) for e in entries})
    archive.archive = archive
    return archive


def test_worker_queue_continues_after_failure_and_never_overlaps(app, tmp_path, monkeypatch):
    owner, guard = _UtilityOwner(), QDialog()
    entries = tuple(replace(_entry(tmp_path), path=f"object/{n}.pamlod") for n in range(3))
    archive = _archive(owner, entries)
    controller = BatchMeshExportController(archive, guard, tuple(BatchMeshSelection(e) for e in entries))
    calls, progress = [], []

    def export(request, *, stop_event):
        assert threading.current_thread() is not threading.main_thread()
        calls.append(request.entry.path)
        return service.BatchMeshExportResult(request.request_id, "failed" if len(calls) == 2 else "exported", request.entry.path)

    monkeypatch.setattr(controller_module, "export_batch_mesh_item", export)
    controller.progress.connect(lambda *values: progress.append(values))
    controller.start(tmp_path, "obj", False)
    try:
        assert _wait_for(app, lambda: not controller.active)
        assert calls == [e.path for e in entries]
        assert [r.status for r in controller.results] == ["exported", "failed", "exported"]
        assert [p[0] for p in progress if p[2] == "Exporting"] == [0, 1, 2]
        assert owner.worker_thread is None
    finally:
        controller.close()
        assert _wait_for(app, lambda: owner.worker_thread is None)
        guard.close()


@pytest.mark.parametrize("committed", [False, True])
def test_cancel_during_worker_keeps_committed_success_and_stops_queue(app, tmp_path, monkeypatch, committed):
    owner, guard = _UtilityOwner(), QDialog()
    entry = _entry(tmp_path)
    selections = (BatchMeshSelection(entry), BatchMeshSelection(replace(entry, path="object/next.pamlod")))
    controller = BatchMeshExportController(_archive(owner, (entry,)), guard, selections)
    entered = threading.Event()

    def export(request, *, stop_event):
        entered.set()
        assert stop_event.wait(10)
        return service.BatchMeshExportResult(request.request_id, "exported" if committed else "cancelled", request.entry.path)

    monkeypatch.setattr(controller_module, "export_batch_mesh_item", export)
    controller.start(tmp_path, "obj", False)
    try:
        assert _wait_for(app, entered.is_set)
        controller.cancel()
        assert _wait_for(app, lambda: not controller.active)
        assert [r.status for r in controller.results] == ["exported" if committed else "cancelled", "cancelled"]
    finally:
        controller.close()
        assert _wait_for(app, lambda: owner.worker_thread is None)
        guard.close()


def test_remote_preparation_uses_each_model_and_ignores_late_result_after_cancel(app, tmp_path, monkeypatch):
    owner, guard, catalogue = _UtilityOwner(), QDialog(), _CatalogueService()
    dtos = (_dto(7, "object/a.pam"), _dto(8, "object/b.pam"))
    selections = tuple(BatchMeshSelection(ArchiveCatalogueService.compatibility_entry(dto), dto) for dto in dtos)
    archive = _archive(owner, ())
    archive.archive_catalogue_service = catalogue
    controller = BatchMeshExportController(archive, guard, selections)
    calls = []

    def export(request, *, stop_event):
        calls.append(request.entry)
        assert request.entry.prepared_path is not None
        return service.BatchMeshExportResult(request.request_id, "exported", request.entry.path)

    monkeypatch.setattr(controller_module, "export_batch_mesh_item", export)
    controller.start(tmp_path, "obj", False)
    try:
        catalogue.result_ready.emit("association-1", "find_association_candidates", ArchiveAssociationResult("session-a", 7, (), 0, False))
        catalogue.result_ready.emit("prepare-2", "prepare_entry", PrepareEntriesResult("session-a", (_prepared(dtos[0]),), 1, 1, 40))
        assert _wait_for(app, lambda: len(catalogue.requests) == 3)
        assert catalogue.requests[2][0].entry_id == 8
        generation = controller._generation
        controller.cancel()
        assert not controller.active
        assert catalogue.cancelled == ["association-3"]
        controller._preparation_failed(generation, "late error")
        assert len(calls) == 1 and [r.status for r in controller.results] == ["exported", "cancelled"]
    finally:
        controller.close()
        assert _wait_for(app, lambda: owner.worker_thread is None)
        guard.close()


def test_selection_is_file_only_deduplicated_and_not_truncated_at_512(tmp_path):
    dtos = tuple(_dto(n, f"object/{n}.pam") for n in range(520))
    nodes = [SimpleNamespace(kind="file", entry=dto) for dto in dtos]
    nodes += [nodes[0], SimpleNamespace(kind="folder"), SimpleNamespace(kind="file", entry=_dto(600, "texture/a.dds"))]
    archive = SimpleNamespace(archive_tree=SimpleNamespace(selectedItems=lambda: nodes))
    assert len(selected_batch_models(archive)) == 520


def test_dialog_close_cancels_preparation_and_leaves_final_report(app, tmp_path):
    from cdmw.ui.archive_browser.mesh_batch_export_dialog import BatchMeshExportDialog

    archive = QWidget()
    archive.shell = _UtilityOwner()
    archive.shell.settings_file_path = tmp_path / "settings.json"
    archive.archive_catalogue_service = _CatalogueService()
    dto = _dto(7, "object/a.pam")
    dialog = BatchMeshExportDialog(archive, (BatchMeshSelection(ArchiveCatalogueService.compatibility_entry(dto), dto),), "fbx")
    dialog.show()
    app.processEvents()
    dialog.start_button.click()
    assert dialog.controller.active
    dialog.close()
    assert not dialog.controller.active
    assert dialog.isVisible() and dialog.copy_button.isEnabled()
    assert "Cancelled: 1" in dialog.report.toPlainText()
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == dialog.report.toPlainText()
    dialog.close()
    archive.close()


def test_close_during_conversion_returns_promptly_and_retains_report_until_worker_stops(app, tmp_path, monkeypatch):
    from time import perf_counter
    from cdmw.ui.archive_browser.mesh_batch_export_dialog import BatchMeshExportDialog

    archive = QWidget()
    archive.shell = _UtilityOwner()
    archive.shell.settings_file_path = tmp_path / "settings.json"
    archive.archive = archive
    entry = _entry(tmp_path)
    archive.archive_entries = (entry,)
    archive.archive_entries_by_normalized_path = {entry.path: (entry,)}
    archive.archive_entries_by_basename = {entry.basename: (entry,)}
    dialog = BatchMeshExportDialog(archive, (BatchMeshSelection(entry),), "obj")
    entered, may_finish = threading.Event(), threading.Event()

    def export(request, *, stop_event):
        entered.set()
        assert stop_event.wait(10)
        assert may_finish.wait(10)
        return service.BatchMeshExportResult(request.request_id, "cancelled", request.entry.path)

    monkeypatch.setattr(controller_module, "export_batch_mesh_item", export)
    dialog.show()
    dialog.start_button.click()
    try:
        assert _wait_for(app, entered.is_set)
        start = perf_counter()
        dialog.close()
        assert perf_counter() - start < 0.1
        assert dialog.isVisible() and dialog.controller.active
        may_finish.set()
        assert _wait_for(app, lambda: not dialog.controller.active)
        assert archive.shell.worker_thread is None
        assert dialog.copy_button.isEnabled() and "Cancelled: 1" in dialog.report.toPlainText()
    finally:
        may_finish.set()
        dialog.controller.close()
        assert _wait_for(app, lambda: archive.shell.worker_thread is None)
        dialog.close()
        archive.close()


def test_incomplete_snapshot_is_reported_and_next_model_still_prepares(app, tmp_path):
    from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet

    owner, guard, catalogue = _UtilityOwner(), QDialog(), _CatalogueService()
    dtos = (_dto(7, "object/a.pam"), _dto(8, "object/b.pam"))
    selections = tuple(BatchMeshSelection(ArchiveCatalogueService.compatibility_entry(dto), dto) for dto in dtos)
    archive = _archive(owner, ())
    archive.archive_catalogue_service = catalogue
    controller = BatchMeshExportController(archive, guard, selections)
    controller.start(tmp_path, "obj", False)
    try:
        generation = controller._generation
        controller._prepared(generation, ArchivePreviewDependencySet("session-a", 7, (), {}, {}, 0, False))
        assert _wait_for(app, lambda: len(catalogue.requests) == 2)
        assert controller.results[0].status == "failed"
        assert catalogue.requests[1][0].entry_id == 8
        controller._preparation_failed(generation, "late failure")
        assert len(controller.results) == 1
        controller.cancel()
        assert [r.status for r in controller.results] == ["failed", "cancelled"]
    finally:
        controller.close()
        guard.close()
