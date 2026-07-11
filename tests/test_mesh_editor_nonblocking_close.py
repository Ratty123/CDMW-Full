from __future__ import annotations

import os
import time


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab


class _SlowController:
    def __init__(self) -> None:
        self.close_called = False

    def close_active_session(self) -> None:
        self.close_called = True
        time.sleep(0.25)


class _RetiringDispatcher:
    def __init__(self) -> None:
        self.cancelled = False
        self.retired: list[object] = []

    def cancel_pending(self) -> None:
        self.cancelled = True

    def retire_controller(self, controller: object) -> None:
        self.retired.append(controller)


def test_close_standalone_session_detaches_slow_controller_without_waiting() -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", "MeshEditorNonblockingClose")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    controller = _SlowController()
    dispatcher = _RetiringDispatcher()
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_live_stroke_dispatcher = dispatcher  # type: ignore[assignment]

    started = time.perf_counter()
    tab.close_standalone_session()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert tab.standalone_controller is None
    assert dispatcher.cancelled
    assert dispatcher.retired == [controller]
    assert not controller.close_called
    tab.standalone_live_stroke_dispatcher = None
    tab.deleteLater()
    app.processEvents()
