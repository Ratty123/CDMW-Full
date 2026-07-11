"""Shell-owned async controller for static-replacement texture-folder scans."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QTimer

from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.archive_browser.static_replacement_qt_helpers import qt_object_is_valid
from cdmw.ui.archive_browser.static_replacement_texture_sources import (
    TextureFolderScanResult,
    scan_texture_source_folder,
)


class StaticReplacementTextureFolderScanController:
    """Dispatch a bounded scan through the shell's tracked utility worker."""

    def __init__(self, owner: object, dialog: object) -> None:
        self._owner = owner
        self._dialog = dialog
        self._request_id = 0
        self._thread: object | None = None
        self._worker: object | None = None
        self._closing = False

    @property
    def active(self) -> bool:
        thread = self._thread
        try:
            return bool(thread is not None and thread.isRunning())
        except RuntimeError:
            return False

    def start(
        self,
        selected_dir: Path | str,
        *,
        allowed_extensions: Sequence[str],
        on_complete: Callable[[TextureFolderScanResult], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None],
    ) -> bool:
        self._cancel_active()
        self._closing = False
        self._request_id += 1
        request_id = self._request_id
        background_active = getattr(self._owner, "_background_task_active", None)
        if callable(background_active) and bool(background_active()):
            on_error("Another background task is still running. Wait for it before scanning a texture folder.")
            return False
        run_task = getattr(self._owner, "_run_utility_task", None)
        if not callable(run_task):
            on_error("Texture folder scanning is unavailable in this window.")
            return False
        source = Path(str(selected_dir)).expanduser()
        extensions = tuple(str(extension or "").lower() for extension in allowed_extensions)

        def task(_log: Callable[[str], None], stop_event: object) -> object:
            return scan_texture_source_folder(
                source,
                allowed_extensions=extensions,
                stop_event=stop_event,
            )

        def complete(result: object) -> None:
            if not self._request_current(request_id):
                return
            if isinstance(result, TextureFolderScanResult):
                on_complete(result)
            else:
                on_error("Texture folder scan returned an unexpected result.")
            self._finish_when_idle(request_id, on_idle)

        def failed(message: str) -> None:
            if not self._request_current(request_id):
                return
            if not is_expected_cancellation_message(message):
                on_error(str(message))
            self._finish_when_idle(request_id, on_idle)

        previous_thread = getattr(self._owner, "worker_thread", None)
        run_task(
            status_message=f"Scanning texture folder: {source.name or source}...",
            task=task,
            on_complete=complete,
            on_error=failed,
            task_accepts_cancel=True,
        )
        thread = getattr(self._owner, "worker_thread", None)
        worker = getattr(self._owner, "utility_worker", None)
        if thread is None or thread is previous_thread or worker is None:
            on_error("Texture folder scan could not start because another task owns the worker.")
            return False
        self._thread = thread
        self._worker = worker
        return True

    def request_shutdown(self) -> None:
        self._closing = True
        self._request_id += 1
        self._cancel_active()

    def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
        if not self.active:
            return ()
        return (("texture_folder_scan", self._thread, self._worker),)

    def _request_current(self, request_id: int) -> bool:
        return bool(
            not self._closing
            and int(request_id) == int(self._request_id)
            and qt_object_is_valid(self._dialog)
        )

    def _cancel_active(self) -> None:
        worker = self._worker
        if worker is not None:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except RuntimeError:
                    pass

    def _finish_when_idle(
        self,
        request_id: int,
        callback: Callable[[], None],
        attempt: int = 0,
    ) -> None:
        if not self._request_current(request_id):
            return
        owner_still_holds_thread = getattr(self._owner, "worker_thread", None) is self._thread
        if (self.active or owner_still_holds_thread) and attempt < 500:
            QTimer.singleShot(
                10,
                lambda: self._finish_when_idle(request_id, callback, attempt + 1),
            )
            return
        self._thread = None
        self._worker = None
        callback()


__all__ = ["StaticReplacementTextureFolderScanController"]
