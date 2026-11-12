"""Off-screen package captures in a running preview process (P4 V5).

Character Finder's thumbnails used to start a renderer process each. A preview
process that offers ``package_capture_v1`` renders them instead, one at a time
on its own device, so the thumbnails add no process. Workers call
``capture_in_engine`` from their own thread; this module sends the request from
the UI thread and hands the result back. With no such process it raises
``CaptureUnavailable`` at once and the caller keeps its own capture process.
"""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot

PACKAGE_CAPTURE_CAPABILITY = "package_capture_v1"
#: As long as a capture process was given.
CAPTURE_TIMEOUT_SECONDS = 45.0


class CaptureUnavailable(RuntimeError):
    """No running preview process can take the capture; use a process of its own."""


@dataclass
class _Job:
    manifest: str
    output: str
    report: str
    size: int
    done: threading.Event = field(default_factory=threading.Event)
    status: str = ""
    message: str = ""
    cancelled: bool = False


class EngineCaptureRouter(QObject):
    _submit = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._controllers: list[weakref.ref] = []
        self._resident: list[weakref.ref] = []
        self._pending: dict[tuple[int, int], tuple[weakref.ref, _Job]] = {}
        self._submit.connect(self._send, Qt.ConnectionType.QueuedConnection)

    def register(self, controller: QObject, *, resident: bool = False) -> None:
        """A preview controller that may take captures (UI thread).

        ``resident``: its process lives as long as the app (Browse's), so it may
        also hold the Mesh Editor tab's editor window (P4 V5).
        """

        if any(ref() is controller for ref in self._controllers):
            return
        ref = weakref.ref(controller)
        self._controllers.append(ref)
        if resident:
            self._resident.append(ref)
        controller.protocol_event.connect(lambda payload, ref=ref: self._event(ref, payload))
        controller.state_changed.connect(lambda _state, _message, ref=ref: self._state(ref))
        controller.destroyed.connect(lambda *_args, ref=ref: self._forget(ref))

    def resident_controller(self) -> QObject | None:
        """The newest live resident preview controller (UI thread), if any."""

        for ref in reversed(self._resident):
            controller = ref()
            try:
                if controller is not None and controller.is_running:
                    return controller
            except RuntimeError:
                continue
        return None

    def _capable(self) -> list[QObject]:
        live = []
        for ref in reversed(self._controllers):
            controller = ref()
            if controller is None:
                continue
            try:
                if controller.is_running and PACKAGE_CAPTURE_CAPABILITY in controller.capabilities:
                    live.append(controller)
            except RuntimeError:  # deleted on the C++ side
                continue
        return live

    def capture(self, manifest: Path | str, output: Path | str, report: Path | str = "", *,
                size: int = 256, stop=None, timeout: float = CAPTURE_TIMEOUT_SECONDS) -> None:
        """Render ``manifest`` into ``output`` in a preview process (any thread).

        Raises ``CaptureUnavailable`` when no process takes it, ``TimeoutError``
        when it does not answer in time and ``RuntimeError`` when it fails.
        ``stop()`` returning true abandons the wait; the result is then dropped.
        """

        job = _Job(str(manifest), str(output), str(report or ""), int(size))
        self._submit.emit(job)
        deadline = time.monotonic() + float(timeout)
        while not job.done.wait(0.05):
            if (stop is not None and stop()) or time.monotonic() > deadline:
                job.cancelled = True
                if stop is not None and stop():
                    return
                raise TimeoutError("The preview process did not answer the thumbnail capture in time.")
        if job.status == "unavailable":
            raise CaptureUnavailable(job.message)
        if job.status != "captured":
            raise RuntimeError(job.message or "The preview process could not capture the thumbnail.")

    @Slot(object)
    def _send(self, job: _Job) -> None:
        if job.cancelled:
            return
        for controller in self._capable():
            request_id = int(controller.send_correlated("package_capture_request", {
                "manifest": job.manifest, "output": job.output, "report": job.report, "size": job.size,
            }) or 0)
            if request_id > 0:
                self._pending[(id(controller), request_id)] = (weakref.ref(controller), job)
                return
        self._finish(job, "unavailable", "No running preview process offers package captures.")

    def _event(self, ref: weakref.ref, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("event") != "package_capture_result":
            return
        controller = ref()
        try:
            request_id = int(payload.get("request_id") or 0)
        except (TypeError, ValueError):
            return
        entry = self._pending.pop((id(controller), request_id), None)
        if entry is None:
            return
        self._finish(entry[1], str(payload.get("status") or "error"), str(payload.get("message") or ""))

    def _state(self, ref: weakref.ref) -> None:
        controller = ref()
        try:
            running = controller is not None and controller.is_running
        except RuntimeError:
            running = False
        if not running:
            self._forget(ref)

    def _forget(self, ref: weakref.ref) -> None:
        """The process stopped: its captures go to a process of their own."""

        for key, (owner, job) in list(self._pending.items()):
            if owner() is None or owner() is ref():
                del self._pending[key]
                self._finish(job, "unavailable", "The preview process stopped during the capture.")

    @staticmethod
    def _finish(job: _Job, status: str, message: str) -> None:
        job.status, job.message = status, message
        job.done.set()

    def pending_count(self) -> int:
        return len(self._pending)


_router: EngineCaptureRouter | None = None


def engine_capture_router() -> EngineCaptureRouter:
    """The process-wide router; created on the UI thread by the first host."""

    global _router
    if _router is None:
        _router = EngineCaptureRouter()
    return _router


def capture_in_engine(manifest, output, report="", *, size=256, stop=None,
                      timeout=CAPTURE_TIMEOUT_SECONDS) -> None:
    """``EngineCaptureRouter.capture`` on the router, if any host made one."""

    if _router is None:
        raise CaptureUnavailable("No preview host is running.")
    _router.capture(manifest, output, report, size=size, stop=stop, timeout=timeout)


__all__ = [
    "CAPTURE_TIMEOUT_SECONDS", "CaptureUnavailable", "EngineCaptureRouter", "PACKAGE_CAPTURE_CAPABILITY",
    "capture_in_engine", "engine_capture_router",
]
