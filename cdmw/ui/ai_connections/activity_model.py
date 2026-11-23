"""The rows of the Workspace Activity drawer's AI Connection tab, fed by the server's ``ActivityFeed``.

One model per app (``ai_activity_model``), so the drawer and the AI
connections controller find it whichever is made first. The feed wakes it
from the MCP threads through a queued signal; it drains the feed on the UI
thread, collapses a call repeated with the same arguments and the same
result into one row with a count, and keeps at most ``CAP_ROWS`` rows.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal

CAP_ROWS = 300
ARGUMENTS_CHARS = 140
_KEEP_FINISHED_JOBS = 200
_ATTRIBUTE = "_cdmw_ai_activity_model"

CALL = "call"
CONNECTED = "connected"
DISCONNECTED = "disconnected"
REFUSED = "refused"


def _local_time(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ""


def short_arguments(arguments: object, limit: int = ARGUMENTS_CHARS) -> str:
    """``name=value, ...`` from the audit line's (already safe) argument summary."""

    if not isinstance(arguments, dict) or not arguments:
        return ""
    parts = []
    for name, value in arguments.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        parts.append(f"{name}={text}")
    text = ", ".join(parts)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


@dataclass
class ActivityRow:
    serial: int
    kind: str
    time: str
    tool: str = ""
    arguments: str = ""
    arguments_full: str = ""
    result: str = ""
    message: str = ""
    duration_ms: int = 0
    client: str = ""
    job: str = ""
    job_state: str = ""
    job_result: str = ""
    job_message: str = ""
    job_duration_ms: int = 0
    count: int = 1
    last_time: str = ""
    revision: int = 0

    @property
    def is_error(self) -> bool:
        if self.kind == REFUSED:
            return True
        if self.kind != CALL:
            return False
        return self.result != "ok" or self.job_result not in ("", "ok")

    def repeat_key(self) -> tuple:
        return (self.tool, self.arguments_full, self.result, self.message)

    def result_text(self) -> str:
        if self.result == "ok":
            return "ok"
        return f"{self.result}: {self.message}" if self.message else self.result

    def job_text(self) -> str:
        job = self.job
        if not job:
            return ""
        if not self.job_state or self.job_state == "running":
            return f"{job}: still running"
        seconds = f"{self.job_duration_ms / 1000:.1f} s"
        if self.job_result in ("", "ok"):
            return f"{job}: done in {seconds}"
        if self.job_state == "cancelled":
            return f"{job}: cancelled after {seconds}"
        message = self.job_message
        if message:
            return f"{job}: failed after {seconds}: {message}"
        return f"{job}: failed after {seconds}"

    def line(self) -> str:
        """One line of plain text, as Copy puts it on the clipboard."""

        if self.kind != CALL:
            return "\t".join(p for p in (self.time, self.kind, self.client, self.message) if p)
        count = f" x{self.count}" if self.count > 1 else ""
        parts = [self.time, self.tool + count, self.arguments_full, self.result_text(), f"{self.duration_ms} ms"]
        if self.job:
            parts.append(self.job_text())
        return "\t".join(parts)


