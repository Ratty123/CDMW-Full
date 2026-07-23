from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell.startup_dialogs import (
    StartupArchivePathDialog,
    StartupSplashDialog,
    validate_startup_archive_path,
)
from cdmw.ui.shell import startup_path_task_controller


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain_until(predicate, timeout: float = 3.0) -> None:
    app = _app()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_startup_path_validation_runs_as_pure_worker_input(tmp_path: Path) -> None:
    package_root = tmp_path / "game"
    package_root.mkdir()
    (package_root / "0.pamt").write_bytes(b"")

    source, valid, resolved = validate_startup_archive_path(str(package_root))

    assert source == str(package_root)
    assert valid is True
    assert Path(resolved) == package_root.resolve()


def test_startup_windows_cannot_leave_application_input_blocked() -> None:
    _app()
    splash = StartupSplashDialog()
    path_dialog = StartupArchivePathDialog(initial_path="skip-initial-autodetect")

    assert splash.windowFlags() & Qt.WindowTransparentForInput
    assert splash.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert path_dialog.windowModality() == Qt.NonModal

    path_dialog.reject()
    splash.finish()


def test_startup_autodetect_handler_returns_immediately_and_applies_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    package_root = tmp_path / "game"
    package_root.mkdir()

    def slow_detect(*, on_log=None, stop_event=None):
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                return []
            time.sleep(0.005)
        if on_log is not None:
            on_log("detected")
        return [package_root]

    monkeypatch.setattr(startup_path_task_controller, "autodetect_archive_package_roots", slow_detect)
    dialog = StartupArchivePathDialog(initial_path="skip-initial-autodetect")
    started = time.perf_counter()
    dialog._run_autodetect()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    _drain_until(lambda: dialog._path_task_thread is None)
    assert dialog.path_edit.text() == str(package_root)
    assert dialog.continue_button.isEnabled()
    dialog.reject()


def test_startup_autodetect_reject_is_nonblocking_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    def cancellable_detect(*, on_log=None, stop_event=None):
        while stop_event is None or not stop_event.is_set():
            time.sleep(0.005)
        return []

    monkeypatch.setattr(startup_path_task_controller, "autodetect_archive_package_roots", cancellable_detect)
    dialog = StartupArchivePathDialog(initial_path="skip-initial-autodetect")
    dialog._run_autodetect()
    started = time.perf_counter()
    dialog.reject()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    _drain_until(lambda: dialog._path_task_thread is None)


def test_startup_autodetect_source_has_no_nested_event_pump() -> None:
    source = Path("cdmw/ui/shell/startup_path_task_controller.py").read_text(encoding="utf-8")
    start = source.index("def _run_autodetect(")
    body = source[start : source.index("def _handle_autodetect_result", start)]
    assert "processEvents(" not in body
    assert "setOverrideCursor" not in body


def test_startup_path_thread_refs_survive_native_thread_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    callbacks: list[object] = []
    deleted: list[bool] = []

    class TailThread:
        def __init__(self) -> None:
            self.wait_results = [False, True]

        def wait(self, _milliseconds: int) -> bool:
            return self.wait_results.pop(0)

        def deleteLater(self) -> None:
            deleted.append(True)

    thread = TailThread()
    worker = object()
    owner = SimpleNamespace(
        _path_task_thread=thread,
        _path_task_worker=worker,
        _pending_path_task=None,
        isVisible=lambda: False,
    )
    owner._handle_path_task_finished = lambda target=None: startup_path_task_controller.StartupPathTaskControllerMixin._handle_path_task_finished(owner, target)
    monkeypatch.setattr(startup_path_task_controller.QTimer, "singleShot", lambda _ms, callback: callbacks.append(callback))

    owner._handle_path_task_finished(thread)

    assert owner._path_task_thread is thread
    assert owner._path_task_worker is worker
    assert len(callbacks) == 1
    callbacks.pop()()
    assert owner._path_task_thread is None
    assert owner._path_task_worker is None
    assert deleted == [True]
