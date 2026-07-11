from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QWidget

from cdmw.core import research_report
from cdmw.core.research import MipAnalysisRow, export_texture_analysis_report
from cdmw.models import RunCancelled
from cdmw.ui.research import analysis_controller
from cdmw.ui.research.analysis_task_controller import ResearchAnalysisTaskController
from cdmw.workers import research_analysis_workers
from cdmw.workers.research_analysis_workers import AnalysisDetailResult


_APP = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    _APP.processEvents()
    return bool(predicate())


class _ResearchHarness(QWidget):
    status_message_requested = Signal(str, bool)
    _show_mip_row_details = analysis_controller._show_mip_row_details
    _apply_analysis_detail_result = analysis_controller._apply_analysis_detail_result
    _handle_analysis_detail_error = analysis_controller._handle_analysis_detail_error
    _export_analysis_report = analysis_controller._export_analysis_report
    _handle_analysis_export_complete = analysis_controller._handle_analysis_export_complete
    _handle_analysis_export_error = analysis_controller._handle_analysis_export_error
    _handle_analysis_export_idle = analysis_controller._handle_analysis_export_idle

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.base_dir = root
        self.research_payload: dict[str, object] = {}
        self.analysis_detail_label = QLabel()
        self.analysis_detail_edit = QPlainTextEdit()
        self.analysis_status_label = QLabel()
        self.export_report_csv_button = QPushButton()
        self.export_report_json_button = QPushButton()
        self.analysis_task_controller = ResearchAnalysisTaskController(self, debounce_ms=10)
        self.get_original_root = lambda: str(root / "original")
        self.get_output_root = lambda: str(root / "output")
        self.get_texconv_path = lambda: ""

    def request_shutdown(self) -> None:
        self.analysis_task_controller.request_shutdown()


def _make_tab(tmp_path: Path) -> _ResearchHarness:
    return _ResearchHarness(tmp_path)


def _mip_row(path: str) -> MipAnalysisRow:
    return MipAnalysisRow(path, "BC7", "BC7", "4x4", "4x4", 1, 1, 0)


def _cooperative_delay(stop_event: threading.Event, seconds: float = 0.2) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if stop_event.is_set():
            raise RunCancelled("cancelled")
        time.sleep(0.005)


def test_detail_handler_is_nonblocking_heartbeats_and_latest_selection_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_detail(request, *, stop_event):
        _cooperative_delay(stop_event)
        path = dict(request.row)["relative_path"]
        return AnalysisDetailResult(request.request_id, request.kind, f"detail:{path}")

    monkeypatch.setattr(research_analysis_workers, "run_analysis_detail_request", slow_detail)
    tab = _make_tab(tmp_path)
    heartbeat = [0]
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.__setitem__(0, heartbeat[0] + 1))
    timer.start()
    try:
        started = time.perf_counter()
        tab._show_mip_row_details(_mip_row("first.dds"))
        assert time.perf_counter() - started < 0.05
        assert _wait_until(lambda: bool(tab.analysis_task_controller.iter_shutdown_workers()))

        started = time.perf_counter()
        tab._show_mip_row_details(_mip_row("second.dds"))
        assert time.perf_counter() - started < 0.05
        assert len(tab.analysis_task_controller.iter_shutdown_workers()) <= 1
        assert _wait_until(lambda: tab.analysis_detail_edit.toPlainText() == "detail:second.dds")
        assert heartbeat[0] >= 5
        assert _wait_until(lambda: not tab.analysis_task_controller.iter_shutdown_workers())
    finally:
        timer.stop()
        tab.request_shutdown()
        assert _wait_until(lambda: not tab.analysis_task_controller.iter_shutdown_workers())