class AiActivityModel(QObject):
    #: The rows or the connection state changed.
    changed = Signal()
    _wake = Signal()

    def __init__(self, parent: QObject | None = None, *, cap: int = CAP_ROWS) -> None:
        super().__init__(parent)
        self.cap = max(1, int(cap))
        self.rows: list[ActivityRow] = []
        self.listening = False
        self.connected = False
        self.client = ""
        self.since = ""
        #: Events the feed dropped because this model did not drain it in time.
        self.dropped = 0
        self.log_path: Path | None = None
        self._feed = None
        self._serial = 0
        self._finished_jobs: OrderedDict[str, dict] = OrderedDict()
        self._wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)

    # ----- the feed ------------------------------------------------------------------
    def attach(self, feed, *, log_path: Path | None = None) -> None:
        """Follow ``feed`` (UI thread); the rows already shown stay."""

        if self._feed is not None and self._feed is not feed:
            self._feed.set_waker(None)
        self._feed = feed
        if log_path is not None:
            self.log_path = Path(log_path)
        state = feed.state()
        self.connected = bool(state.get("connected"))
        self.client = str(state.get("client") or "")
        self.since = _local_time(state.get("since")) if state.get("since") else ""
        feed.set_waker(self._wake.emit)
        self.changed.emit()

    def detach(self, feed=None) -> None:
        if self._feed is None or (feed is not None and feed is not self._feed):
            return
        self._feed.set_waker(None)
        self._feed = None
        self.connected = False
        self.client = ""
        self.since = ""
        self.changed.emit()

    def set_listening(self, listening: bool) -> None:
        listening = bool(listening)
        if listening != self.listening:
            self.listening = listening
            self.changed.emit()

    def _drain(self) -> None:
        feed = self._feed
        if feed is None:
            return
        events, dropped = feed.drain()
        self.dropped += dropped
        if events or dropped:
            self.apply_events(events)

    # ----- rows -------------------------------------------------------------------------
    def clear(self) -> None:
        self.rows = []
        self.dropped = 0
        self.changed.emit()

    def apply_events(self, events) -> None:
        for event in events:
            if isinstance(event, dict):
                self._apply(event)
        if len(self.rows) > self.cap:
            del self.rows[:len(self.rows) - self.cap]
        self.changed.emit()

    def _next_serial(self) -> int:
        self._serial += 1
        return self._serial

    def _apply(self, event: dict) -> None:
        kind = event.get("kind")
        when = _local_time(event.get("time"))
        if kind == CALL:
            self._add_call(event, when)
        elif kind == "job":
            self._finish_job(event)
        elif kind == CONNECTED:
            self.connected, self.client, self.since = True, "", when
            self.rows.append(ActivityRow(self._next_serial(), CONNECTED, when))
        elif kind == "client":
            self.client = str(event.get("client") or "")
            for row in reversed(self.rows):
                if row.kind == CONNECTED:
                    if not row.client:
                        row.client = self.client
                        row.revision += 1
                    break
        elif kind == DISCONNECTED:
            self.connected, self.since = False, ""
            name = str(event.get("client") or self.client or "")
            self.client = ""
            self.rows.append(ActivityRow(self._next_serial(), DISCONNECTED, when, client=name))
        elif kind == REFUSED:
            self.rows.append(ActivityRow(self._next_serial(), REFUSED, when, message=str(event.get("message") or "")))

    def _add_call(self, event: dict, when: str) -> None:
        arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
        full = json.dumps(arguments, ensure_ascii=False, default=str, separators=(", ", ": ")) if arguments else ""
        row = ActivityRow(
            serial=0, kind=CALL, time=when, tool=str(event.get("tool") or ""),
            arguments=short_arguments(arguments), arguments_full=full,
            result=str(event.get("result") or ""), message=str(event.get("message") or ""),
            duration_ms=int(event.get("duration_ms") or 0), client=str(event.get("client") or ""),
            job=str(event.get("job") or ""), last_time=when,
        )
        last = self.rows[-1] if self.rows else None
        if (last is not None and last.kind == CALL and not last.job and not row.job
                and last.repeat_key() == row.repeat_key()):
            last.count += 1
            last.last_time = when
            last.duration_ms = row.duration_ms
            last.revision += 1
            return
        row.serial = self._next_serial()
        if row.job:
            row.job_state = "running"
            finished = self._finished_jobs.pop(row.job, None)
            if finished is not None:
                self._set_job(row, finished)
        self.rows.append(row)

    def _finish_job(self, event: dict) -> None:
        job = str(event.get("job") or "")
        if not job:
            return
        for row in reversed(self.rows):
            if row.job == job:
                self._set_job(row, event)
                row.revision += 1
                return
        # A job can end before its call's line arrives, or was answered at once (no row).
        self._finished_jobs[job] = event
        while len(self._finished_jobs) > _KEEP_FINISHED_JOBS:
            self._finished_jobs.popitem(last=False)

    @staticmethod
    def _set_job(row: ActivityRow, event: dict) -> None:
        row.job_state = str(event.get("state") or "")
        row.job_result = str(event.get("result") or "")
        row.job_message = str(event.get("message") or "")
        row.job_duration_ms = int(event.get("duration_ms") or 0)

    def formatted_text(self) -> str:
        return "\n".join(row.line() for row in self.rows)


def ai_activity_model() -> AiActivityModel | None:
    """The app's one model, made on first use; None without a Qt application."""

    app = QCoreApplication.instance()
    if app is None:
        return None
    model = getattr(app, _ATTRIBUTE, None)
    if model is None:
        model = AiActivityModel(app)
        setattr(app, _ATTRIBUTE, model)
    return model


__all__ = ["ActivityRow", "AiActivityModel", "CAP_ROWS", "ai_activity_model", "short_arguments"]
