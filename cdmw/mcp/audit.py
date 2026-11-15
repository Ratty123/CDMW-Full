"""``workspace\\logs\\ai-calls.log``: one line per AI tool call (P13 stage C, design record 2.4 step 8).

Each line is a JSON object: the time (UTC), the client's name, the tool and
its class, a summary of its arguments (``summary.summarize_arguments``: no
secrets, no file contents, no image data), how it was approved, the result
code, the job it started and how long it took. Past 4 MiB the file becomes
``ai-calls.1.log``, replacing the previous one. A log that cannot be written
never stops the call.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from cdmw.mcp.summary import summarize, summarize_arguments

LOG_NAME = "ai-calls.log"
ROTATED_NAME = "ai-calls.1.log"
ROTATE_BYTES = 4 * 1024 * 1024


def audit_log_path() -> Path:
    from cdmw.app.app_folder import workspace_folder

    return workspace_folder() / "logs" / LOG_NAME


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.failed = ""

    @property
    def path(self) -> Path:
        return self._path or audit_log_path()

    def record(self, *, client: str, tool: str, effect: str, arguments: Mapping[str, object] | None,
               approval: str, result: str, duration_s: float, job: str = "", message: str = "",
               rows: int | None = None) -> None:
        line = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "client": summarize(str(client or "")),
            "tool": tool,
            "class": effect,
            "arguments": summarize_arguments(arguments),
            "approval": approval or "",
            "result": result,
            "duration_ms": int(round(max(0.0, duration_s) * 1000)),
        }
        if job:
            line["job"] = job
        if rows is not None:
            line["rows"] = int(rows)
        if message:
            line["message"] = summarize(message)
        text = json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                path = self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size + len(text) > ROTATE_BYTES:
                    path.replace(path.with_name(ROTATED_NAME))
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(text)
                self.failed = ""
            except OSError as exc:
                self.failed = str(exc)


class Stopwatch:
    def __init__(self) -> None:
        self.started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.started