def test_report_export_handler_is_nonblocking_and_keeps_ui_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "analysis.json"
    original_operation = research_analysis_workers.run_analysis_report_export
    operation_started = threading.Event()
    operation_finished = threading.Event()

    def slow_export(request, *, stop_event):
        operation_started.set()
        _cooperative_delay(stop_event, 0.3)
        result = original_operation(request, stop_event=stop_event)
        operation_finished.set()
        return result

    class Dialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return str(output_path), "JSON report (*.json)"

    monkeypatch.setattr(research_analysis_workers, "run_analysis_report_export", slow_export)
    monkeypatch.setattr(analysis_controller, "QFileDialog", Dialog)
    tab = _make_tab(tmp_path)
    tab.research_payload = {"mip_rows": [_mip_row("latest.dds")], "normal_rows": []}
    heartbeat = [0]
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.__setitem__(0, heartbeat[0] + 1))
    timer.start()
    try:
        started = time.perf_counter()
        tab._export_analysis_report(".json")
        assert time.perf_counter() - started < 0.05
        assert _wait_until(operation_started.is_set)
        assert not operation_finished.is_set()
        heartbeat_deadline = time.perf_counter() + 0.20
        while time.perf_counter() < heartbeat_deadline:
            _APP.processEvents()
            time.sleep(0.002)
        assert heartbeat[0] >= 5
        assert _wait_until(operation_finished.is_set)
        assert output_path.is_file()
        assert json.loads(output_path.read_text(encoding="utf-8"))["mip_rows"][0]["relative_path"] == "latest.dds"
        assert "Exported analysis report" in tab.analysis_status_label.text()
        assert _wait_until(lambda: not tab.analysis_task_controller.iter_shutdown_workers())
    finally:
        timer.stop()
        tab.request_shutdown()
        assert _wait_until(lambda: not tab.analysis_task_controller.iter_shutdown_workers())


def test_cancelled_or_failed_report_export_preserves_prior_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "analysis.json"
    output_path.write_text("prior", encoding="utf-8")
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RunCancelled):
        export_texture_analysis_report(output_path, [_mip_row("a.dds")], [], stop_event=stop_event)
    assert output_path.read_text(encoding="utf-8") == "prior"

    def fail_after_partial_write(handle, _payload, _stop_event):
        handle.write("partial")
        raise OSError("injected write failure")

    monkeypatch.setattr(research_report, "_write_json", fail_after_partial_write)
    with pytest.raises(OSError, match="injected write failure"):
        export_texture_analysis_report(output_path, [_mip_row("a.dds")], [])
    assert output_path.read_text(encoding="utf-8") == "prior"
    assert not list(tmp_path.glob(".analysis.json.*.tmp"))


def test_csv_report_keeps_existing_row_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "analysis.csv"
    export_texture_analysis_report(output_path, [_mip_row("schema.dds")], [])

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["report_type"] == "mip"
    assert rows[0]["path"] == "schema.dds"


def test_research_shutdown_cancels_export_without_thread_or_output_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "analysis.json"
    output_path.write_text("prior", encoding="utf-8")
    original_operation = research_analysis_workers.run_analysis_report_export

    def slow_export(request, *, stop_event):
        _cooperative_delay(stop_event)
        return original_operation(request, stop_event=stop_event)

    class Dialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return str(output_path), "JSON report (*.json)"

    monkeypatch.setattr(research_analysis_workers, "run_analysis_report_export", slow_export)
    monkeypatch.setattr(analysis_controller, "QFileDialog", Dialog)
    tab = _make_tab(tmp_path)
    tab.research_payload = {"mip_rows": [_mip_row("cancel.dds")], "normal_rows": []}
    tab._export_analysis_report(".json")
    assert _wait_until(lambda: bool(tab.analysis_task_controller.iter_shutdown_workers()))

    started = time.perf_counter()
    tab.request_shutdown()
    assert time.perf_counter() - started < 0.05
    assert _wait_until(lambda: not tab.analysis_task_controller.iter_shutdown_workers())
    assert output_path.read_text(encoding="utf-8") == "prior"
    assert not list(tmp_path.glob(".analysis.json.*.tmp"))


def test_research_tab_exposes_analysis_workers_to_shell_shutdown() -> None:
    source = Path("cdmw/ui/research/tab.py").read_text(encoding="utf-8")
    assert "self.analysis_task_controller = ResearchAnalysisTaskController(self)" in source
    assert ") + self.analysis_task_controller.iter_shutdown_workers()" in source
    assert "self.analysis_task_controller.request_shutdown()" in source
