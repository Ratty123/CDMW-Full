"""Build plan progress reaches Output on the UI thread and ends with its worker."""
from collections import OrderedDict
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services import new_item_template_materials as owner
from cdmw.services.new_item_service import NewItemService
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_output import OutputPanel
from cdmw.ui.new_item.state import NewItemDraft
from tests.test_new_item_template_translucency_bake import BLADE, layered_inputs
from tests.test_new_item_service import TEMPLATE, _read, build_package


def pump(app, predicate):
    deadline = time.monotonic() + 6
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_output_reports_real_plan_work_and_retires_progress(tmp_path, monkeypatch, outcome):
    app = QApplication.instance() or QApplication([])
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "game", layered_inputs())), read_entry=_read)
    controller = NewItemStudioController(service=service)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=TEMPLATE, internal_name="ProgressProbe",
        display_names={"eng": "Progress probe"}, translucency=TranslucencyChoice((BLADE,)))
    panel = OutputPanel(controller)
    entered, release = threading.Event(), threading.Event()
    original = owner._bake_material_maps
    monkeypatch.setattr(owner, "_BAKE_CACHE", OrderedDict())
    worker_threads, delivered_threads, details, ticks = [], [], [], []
    controller.operation_progress.connect(lambda *_: delivered_threads.append(threading.get_ident()))
    controller.operation_progress.connect(lambda *values: details.append(values))
    def blocked(*args):
        worker_threads.append(threading.get_ident())
        report, stop = args[-2:]
        report("Compressing colour texture...")
        entered.set()
        assert release.wait(5)
        if outcome == "failure":
            raise RuntimeError("texture compression failed")
        if outcome == "cancel":
            report("Late material progress")
            raise_if_cancelled(stop)
        return original(*args)
    monkeypatch.setattr(owner, "_bake_material_maps", blocked)
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(True))
    heartbeat.start()
    try:
        panel.build_button.click()
        pump(app, lambda: entered.is_set() and "Compressing colour texture" in panel.busy_state._plain)
        pump(app, lambda: bool(ticks))
        assert not panel.busy_bar.isHidden()
        assert (panel.busy_bar.value(), panel.busy_bar.maximum()) == (0, 1)
        assert panel._busy_timer.isActive()
        assert "Material 1/1" in panel.busy_state._plain
        assert "s)" in panel.busy_state._plain
        if outcome == "success":
            pump(app, lambda: "(1s)" in panel.busy_state._plain)
        assert worker_threads and all(t != threading.get_ident() for t in worker_threads)
        assert delivered_threads and set(delivered_threads) == {threading.get_ident()}
        controller.operation_progress.emit("model_apply", 8, 10, "Unrelated operation")
        assert "Unrelated" not in panel.busy_state._plain
        if outcome == "cancel":
            assert controller.cancel_operation("plan")
            assert "Cancelling" in panel.busy_state._plain
        release.set()
        pump(app, lambda: not controller.busy)
        assert panel.busy_bar.isHidden()
        assert not panel._busy_timer.isActive()
        if outcome == "success":
            assert controller.has_current_plan
            assert any("Planning texture registry" in d for _, _, _, d in details)
        else:
            assert not controller.has_current_plan
            assert not owner._BAKE_CACHE
        assert not any("Late material progress" in d for _, _, _, d in details)
        controller.operation_progress.emit("plan", 1, 1, "Late finished operation")
        assert "Late" not in panel.busy_state._plain
    finally:
        release.set()
        heartbeat.stop()
        controller.request_shutdown()
        pump(app, lambda: not controller.iter_shutdown_workers())
        panel.close()
        panel.deleteLater()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
