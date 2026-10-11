from __future__ import annotations

import threading
import time

import pytest

from cdmw.core.archive_format import VfsPathResolver, parse_archive_pamt
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.new_item_provenance import SourceTracker
from cdmw.workers.new_item_lookup import NewItemPreloadGate
from tests.test_new_item_service import build_package


@pytest.mark.parametrize("finish", ["resume", "promote", "cancel"])
def test_index_preload_pauses_mid_parse_and_keeps_its_progress(tmp_path, monkeypatch, finish):
    pamt = build_package(tmp_path, {f"texture/item_{index:05}.dds": b"x" for index in range(6000)})
    expected = parse_archive_pamt(pamt)
    gate, stop = NewItemPreloadGate(), threading.Event()
    paused, finished = threading.Event(), threading.Event()
    resolved, result, failures = [], [], []
    original = VfsPathResolver.get_full_path

    def resolve(self, offset):
        value = original(self, offset)
        resolved.append(value)
        if len(resolved) == 1200:
            gate.pause()
            paused.set()
        return value

    monkeypatch.setattr(VfsPathResolver, "get_full_path", resolve)

    def run():
        try:
            result.extend(SourceTracker(None).parse_index(pamt, stop_event=gate.bind(stop)))
        except Exception as exc:
            failures.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert paused.wait(5)
        assert not finished.wait(0.08)
        # There is a checkpoint inside the large index, not just between files.
        assert 1200 <= len(resolved) < 2300
        if finish == "cancel":
            stop.set()
        else:
            getattr(gate, finish)()
        assert finished.wait(5)
        if finish == "cancel":
            assert len(failures) == 1 and isinstance(failures[0], RunCancelled)
            assert not result
        else:
            assert not failures
            assert result == expected
            assert len(resolved) < 6100  # Resumed work did not start the parse again.
    finally:
        stop.set()
        gate.resume()
        thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize("finish", ["promote", "cancel"])
def test_controller_preload_keeps_qt_responsive_and_retires_its_worker(tmp_path, finish):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from cdmw.services.new_item_service import NewItemService
    from cdmw.ui.new_item.controller import NewItemStudioController
    from tests.test_new_item_service import synthetic_files

    app = QApplication.instance() or QApplication([])
    entries = parse_archive_pamt(build_package(tmp_path, synthetic_files()))
    controller = NewItemStudioController(service=NewItemService())
    gate = NewItemPreloadGate()
    gate.pause()
    ticks = []

    def pump_until(predicate, timeout=5):
        deadline = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.001)
        assert predicate()

    try:
        assert controller.start_snapshot(entries, preload_gate=gate)
        QTimer.singleShot(0, lambda: ticks.append(True))
        pump_until(lambda: bool(ticks))
        assert controller.busy and controller.snapshot is None
        if finish == "cancel":
            controller.request_shutdown()
        else:
            gate.promote()
        pump_until(lambda: not controller.busy)
        if finish == "cancel":
            assert controller.snapshot is None
        else:
            assert controller.snapshot is not None and controller.snapshot.rows
            assert controller.snapshot.provenance.capture().indexes
        pump_until(lambda: controller._thread is None)
    finally:
        controller.request_shutdown()
        pump_until(lambda: controller._thread is None)
