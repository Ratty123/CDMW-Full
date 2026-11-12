"""Drafts to offer after CDMW itself closed unexpectedly (P4 V4).

An unclean exit used to leave only a crash report; a draft was offered again
only when the same game file was opened. The next start now finds the drafts
autosaved while the session that died was running and offers them.

Only Mesh Editor drafts are found: a mesh opened from disk never autosaves, so
there is nothing to recover for it, and nothing is claimed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

#: A draft written up to this long after the last heartbeat still belongs to
#: the session (heartbeats are periodic; the autosave may follow the last one).
HEARTBEAT_GRACE_SECONDS = 120.0


def read_heartbeat(path: Path | str) -> dict[str, object] | None:
    """The heartbeat a session left, or None when there is none or it is unreadable."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def session_window(heartbeat: Mapping[str, object]) -> tuple[float, float] | None:
    """(start, end) of the session in epoch seconds, from its heartbeat."""

    try:
        started = float(str(heartbeat.get("started_at") or "").strip())
        last_beat = float(heartbeat.get("last_beat_epoch") or 0.0)
    except (TypeError, ValueError):
        return None
    if started > 1e11:  # the session id carries milliseconds
        started /= 1000.0
    if started <= 0 or last_beat <= 0 or last_beat < started:
        return None
    return started, last_beat + HEARTBEAT_GRACE_SECONDS


def drafts_saved_during(heartbeat: Mapping[str, object], draft_root: Path | str) -> tuple[object, ...]:
    """Mesh Editor drafts saved while the session of ``heartbeat`` ran, newest first."""

    from cdmw.services.mesh_saved_work_service import KIND_DRAFT, list_saved_work

    window = session_window(heartbeat)
    if window is None or bool(heartbeat.get("clean_shutdown")):
        return ()
    start, end = window
    return tuple(
        row for row in list_saved_work(draft_root)
        if row.kind == KIND_DRAFT and row.has_draft and start <= float(row.saved_at) <= end
    )


__all__ = ["HEARTBEAT_GRACE_SECONDS", "drafts_saved_during", "read_heartbeat", "session_window"]
