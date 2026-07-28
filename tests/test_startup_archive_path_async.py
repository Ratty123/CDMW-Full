from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.shell.startup_controller import StartupPromptMixin
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


class _StartupPromptHarness(StartupPromptMixin, QWidget):
    def __init__(self, settings: QSettings) -> None:
        QWidget.__init__(self)
        self.settings = settings
        self.current_theme_key = "graphite"
        self.show_quick_start_on_launch = True
        self.archive_package_root_edit = QLineEdit(self)
        self.probe_button = QPushButton("Probe", self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.archive_package_root_edit)
        layout.addWidget(self.probe_button)
        self.status_messages: list[str] = []
        self.log_messages: list[str] = []
        self.archive_log_messages: list[str] = []
        self.runtime_events: list[str] = []
        self._startup_archive_path_prompt_handled = False
        self._startup_archive_path_prompt_accepted = False
        self._startup_archive_path_prompt_open = False
        self._startup_archive_path_dialog = None
        self._startup_splash_window = None

    @staticmethod
    def _startup_benchmark_enabled() -> bool:
        return False

    def set_status_message(self, message: str) -> None:
        self.status_messages.append(message)

    def append_log(self, message: str) -> None:
        self.log_messages.append(message)

    def append_archive_log(self, message: str) -> None:
        self.archive_log_messages.append(message)

    def flush_settings_save(self) -> None:
        return

    def _record_runtime_event(self, event: str, **_fields: object) -> None:
        self.runtime_events.append(event)


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


def test_first_run_prompt_is_modeless_and_main_window_stays_clickable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    monkeypatch.setenv("CDMW_DEFER_TEXTURE_PREVIEW", "test-original")
    # The prompt gate returns False when this is set, so control it rather than
    # inheriting whatever an earlier test in the process left behind.
    monkeypatch.delenv("CDMW_GUI_STARTUP_SMOKE", raising=False)
    monkeypatch.setattr(StartupArchivePathDialog, "_run_initial_autodetect", lambda _self: None)
    package_root = tmp_path / "game"
    package_root.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = _StartupPromptHarness(settings)
    clicks: list[bool] = []
    continued: list[bool] = []
    window.probe_button.clicked.connect(lambda: clicks.append(True))
    window.show()

    shown = window._show_startup_archive_path_prompt_if_needed(
        None,
        on_finished=lambda: continued.append(True),
    )
    app.processEvents()

    dialog = window._startup_archive_path_dialog
    assert shown is True
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog.isModal() is False
    assert QApplication.activeModalWidget() is None

    dialog._selected_path = str(package_root)
    dialog.accept()
    _drain_until(lambda: continued == [True] and window._startup_archive_path_dialog is None)

    window.raise_()
    window.activateWindow()
    app.processEvents()
    QTest.mouseClick(window.probe_button, Qt.LeftButton)

    assert clicks == [True]
    assert QApplication.activeModalWidget() is None
    assert window.archive_package_root_edit.text() == str(package_root)
    assert settings.value("ui/startup_setup_shown", False, type=bool) is True
    assert settings.value("archive/package_root", "") == str(package_root)
    assert "startup_path_prompt_accepted" in window.runtime_events
    window.close()


def test_first_run_prompt_keeps_event_loop_alive_until_hidden_main_window_opens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    previous_quit_on_last_window_closed = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(True)
    # The prompt gate returns False when this is set, so control it rather than
    # inheriting whatever an earlier test in the process left behind.
    monkeypatch.delenv("CDMW_GUI_STARTUP_SMOKE", raising=False)
    monkeypatch.setattr(StartupArchivePathDialog, "_run_initial_autodetect", lambda _self: None)
    package_root = tmp_path / "game"
    package_root.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = _StartupPromptHarness(settings)
    continued: list[bool] = []

    def continue_after_prompt() -> None:
        continued.append(True)
        window.show()

    shown = window._show_startup_archive_path_prompt_if_needed(
        None,
        on_finished=continue_after_prompt,
    )
    dialog = window._startup_archive_path_dialog
    assert shown is True
    assert dialog is not None
    dialog._selected_path = str(package_root)

    fallback_exit = QTimer()
    fallback_exit.setSingleShot(True)
    fallback_exit.timeout.connect(lambda: app.exit(17))
    QTimer.singleShot(0, dialog.accept)
    fallback_exit.start(250)
    exit_code = app.exec()
    fallback_exit.stop()
    window_was_visible = window.isVisible()
    quit_on_last_window_closed_was_restored = app.quitOnLastWindowClosed()

    app.setQuitOnLastWindowClosed(False)
    window.close()
    app.processEvents()
    app.setQuitOnLastWindowClosed(previous_quit_on_last_window_closed)

    assert exit_code == 17
    assert continued == [True]
    assert window_was_visible is True
    assert quit_on_last_window_closed_was_restored is True


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
