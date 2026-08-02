"""Record what the user did and what the interface did back, for one session.

Nothing in this application has ever written down an interaction. A report that
the preview reloads or the panel flickers arrives with no way to reconstruct the
sequence that produced it, so every investigation starts by guessing at the
click that came first. This records the sequence: input, focus, the widgets that
showed and hid, and how hard each one was repainting while it happened.

It is off unless `CDMW_SESSION_RECORDER` is set, and it is deliberately not a
feature. The event filter runs for every event the application delivers, so its
hot path does membership tests and dictionary increments and nothing else; the
file writing happens on a daemon thread draining a queue.

Two things it will not do:

- Keystroke text is redacted. `CDMW_SESSION_RECORDER_KEYS=1` turns it on for a
  session where what was typed actually matters, and the header row records
  which way it ran, so a trail can never be mistaken for the other kind.
- Output goes to a `session-recorder/` subdirectory rather than the crash
  reports directory itself, because `latest_diagnostic_report_files()` globs
  `*.jsonl` from that directory into the shareable diagnostic bundle. A record
  of every click in a session does not belong in a file the user attaches to a
  bug report without thinking about it. The glob does not recurse, so the
  subdirectory is the whole guard.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject

RECORDER_ENV = "CDMW_SESSION_RECORDER"
RECORDER_KEYS_ENV = "CDMW_SESSION_RECORDER_KEYS"
RECORDER_DIRECTORY = "session-recorder"
RECORDER_FILENAME = "ui_session_current.jsonl"

# Buckets of repaint and layout activity, flushed on this cadence rather than
# written per event: a repainting panel produces thousands of these a second and
# the count is the interesting part, not the individual event.
_AGGREGATE_FLUSH_SECONDS = 0.25

_INPUT_EVENTS = {
    QEvent.Type.MouseButtonPress: "mouse_press",
    QEvent.Type.MouseButtonRelease: "mouse_release",
    QEvent.Type.MouseButtonDblClick: "mouse_double_click",
    QEvent.Type.Wheel: "wheel",
    QEvent.Type.KeyPress: "key_press",
}

# Show and Hide are the flicker signal itself. A pane that hides and shows
# inside the same second is the thing the reader is complaining about, and it
# is invisible in every other trail the application writes.
_VISIBILITY_EVENTS = {
    QEvent.Type.Show: "show",
    QEvent.Type.Hide: "hide",
}

_AGGREGATE_EVENTS = {
    QEvent.Type.Paint: "paint",
    QEvent.Type.LayoutRequest: "layout",
    QEvent.Type.Resize: "resize",
}

_WATCHED = frozenset(_INPUT_EVENTS) | frozenset(_VISIBILITY_EVENTS) | frozenset(_AGGREGATE_EVENTS)


def recorder_enabled() -> bool:
    return str(os.environ.get(RECORDER_ENV, "") or "").strip().lower() not in ("", "0", "false", "no")


def _keys_enabled() -> bool:
    return str(os.environ.get(RECORDER_KEYS_ENV, "") or "").strip().lower() not in ("", "0", "false", "no")


def resolve_recorder_directory() -> Optional[Path]:
    """Where the trail goes, kept out of the diagnostic bundle's reach."""

    crash_dir = str(os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    try:
        if crash_dir:
            base = Path(crash_dir)
        else:
            from cdmw.domain.workspace import workspace_paths
            from cdmw.services.settings_service import resolve_settings_file_path

            base = Path(workspace_paths(resolve_settings_file_path().parent)["crash_reports_dir"])
        directory = base / RECORDER_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        return directory
    except Exception:
        return None


def _identify(obj: QObject) -> str:
    """Name a widget the way a reader of the trail would recognise it.

    Deleted C++ objects still reach the filter, so every attribute read here is
    inside the caller's guard.
    """

    name = obj.objectName()
    class_name = type(obj).__name__
    return f"{class_name}#{name}" if name else class_name


class SessionRecorder(QObject):
    """Appends one line per interesting event; never disturbs the interface."""

    def __init__(self, directory: Path, *, record_key_text: bool) -> None:
        super().__init__()
        self._path = directory / RECORDER_FILENAME
        self._record_key_text = bool(record_key_text)
        self._queue: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=20000)
        # Rebound wholesale by the writer rather than iterated in place, so the
        # filter never holds a lock and a lost increment during the swap costs a
        # count nobody reads to the unit.
        self._aggregates: dict[tuple[str, str], int] = {}
        self._dropped = 0
        self._stopping = threading.Event()
        self._path.write_text("", encoding="utf-8")
        self._emit(
            "session_recorder_started",
            pid=os.getpid(),
            key_text_recorded=self._record_key_text,
            aggregate_flush_seconds=_AGGREGATE_FLUSH_SECONDS,
        )
        self._writer = threading.Thread(target=self._drain, name="cdmw-session-recorder", daemon=True)
        self._writer.start()

    @property
    def path(self) -> Path:
        return self._path

    def _emit(self, event: str, **fields: object) -> None:
        # time.time() rather than perf_counter: this trail is joined against
        # another process's capture, and only wall clock is comparable across
        # processes.
        row = {"t": round(time.time(), 4), "event": str(event), **fields}
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            self._dropped += 1

    def _drain(self) -> None:
        pending: list[str] = []
        last_flush = time.monotonic()
        while not self._stopping.is_set():
            try:
                row = self._queue.get(timeout=_AGGREGATE_FLUSH_SECONDS)
            except queue.Empty:
                row = None
            if row is not None:
                try:
                    pending.append(json.dumps(row, default=str))
                except Exception:
                    pass
            now = time.monotonic()
            if now - last_flush < _AGGREGATE_FLUSH_SECONDS and len(pending) < 256:
                continue
            last_flush = now
            self._flush_aggregates(pending)
            if pending:
                try:
                    with open(self._path, "a", encoding="utf-8") as handle:
                        handle.write("\n".join(pending) + "\n")
                except OSError:
                    pass
                pending.clear()

    def _flush_aggregates(self, pending: list[str]) -> None:
        counts, self._aggregates = self._aggregates, {}
        if not counts:
            return
        summary: dict[str, dict[str, int]] = {}
        for (kind, target), count in counts.items():
            summary.setdefault(kind, {})[target] = count
        for kind, targets in summary.items():
            # Only the busiest targets are worth the line; a repaint storm has a
            # clear head and a long meaningless tail.
            worst = dict(sorted(targets.items(), key=lambda item: -item[1])[:12])
            row = {
                "t": round(time.time(), 4),
                "event": f"{kind}_burst",
                "total": sum(targets.values()),
                "widgets": len(targets),
                "worst": worst,
            }
            try:
                pending.append(json.dumps(row, default=str))
            except Exception:
                pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        try:
            event_type = event.type()
            if event_type not in _WATCHED:
                return False
            aggregate = _AGGREGATE_EVENTS.get(event_type)
            if aggregate is not None:
                key = (aggregate, _identify(obj))
                self._aggregates[key] = self._aggregates.get(key, 0) + 1
                return False
            visibility = _VISIBILITY_EVENTS.get(event_type)
            if visibility is not None:
                self._emit(visibility, target=_identify(obj))
                return False
            self._record_input(_INPUT_EVENTS[event_type], obj, event)
        except Exception:
            # A diagnostic must never be the reason a click does not land.
            return False
        return False

    def _record_input(self, kind: str, obj: QObject, event: QEvent) -> None:
        fields: dict[str, object] = {"target": _identify(obj)}
        try:
            window = obj.window()
            if window is not None and window is not obj:
                fields["window"] = _identify(window)
        except Exception:
            pass
        if kind == "key_press":
            try:
                fields["key"] = int(event.key())
                fields["modifiers"] = int(event.modifiers().value)
                text = event.text()
                if text:
                    fields["text"] = text if self._record_key_text else "*"
            except Exception:
                pass
        else:
            try:
                position = event.position()
                fields["x"] = round(float(position.x()), 1)
                fields["y"] = round(float(position.y()), 1)
            except Exception:
                pass
            try:
                fields["button"] = int(event.button().value)
            except Exception:
                pass
        self._emit(kind, **fields)

    def stop(self) -> None:
        self._emit("session_recorder_stopped", dropped=self._dropped)
        self._stopping.set()
        try:
            self._writer.join(timeout=2.0)
        except RuntimeError:
            pass


def install_session_recorder(app: QObject) -> Optional[SessionRecorder]:
    """Attach the recorder to the application, or do nothing at all.

    Returns None whenever the environment has not asked for it, which is the
    normal case: an unset variable must cost one string comparison at startup
    and never install a filter.
    """

    if not recorder_enabled():
        return None
    directory = resolve_recorder_directory()
    if directory is None:
        return None
    try:
        recorder = SessionRecorder(directory, record_key_text=_keys_enabled())
    except Exception:
        return None
    app.installEventFilter(recorder)
    return recorder


__all__ = [
    "RECORDER_ENV",
    "RECORDER_KEYS_ENV",
    "SessionRecorder",
    "install_session_recorder",
    "recorder_enabled",
    "resolve_recorder_directory",
]
