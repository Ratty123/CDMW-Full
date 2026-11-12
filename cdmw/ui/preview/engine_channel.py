"""The editor's half of Browse's helper process (P4 V3: one process, two modes).

Browse Archives' viewport is a window of a helper started in Preview mode. That
helper can also hold an edit: an ``open_session`` line on the editor protocol
switches its viewport into edit mode, keeping the window, the renderer, every
texture it uploaded and the camera. Python's Mesh Editor component drives the
edit exactly as it drives a helper of its own; this channel gives it a
QProcess-shaped view of the editor protocol's lines in that shared process.

The Preview controller owns the process. The channel only borrows it: stopping
the channel ends the edit (``leave_edit``) and never the process. When the
process exits, the channel reports a crash, as a helper of its own would.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QByteArray, QObject, QProcess, QTimer, Signal

from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL

#: What a Preview helper announces when it can edit in place.
EDIT_IN_PLACE_CAPABILITY = "edit_in_place_v1"
#: What it announces when an edit can also have a window of its own there (P4 V5).
OWN_VIEWPORT_EDIT_CAPABILITY = "own_viewport_edit_v1"
#: What it announces when it holds several edits at once, one per document (P15).
MULTI_EDIT_CAPABILITY = "multi_edit_v1"

_LEAVE_EVENTS = frozenset({"edit_left", "edit_refused"})
#: The engine's own report; the editor component does not read it.
_ENGINE_EVENTS = frozenset({"edit_entered", "edit_viewing"})


class EngineEditChannel(QObject):
    """A borrowed edit inside a Preview helper, shaped like the ``QProcess`` it replaces."""

    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    started = Signal()
    finished = Signal(int, QProcess.ExitStatus)
    errorOccurred = Signal(QProcess.ProcessError)
    #: The helper could not enter edit mode; the reason is the argument.
    refused = Signal(str)
    #: The editor shows Browse's model; its session follows (P4 V4).
    viewing_started = Signal()
    #: (child_hwnd, parent_hwnd): the edit moved into a window of its own (P4 V5).
    promoted = Signal(int, int)
    #: Why the edit could not move into a window of its own.
    promote_refused = Signal(str)

    NotRunning = QProcess.ProcessState.NotRunning
    Running = QProcess.ProcessState.Running

    def __init__(self, write: Callable[[bytes], int], process_id: Callable[[], int],
                 detach: Callable[["EngineEditChannel"], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._write = write
        self._process_id = process_id
        self._detach = detach
        self._buffer = bytearray()
        self._running = True
        self.refusal = ""
        self.entered_report: dict = {}
        self.viewing = False
        #: The edit has a window of its own in this process instead of Browse's (P4 V5).
        self.own_window = False
        #: The session this edit opened (P15): the engine routes lines by it both ways.
        self.session_id = ""

    # ----- fed by the Preview controller --------------------------------------
    def feed(self, raw_line: bytes) -> None:
        """One editor-protocol line the helper wrote."""

        if not self._running:
            return
        line = bytes(raw_line).rstrip(b"\r\n")
        try:
            payload = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            payload = {}
        event = payload.get("event") if isinstance(payload, dict) else None
        if event == "edit_promoted":
            self.own_window = True
            self.promoted.emit(int(payload.get("child_hwnd") or 0), int(payload.get("embedded_parent_hwnd") or 0))
            return
        if event == "promote_refused":
            self.promote_refused.emit(str(payload.get("reason") or "The edit could not move."))
            return
        if event in _ENGINE_EVENTS:
            if event == "edit_viewing":
                self.viewing = True
                self.viewing_started.emit()
            else:
                self.entered_report = dict(payload)
            return
        if event in _LEAVE_EVENTS:
            if event == "edit_refused":
                self.refusal = str(payload.get("reason") or "The viewport could not enter edit mode.")
                self.refused.emit(self.refusal)
            self._end(send_leave=False, exit_code=0 if event == "edit_left" else 1)
            return
        self._buffer += line + b"\n"
        self.readyReadStandardOutput.emit()

    def process_lost(self, exit_code: int = -1) -> None:
        """The helper exited while the edit was open: report it as a crash."""

        self._end(send_leave=False, exit_code=exit_code, crashed=True)

    # ----- what the Mesh Editor component calls ------------------------------
    def write(self, data: bytes | QByteArray) -> int:
        if not self._running:
            return -1
        return int(self._write(bytes(data)))

    def readAllStandardOutput(self) -> QByteArray:  # noqa: N802 - QProcess shape
        data, self._buffer = bytes(self._buffer), bytearray()
        return QByteArray(data)

    def readAllStandardError(self) -> QByteArray:  # noqa: N802 - QProcess shape
        return QByteArray()

    def bytesAvailable(self) -> int:  # noqa: N802 - QProcess shape
        return len(self._buffer)

    def processId(self) -> int:  # noqa: N802 - QProcess shape
        return int(self._process_id() or 0) if self._running else 0

    def state(self) -> QProcess.ProcessState:
        return self.Running if self._running else self.NotRunning

    def errorString(self) -> str:  # noqa: N802 - QProcess shape
        return self.refusal

    def show_view(self, *, keep_view: bool = True) -> bool:
        """Show the editor at once on Browse's model, before the session exists (P4 V4)."""

        line = self._own_line({"event": "enter_edit", "keep_view": bool(keep_view)})
        return self.write(line) == len(line)

    def promote(self, parent_hwnd: int) -> bool:
        """Ask the edit to move into a window of its own under ``parent_hwnd`` (Promote to tab)."""

        line = self._own_line({"event": "promote_edit", "parent_hwnd": int(parent_hwnd)})
        return self.write(line) == len(line)

    def hand_to(self, detach: Callable[["EngineEditChannel"], None]) -> None:
        """A new owner releases this channel when it ends."""

        self._detach = detach

    def terminate(self) -> None:
        """End the edit; the shared process keeps running."""

        self._end(send_leave=True)

    def kill(self) -> None:
        self._end(send_leave=True)

    def closeWriteChannel(self) -> None:  # noqa: N802 - QProcess shape
        self._end(send_leave=True)

    def waitForFinished(self, _msecs: int = 30000) -> bool:  # noqa: N802 - QProcess shape
        self._end(send_leave=True)
        return True

    @property
    def is_running(self) -> bool:
        return self._running

    # ----- internals ----------------------------------------------------------
    def _own_line(self, payload: dict) -> bytes:
        message = {"event": payload.pop("event"), "protocol": RUST_MESH_EDITOR_PROTOCOL, **payload}
        if self.session_id:
            message["session_id"] = self.session_id
        return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"

    def _end(self, *, send_leave: bool, exit_code: int = 0, crashed: bool = False) -> None:
        if not self._running:
            return
        self._running = False
        if send_leave:
            line = self._own_line({"event": "leave_edit"})
            try:
                self._write(line)
            except (RuntimeError, OSError):
                pass
        try:
            self._detach(self)
        except RuntimeError:
            pass
        status = QProcess.ExitStatus.CrashExit if crashed else QProcess.ExitStatus.NormalExit
        # Delivered later, as QProcess delivers finished, so a caller that stops the
        # edit is not re-entered from its own call.
        QTimer.singleShot(0, self, lambda: self.finished.emit(int(exit_code), status))


__all__ = ["EDIT_IN_PLACE_CAPABILITY", "MULTI_EDIT_CAPABILITY", "OWN_VIEWPORT_EDIT_CAPABILITY", "EngineEditChannel"]
