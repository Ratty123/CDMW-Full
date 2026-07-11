from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.workers.mesh_editor_workers import MeshReportWriteWorker
from tests.mesh_editor_source_support import mesh_editor_tab_source


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain_until(predicate, timeout: float = 3.0) -> None:
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_report_worker_pre_cancel_preserves_existing_output(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")
    worker = MeshReportWriteWorker(1, target, "new")

    worker.stop()
    worker.run()

    assert target.read_text(encoding="utf-8") == "old"
    assert not tuple(tmp_path.glob(".report.json.*.tmp"))


def test_report_worker_mid_write_cancel_does_not_publish(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")
    worker = MeshReportWriteWorker(1, target, "new")
    entered = threading.Event()
    release = threading.Event()

    def paused_fsync(_fd: int) -> None:
        entered.set()
        assert release.wait(2.0)

    with patch("cdmw.workers.mesh_editor_workers.os.fsync", side_effect=paused_fsync):
        thread = threading.Thread(target=worker.run)
        thread.start()
        assert entered.wait(1.0)
        worker.stop()
        release.set()
        thread.join(2.0)

    assert not thread.is_alive()
    assert target.read_text(encoding="utf-8") == "old"
    assert not tuple(tmp_path.glob(".report.json.*.tmp"))


def test_report_save_handler_returns_before_slow_atomic_publish(tmp_path: Path) -> None:
    _app()
    target = tmp_path / "report.json"
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshReportAsync"))
    tab.standalone_last_rebuild_report = {"mesh_format": "pac", "warnings": ()}
    real_fsync = os.fsync

    def slow_fsync(fd: int) -> None:
        time.sleep(0.15)
        real_fsync(fd)

    with (
        patch("cdmw.ui.mesh_editor.tab.QFileDialog.getSaveFileName", return_value=(str(target), "")),
        patch("cdmw.workers.mesh_editor_workers.os.fsync", side_effect=slow_fsync),
    ):
        started = time.perf_counter()
        tab._save_standalone_rebuild_report_requested()
        elapsed = time.perf_counter() - started
        assert elapsed < 0.05
        _drain_until(lambda: tab.standalone_report_write_thread is None)

    assert '"mesh_format": "pac"' in target.read_text(encoding="utf-8")
    tab.deleteLater()


def test_report_save_ui_path_uses_tracked_worker_and_atomic_compatibility_write() -> None:
    source = mesh_editor_tab_source()
    start = source.index("def _save_standalone_rebuild_report_requested(")
    handler = source[start : source.index("def _handle_standalone_report_write_completed(", start)]
    body = source[start : source.index("def _start_standalone_native_preview_requested(", start)]
    assert "MeshReportWriteWorker(" in body
    assert "serializer=_rebuild_report_json_payload" in body
    assert "json.dumps(_rebuild_report_json_payload(report)" not in handler
    assert "target.write_text(" not in body
    assert "atomic_write_text(" in body
    assert '"standalone_report_write"' in source
