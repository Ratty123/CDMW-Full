from __future__ import annotations

import threading
import time
from types import SimpleNamespace

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


@pytest.mark.parametrize("tool,promoted", [("mod_management", False), ("new_item_studio", True)])
def test_only_the_new_item_consumer_promotes_its_preload(tmp_path, monkeypatch, tool, promoted):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
    from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin

    app = QApplication.instance() or QApplication([])
    gate = NewItemPreloadGate().bind(threading.Event())
    gate.pause()
    controller = SimpleNamespace(persist_issued_identities=lambda: None)

    class Tab(QWidget):
        status_message_requested = Signal(str, bool)
        open_archive_entry_requested = Signal(str)

        def __init__(self, **kwargs):
            super().__init__()
            self.controller = controller
            self.workflow = kwargs.get("workflow")

    monkeypatch.setattr("cdmw.ui.tools.rust_mod_management.RustModManagementTab", Tab)
    monkeypatch.setattr("cdmw.ui.new_item.rust_ui_tab.RustNewItemStudioTab", Tab)
    monkeypatch.setattr("cdmw.ui.new_item.tab.NewItemStudioTab", Tab)
    shell = SimpleNamespace(
        _new_item_preload_gate=gate, _shared_new_item_controller=lambda: controller,
        set_status_message=lambda *a, **kw: None,
        _current_archive_performance_settings=lambda: SimpleNamespace(native_preview_cache_mode="balanced"),
        textures=SimpleNamespace(_show_archive_browser_from_texture_editor=lambda *a: None),
        archive=SimpleNamespace(archive_cache_root=tmp_path, archive_package_root_edit=QLineEdit(),
                                _current_model_preview_render_settings=lambda: None),
    )
    shell.shell = shell
    tab = getattr(ShellToolTabsMixin, f"_create_{tool}_tab")(shell)
    assert tab.objectName() == tool
    assert gate.process_state() == ("run" if promoted else "pause")
    if tab.workflow is not None:
        tab.workflow.deleteLater()
    tab.deleteLater()
    app.processEvents()
