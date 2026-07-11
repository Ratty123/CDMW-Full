from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.process_io import append_bounded_text, stop_qprocess_async
from tests.mesh_editor_source_support import mesh_editor_tab_source


class _Signal:
    def __init__(self) -> None:
        self._callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in tuple(self._callbacks):
            callback()  # type: ignore[operator]


class _Process:
    NotRunning = 0
    Running = 1

    def __init__(self) -> None:
        self.finished = _Signal()
        self._state = self.Running
        self.terminated = False
        self.killed = False
        self.deleted = False

    def state(self) -> int:
        return self._state

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._state = self.NotRunning
        self.finished.emit()

    def deleteLater(self) -> None:
        self.deleted = True


def test_qprocess_stop_returns_immediately_then_forces_after_grace() -> None:
    app = QApplication.instance() or QApplication([])
    process = _Process()
    started = time.perf_counter()
    stop_qprocess_async(process, grace_ms=1)
    assert (time.perf_counter() - started) * 1000.0 < 50.0
    assert process.terminated and not process.killed
    deadline = time.perf_counter() + 1.0
    while not process.deleted and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert process.killed and process.deleted


def test_mesh_process_buffers_are_bounded_and_ui_has_no_blocking_waits() -> None:
    assert append_bounded_text("abc", "def", max_chars=4) == "cdef"
    source = mesh_editor_tab_source()
    assert "waitForStarted(" not in source
    assert "waitForFinished(" not in source
    assert "waitForBytesWritten(" not in source
    assert "DOTNET_PROTOCOL_BUFFER_LIMIT" in source
    assert "DOTNET_PROTOCOL_EVENT_LIMIT" in source
    assert "readyReadStandardError.connect(" in source
    assert "stop_qprocess_async(process)" in source
