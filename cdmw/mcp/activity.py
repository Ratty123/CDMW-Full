"""What the AI connection is doing, for the Workspace Activity drawer's AI Connection tab.

No Qt here. The server's threads publish events into a bounded buffer and
never wait for the interface: the oldest events are dropped (and counted)
when the interface does not drain the buffer, and the waker is called only
when the buffer goes from drained to pending, so a slow or closed interface
cannot back up an MCP call or flood the Qt event queue.

Events are dicts with a ``kind``:

* ``call``: the same line ``AuditLog.record`` writes to ``ai-calls.log``;
* ``connected`` and ``disconnected``: a bridge reached or left CDMW, with
  ``client`` (empty until the client says its name in ``initialize``);
* ``client``: the connected client named itself;
* ``refused``: a second app was turned away;
* ``job``: a job finished, with its ``job`` id, ``state``, ``message`` and
  ``duration_ms``.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

from cdmw.mcp.summary import summarize

#: Events held for the interface before the oldest are dropped.
BUFFER_EVENTS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ActivityFeed:
    def __init__(self, capacity: int = BUFFER_EVENTS) -> None:
        self._lock = threading.Lock()
        self._pending: deque[dict] = deque(maxlen=max(1, int(capacity)))
        self._waker: Callable[[], None] | None = None
        self._wake_pending = False
        self.dropped = 0
        #: The connection now: ``connected``, ``client`` and ``since`` (UTC ISO time).
        self._state: dict[str, object] = {"connected": False, "client": "", "since": ""}

    # ----- the interface side -------------------------------------------------
    def set_waker(self, waker: Callable[[], None] | None) -> None:
        """``waker`` is called from any thread when events wait; it must not block."""

        with self._lock:
            self._waker = waker
            self._wake_pending = False
            wake = waker is not None and bool(self._pending)
            if wake:
                self._wake_pending = True
        if wake:
            self._call_waker(waker)

    def drain(self) -> tuple[list[dict], int]:
        """The waiting events, oldest first, and how many were dropped since the last drain."""

        with self._lock:
            events = list(self._pending)
            self._pending.clear()
            dropped, self.dropped = self.dropped, 0
            self._wake_pending = False
        return events, dropped

    def state(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)

    # ----- the server side ------------------------------------------------------
    def publish(self, event: dict) -> None:
        """Never raises and never waits on the interface."""

        try:
            with self._lock:
                if len(self._pending) == self._pending.maxlen:
                    self.dropped += 1
                self._pending.append(event)
                waker = self._waker if not self._wake_pending else None
                if waker is not None:
                    self._wake_pending = True
            if waker is not None:
                self._call_waker(waker)
        except Exception:
            pass

    def _call_waker(self, waker: Callable[[], None]) -> None:
        try:
            waker()
        except Exception:
            # The interface is gone (its Qt object deleted): stop waking it.
            with self._lock:
                if self._waker is waker:
                    self._waker = None
                self._wake_pending = False

    def call(self, line: dict) -> None:
        self.publish({"kind": "call", **line})

    def connected(self) -> None:
        when = _now()
        with self._lock:
            self._state = {"connected": True, "client": "", "since": when}
        self.publish({"kind": "connected", "time": when, "client": ""})

    def client_named(self, client: str) -> None:
        with self._lock:
            if not self._state.get("connected"):
                return
            self._state["client"] = str(client or "")
        self.publish({"kind": "client", "time": _now(), "client": str(client or "")})

    def disconnected(self, client: str = "") -> None:
        with self._lock:
            name = str(client or self._state.get("client") or "")
            self._state = {"connected": False, "client": "", "since": ""}
        self.publish({"kind": "disconnected", "time": _now(), "client": name})

    def refused(self, reason: str) -> None:
        self.publish({"kind": "refused", "time": _now(), "message": str(reason or "")})

    def job_finished(self, job) -> None:
        error = getattr(job, "error", None)
        started = float(getattr(job, "started", 0.0) or 0.0)
        finished = float(getattr(job, "finished", 0.0) or time.time())
        self.publish({
            "kind": "job", "time": _now(), "job": str(getattr(job, "id", "")), "tool": str(getattr(job, "tool", "")),
            "state": str(getattr(job, "state", "")),
            "result": getattr(error, "code", "") if error is not None else "ok",
            "message": summarize(getattr(error, "message", "")) if error is not None else "",
            "duration_ms": int(round(max(0.0, finished - started) * 1000)) if started else 0,
        })


__all__ = ["ActivityFeed", "BUFFER_EVENTS"]
