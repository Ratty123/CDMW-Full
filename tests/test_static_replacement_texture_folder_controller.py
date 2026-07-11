from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from tests.static_replacement_source_support import static_replacement_ui_section_source
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.models import RunCancelled
from cdmw.ui.archive_browser.static_replacement_texture_folder_controller import (
    StaticReplacementTextureFolderScanController,
)
from cdmw.ui.archive_browser.static_replacement_texture_sources import TextureFolderScanResult
from cdmw.ui.shell.utility_controller import UtilityControllerMixin


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class _UtilityOwner(UtilityControllerMixin, QObject):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False

    def _background_task_active(self) -> bool:
        return self.worker_thread is not None

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def append_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_busy(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _handle_utility_log_message(self, _message: str) -> None:
        pass

    def _handle_utility_progress_changed(self, _current: int, _total: int, _detail: str) -> None:
        pass

    def _handle_worker_error(self, message: str) -> None:
        handler = self._utility_error_handler
        if handler is not None:
            handler(str(message))

    def _cleanup_worker_refs(self) -> None:
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None


def test_texture_folder_controller_dispatches_slow_scan_off_ui_thread(tmp_path: Path) -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = StaticReplacementTextureFolderScanController(owner, dialog)
    main_thread_id = threading.get_ident()
    worker_threads: list[int] = []
    completed: list[TextureFolderScanResult] = []
    errors: list[str] = []
    idle = threading.Event()

    def slow_scan(*_args: object, **_kwargs: object) -> TextureFolderScanResult:
        worker_threads.append(threading.get_ident())
        time.sleep(0.15)
        return TextureFolderScanResult((tmp_path / "body.dds",), scanned_entries=1)

    with mock.patch(
        "cdmw.ui.archive_browser.static_replacement_texture_folder_controller.scan_texture_source_folder",
        side_effect=slow_scan,
    ):
        before = time.perf_counter()
        started = controller.start(
            tmp_path,
            allowed_extensions=(".dds",),
            on_complete=completed.append,
            on_error=errors.append,
            on_idle=idle.set,
        )
        elapsed_ms = (time.perf_counter() - before) * 1000.0
        assert started
        assert elapsed_ms < 50.0
        assert _wait_for(app, idle.is_set)

    assert len(completed) == 1
    assert errors == []
    assert worker_threads and worker_threads[0] != main_thread_id
    assert owner.worker_thread is None
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_texture_folder_controller_close_is_nonblocking_and_rejects_stale_result(tmp_path: Path) -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = StaticReplacementTextureFolderScanController(owner, dialog)
    started = threading.Event()
    cancelled = threading.Event()
    completed: list[TextureFolderScanResult] = []

    def cancellable_scan(*_args: object, stop_event: threading.Event, **_kwargs: object) -> object:
        started.set()
        if stop_event.wait(2.0):
            cancelled.set()
            raise RunCancelled("Texture folder scan cancelled.")
        return TextureFolderScanResult(())

    with mock.patch(
        "cdmw.ui.archive_browser.static_replacement_texture_folder_controller.scan_texture_source_folder",
        side_effect=cancellable_scan,
    ):
        assert controller.start(
            tmp_path,
            allowed_extensions=(".dds",),
            on_complete=completed.append,
            on_error=lambda _message: None,
            on_idle=lambda: None,
        )
        assert started.wait(1.0)
        before = time.perf_counter()
        controller.request_shutdown()
        assert (time.perf_counter() - before) * 1000.0 < 50.0
        assert cancelled.wait(1.0)
        assert _wait_for(app, lambda: owner.worker_thread is None)

    assert completed == []
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_texture_folder_ui_handler_uses_controller_not_recursive_scan() -> None:
    source = static_replacement_ui_section_source(Path.cwd())
    start = source.index("        def _add_missing_texture_folder() -> None:")
    body = source[start : source.index("        _state.texture_filter_refresh", start)]

    assert "texture_folder_scan_controller.start(" in body
    assert "_texture_source_files_in_folder_helper(" not in body
    assert "rglob(" not in body
    assert "setattr(_state.dialog, '_texture_folder_scan_controller'" in source
    assert "texture_folder_scan_controller.request_shutdown()" in source
