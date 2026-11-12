"""A preview's window in Browse's helper process instead of a process of its own (P4 V5).

Dialog previews (Model Library, Create New Item, placement and reference
dialogs and the rest) each started a helper. When Browse's helper offers
``viewport_open_v1``, a dialog's controller is given an ``EngineViewportChannel``
in place of the ``QProcess`` it would launch: ``start()`` asks Browse's process
to open another preview window under the dialog's host, and the controller then
drives it exactly as it drives a helper of its own. Every line of that window
names its ``viewport_id``; the resident controller hands those lines here, and
this channel adds the id to every line the dialog's controller writes.

The channel never owns the process: ``terminate`` closes the window
(``close_request``), never the process, and it reports no process id once it has
ended, so nothing can stop Browse's helper through it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable

from PySide6.QtCore import QByteArray, QObject, QProcess, QTimer, Signal

from cdmw.services.mesh_rust_contract import RUST_PREVIEW_PROTOCOL

#: What a Preview helper announces when other previews can be windows of it.
VIEWPORT_OPEN_CAPABILITY = "viewport_open_v1"
_END_EVENTS = frozenset({"viewport_closed", "viewport_refused"})


class EngineViewportChannel(QObject):
    """Another preview's window in a resident helper, shaped like a ``QProcess``."""

    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    started = Signal()
    finished = Signal(int, QProcess.ExitStatus)
    errorOccurred = Signal(QProcess.ProcessError)

    NotRunning = QProcess.ProcessState.NotRunning
    Running = QProcess.ProcessState.Running

    def __init__(self, resident: QObject, parent: QObject | None = None, *,
                 on_refused: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._resident = resident
        self._on_refused = on_refused
        self.viewport_id = uuid.uuid4().hex
        self._arguments: list[str] = []
        self._buffer = bytearray()
        self._running = False
        self._ended = False
        self.refusal = ""

    # ----- what the controller sets before start(), as on a QProcess ---------
    def setProgram(self, _program: str) -> None:  # noqa: N802 - QProcess shape
        pass

    def setArguments(self, arguments) -> None:  # noqa: N802 - QProcess shape
        self._arguments = [str(argument) for argument in arguments]

    def setWorkingDirectory(self, _directory: str) -> None:  # noqa: N802 - QProcess shape
        pass

    def setProcessChannelMode(self, _mode) -> None:  # noqa: N802 - QProcess shape
        pass

    def _argument(self, name: str) -> str:
        try:
            return self._arguments[self._arguments.index(name) + 1]
        except (ValueError, IndexError):
            return ""

    def start(self) -> None:
        manifest = self._argument("--cdmw-preview-session")
        try:
            parent_hwnd = int(self._argument("--embedded-parent-hwnd") or 0)
        except ValueError:
            parent_hwnd = 0
        opened = False
        open_viewport = getattr(self._resident, "open_viewport", None)
        if manifest and parent_hwnd > 0 and callable(open_viewport):
            try:
                opened = bool(open_viewport(self, manifest, parent_hwnd))
            except RuntimeError:
                opened = False
        if not opened:
            self._ended = True
            self._refused("Browse's preview process could not open this window.")
            QTimer.singleShot(0, self, lambda: self.errorOccurred.emit(QProcess.ProcessError.FailedToStart))
            return
        self._running = True
        QTimer.singleShot(0, self, self.started.emit)

    # ----- fed by the resident controller -----------------------------------
    def feed(self, raw_line: bytes) -> None:
        if not self._running:
            return
        line = bytes(raw_line).rstrip(b"\r\n")
        try:
            payload = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            payload = {}
        event = payload.get("event") if isinstance(payload, dict) else None
        if event in _END_EVENTS:
            if event == "viewport_refused":
                self._refused(str(payload.get("reason") or "The window could not be opened."))
            self._end(exit_code=0 if event == "viewport_closed" else 1)
            return
        if isinstance(payload, dict):
            # To the dialog's controller this is its own process's line.
            payload.pop("viewport_id", None)
            line = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._buffer += line + b"\n"
        self.readyReadStandardOutput.emit()

    def process_lost(self, exit_code: int = -1) -> None:
        """Browse's helper exited: report it as this window's crash."""

        self._end(exit_code=exit_code, crashed=True)

    # ----- what the controller calls ------------------------------------------
    def write(self, data: bytes | QByteArray) -> int:
        if not self._running:
            return -1
        lines = []
        for raw in bytes(data).splitlines():
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                return -1
            if isinstance(payload, dict):
                payload["viewport_id"] = self.viewport_id
            lines.append(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        writer = getattr(self._resident, "write_for_viewport", None)
        if not callable(writer):
            return -1
        written = int(writer(b"".join(lines)))
        return len(data) if written >= 0 else -1

    def readAllStandardOutput(self) -> QByteArray:  # noqa: N802 - QProcess shape
        data, self._buffer = bytes(self._buffer), bytearray()
        return QByteArray(data)

    def readAllStandardError(self) -> QByteArray:  # noqa: N802 - QProcess shape
        return QByteArray()

    def bytesAvailable(self) -> int:  # noqa: N802 - QProcess shape
        return len(self._buffer)

    def processId(self) -> int:  # noqa: N802 - QProcess shape
        if not self._running:
            return 0
        try:
            return int(getattr(self._resident, "process_id", 0) or 0)
        except (RuntimeError, TypeError, ValueError):
            return 0

    def state(self) -> QProcess.ProcessState:
        return self.Running if self._running else self.NotRunning

    def errorString(self) -> str:  # noqa: N802 - QProcess shape
        return self.refusal

    def terminate(self) -> None:
        """Close this window; Browse's process keeps running."""

        if self._running:
            line = json.dumps({"protocol": RUST_PREVIEW_PROTOCOL, "event": "close_request",
                               "viewport_id": self.viewport_id}, separators=(",", ":")).encode("utf-8") + b"\n"
            writer = getattr(self._resident, "write_for_viewport", None)
            if callable(writer):
                try:
                    writer(line)
                except (RuntimeError, OSError):
                    pass
        self._end(exit_code=0)

    def kill(self) -> None:
        self.terminate()

    def waitForFinished(self, _msecs: int = 30000) -> bool:  # noqa: N802 - QProcess shape
        self.terminate()
        return True

    # ----- internals -----------------------------------------------------------
    def _refused(self, reason: str) -> None:
        self.refusal = reason
        if self._on_refused is not None:
            self._on_refused(reason)

    def _end(self, *, exit_code: int = 0, crashed: bool = False) -> None:
        if not self._running:
            return
        self._running = False
        release = getattr(self._resident, "release_viewport", None)
        if callable(release):
            try:
                release(self)
            except RuntimeError:
                pass
        status = QProcess.ExitStatus.CrashExit if crashed else QProcess.ExitStatus.NormalExit
        QTimer.singleShot(0, self, lambda: self.finished.emit(int(exit_code), status))


def engine_viewport_factory(owner_refusals: dict | None = None):
    """A ``process_factory`` for a dialog's preview controller.

    It gives a window of Browse's helper when that process can open one, else a
    ``QProcess``. Once Browse's process refuses a controller's window, that
    controller launches processes of its own from then on.
    """

    from cdmw.services.engine_capture import engine_capture_router

    refused: dict = owner_refusals if owner_refusals is not None else {}

    def make(owner: QObject):
        if not refused.get(id(owner)):
            resident = engine_capture_router().resident_controller()
            blocker = getattr(resident, "viewport_blocker", None)
            if resident is not None and resident is not owner and callable(blocker) and not blocker():
                def note(_reason: str, key=id(owner)) -> None:
                    refused[key] = True

                return EngineViewportChannel(resident, owner, on_refused=note)
        return QProcess(owner)

    return make


__all__ = ["VIEWPORT_OPEN_CAPABILITY", "EngineViewportChannel", "engine_viewport_factory"]
