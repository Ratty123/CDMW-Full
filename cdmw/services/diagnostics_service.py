from __future__ import annotations

import ctypes
import faulthandler
import hashlib
import json
import os
import platform
import re
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DiagnosticsService:
    settings: object | None = None
    runtime_events: list[dict[str, Any]] = field(default_factory=list)

    def record_event(self, name: str, **fields: Any) -> dict[str, Any]:
        event = {"event": str(name), **fields}
        self.runtime_events.append(event)
        return event


def crash_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"


_TRACEBACK_FRAME_RE = re.compile(r'^\s*File "([^"]+)", line (\d+), in (.+)$')
_CRASH_REPORT_HEADER_KEYS = {
    "Kind",
    "Time",
    "Version",
    "Report ID",
    "Likely Location",
    "Exception",
    "Fingerprint",
    "Process ID",
    "Session ID",
    "Python",
    "Platform",
}


def _normalize_traceback_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    lowered = normalized.lower()
    for marker in ("/cdmw/", "cdmw/", "/cdmw_app.py", "cdmw_app.py"):
        index = lowered.rfind(marker)
        if index >= 0:
            return normalized[index + (1 if marker.startswith("/") else 0) :]
    return normalized


def _is_app_traceback_path(path: str) -> bool:
    lowered = str(path or "").replace("\\", "/").lower()
    return "/cdmw/" in lowered or lowered.startswith("cdmw/") or lowered.endswith("/cdmw_app.py") or lowered == "cdmw_app.py"


def _traceback_exception_line(traceback_text: str) -> str:
    for line in reversed(str(traceback_text or "").splitlines()):
        stripped = line.strip()
        if stripped and not stripped.startswith("File ") and not stripped.startswith("Traceback "):
            return stripped[:1000]
    return ""


def traceback_diagnostic_details(traceback_text: str) -> dict[str, str]:
    frames: list[dict[str, str]] = []
    for line in str(traceback_text or "").splitlines():
        match = _TRACEBACK_FRAME_RE.match(line)
        if not match:
            continue
        raw_path, line_number, function_name = match.groups()
        display_path = _normalize_traceback_path(raw_path)
        frames.append(
            {
                "path": display_path,
                "location": f"{display_path}:{line_number} in {function_name.strip()}",
                "is_app_frame": "1" if _is_app_traceback_path(raw_path) else "",
            }
        )
    app_frame = next((frame for frame in reversed(frames) if frame["is_app_frame"]), None)
    fallback_frame = frames[-1] if frames else None
    location = (app_frame or fallback_frame or {}).get("location", "unknown")
    exception = _traceback_exception_line(traceback_text) or "unknown"
    exception_type, _separator, exception_message = exception.partition(":")
    seed = "|".join((location, exception_type.strip(), exception_message.strip() or exception))
    return {
        "likely_location": location,
        "fallback_location": (fallback_frame or {}).get("location", "unknown"),
        "exception": exception,
        "exception_type": exception_type.strip() or "unknown",
        "exception_message": exception_message.strip(),
        "fingerprint": hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:12],
    }


def crash_report_details(kind: str, title: str, body: str, *, report_id: str = "") -> dict[str, str]:
    details = traceback_diagnostic_details(body)
    if details["exception"] == "unknown":
        details["exception"] = str(title or kind or "unknown").strip()[:1000] or "unknown"
    details["report_id"] = str(report_id or "").strip()
    return details


def parse_crash_report_header(report_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in str(report_text or "").splitlines()[1:]:
        if not line.strip() and fields:
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in _CRASH_REPORT_HEADER_KEYS:
            fields[key] = value.strip()
    return fields


def crash_report_context_from_text(report_text: str) -> dict[str, object]:
    marker = "\nContext:\n"
    if marker not in str(report_text or ""):
        return {}
    try:
        parsed = json.loads(str(report_text).split(marker, 1)[1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def latest_diagnostic_report_files(
    reports_dir: Path,
    *,
    limit: int = 20,
    suffixes: frozenset[str] = frozenset({".log", ".json", ".jsonl"}),
) -> list[Path]:
    try:
        candidates = [
            path
            for path in Path(reports_dir).glob("*")
            if path.is_file() and path.suffix.lower() in suffixes
        ]
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[: max(0, int(limit))]
    except Exception:
        return []


def diagnostic_report_index(report_paths: Sequence[Path]) -> list[dict[str, object]]:
    index: list[dict[str, object]] = []
    for report_path in report_paths:
        path = Path(report_path)
        try:
            stat = path.stat()
        except OSError:
            continue
        fields: dict[str, str] = {}
        if path.suffix.lower() == ".log":
            try:
                fields = parse_crash_report_header(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                fields = {}
        item: dict[str, object] = {
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        }
        for source_key, target_key in (
            ("Report ID", "report_id"),
            ("Kind", "kind"),
            ("Time", "time"),
            ("Version", "version"),
            ("Likely Location", "likely_location"),
            ("Exception", "exception"),
            ("Fingerprint", "fingerprint"),
        ):
            if fields.get(source_key):
                item[target_key] = fields[source_key]
        index.append(item)
    return index


def _context_value(context: Mapping[str, object], key: str) -> str:
    value = context.get(key)
    if value is None:
        return "unknown"
    text = str(sanitize_runtime_event_value(value)).strip()
    return text[:1000] if text else "unknown"


def _last_operation_label(context: Mapping[str, object]) -> str:
    operation = context.get("last_active_operation")
    if isinstance(operation, Mapping):
        return _context_value(operation, "operation")
    return str(sanitize_runtime_event_value(operation)).strip()[:1000] if operation is not None else "unknown"


def format_issue_summary(
    *,
    app_title: str,
    app_version: str,
    report_path: Path | None = None,
    report_text: str = "",
    context: Mapping[str, object] | None = None,
) -> str:
    text = str(report_text or "")
    if not text and report_path is not None:
        try:
            text = Path(report_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    fields = parse_crash_report_header(text)
    report_context = dict(context or crash_report_context_from_text(text))
    report_id = fields.get("Report ID") or (Path(report_path).stem if report_path is not None else "live-context")
    return "\n".join(
        [
            f"{app_title} problem report",
            f"Version: {fields.get('Version') or app_version}",
            f"Report ID: {report_id}",
            f"Kind: {fields.get('Kind') or 'live_context'}",
            f"Likely location: {fields.get('Likely Location') or 'unknown'}",
            f"Exception: {fields.get('Exception') or 'unknown'}",
            f"Fingerprint: {fields.get('Fingerprint') or 'unknown'}",
            f"Current tab: {_context_value(report_context, 'current_tab')}",
            f"Last action: {_last_operation_label(report_context)}",
            "",
            "What I was doing:",
            "",
            "Steps to reproduce:",
            "1. ",
            "2. ",
            "3. ",
            "",
            "Expected result:",
            "",
            "Actual result:",
            "",
            "Attachment:",
            "- Diagnostic ZIP from Help > Export Diagnostics",
        ]
    )


def runtime_event_log_sibling(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def rotate_runtime_event_logs(
    path: Path,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    rotation_count: int = 3,
) -> None:
    try:
        if not path.is_file() or path.stat().st_size < max(0, int(max_bytes)):
            return
        bounded_rotation_count = max(0, int(rotation_count))
        for index in range(bounded_rotation_count, 0, -1):
            rotated = runtime_event_log_sibling(path, index)
            if index == bounded_rotation_count:
                try:
                    rotated.unlink()
                except OSError:
                    pass
                continue
            previous = runtime_event_log_sibling(path, index)
            target = runtime_event_log_sibling(path, index + 1)
            if previous.is_file():
                try:
                    previous.replace(target)
                except OSError:
                    pass
        if bounded_rotation_count > 0:
            path.replace(runtime_event_log_sibling(path, 1))
    except (OSError, ValueError, TypeError):
        pass


def sanitize_runtime_event_value(value: object, *, depth: int = 0) -> object:
    if depth > 3:
        return str(type(value).__name__)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                sanitized["..."] = f"{len(value) - index} more"
                break
            sanitized[str(key)[:80]] = sanitize_runtime_event_value(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized_items = [sanitize_runtime_event_value(item, depth=depth + 1) for item in items[:40]]
        if len(items) > 40:
            sanitized_items.append(f"{len(items) - 40} more")
        return sanitized_items
    text = str(value)
    if len(text) > 1000:
        return text[:1000] + "...<truncated>"
    return text


def append_runtime_event_log(path: Path, payload: Mapping[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_runtime_event_logs(path)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def runtime_event_child_memory(
    fields: Mapping[str, object],
    *,
    current_pid: int | None = None,
    memory_snapshot: Callable[[int], Mapping[str, int]] | None = None,
) -> dict[str, dict[str, int]]:
    if memory_snapshot is None:
        return {}
    current_process_id = os.getpid() if current_pid is None else int(current_pid)
    snapshots: dict[str, dict[str, int]] = {}
    for key in (
        "process_pid",
        "dotnet_preview_process_pid",
        "d3d11_process_pid",
        "preview_core_process_pid",
        "native_preview_core_process_pid",
    ):
        try:
            pid = int(fields.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == current_process_id:
            continue
        snapshot = dict(memory_snapshot(pid))
        if snapshot:
            snapshots[str(pid)] = snapshot
    return snapshots


class RuntimeEventRecorder:
    def __init__(
        self,
        log_path: Path,
        *,
        session_id: str,
        ring_size: int = 500,
        current_pid_fn: Callable[[], int] = os.getpid,
        memory_snapshot: Callable[[int], Mapping[str, int]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.log_path = Path(log_path)
        self.session_id = str(session_id)
        self.current_pid_fn = current_pid_fn
        self.memory_snapshot = memory_snapshot
        self.clock = clock
        self._runtime_event_ring = deque(maxlen=max(1, int(ring_size)))

    def record(self, event: str, **fields: object) -> dict[str, object]:
        timestamp = float(self.clock())
        current_pid = int(self.current_pid_fn())
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
            "pid": current_pid,
            "session_id": self.session_id,
            "event": str(event or "event"),
        }
        process_memory = dict(self.memory_snapshot(current_pid)) if self.memory_snapshot is not None else {}
        if process_memory:
            payload["process_memory"] = process_memory
        child_memory = runtime_event_child_memory(
            fields,
            current_pid=current_pid,
            memory_snapshot=self.memory_snapshot,
        )
        if child_memory:
            payload["child_process_memory"] = child_memory
        try:
            payload["memory_total_private_bytes"] = int(process_memory.get("private_bytes", 0) or 0) + sum(
                int(snapshot.get("private_bytes", 0) or 0)
                for snapshot in child_memory.values()
            )
        except Exception:
            pass
        for key, value in fields.items():
            payload[str(key)] = sanitize_runtime_event_value(value)
        self._runtime_event_ring.append(payload)
        append_runtime_event_log(self.log_path, payload)
        return payload

    def tail(self, *, limit: int = 120) -> list[dict[str, object]]:
        return list(self._runtime_event_ring)[-max(1, int(limit)) :]


def read_jsonl_tail(path: Path, *, limit: int = 80) -> list[dict[str, object]]:
    try:
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit)) :]
    except Exception:
        return []
    payloads: list[dict[str, object]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def read_crash_json_context_file(reports_dir: Path, file_name: str) -> dict[str, object] | None:
    try:
        context_path = Path(reports_dir) / file_name
        if context_path.is_file():
            payload = json.loads(context_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return None


def add_persisted_crash_breadcrumbs(
    context: dict[str, object],
    *,
    reports_dir: Path,
    runtime_event_log_path: Path,
    native_diagnostic_log_path: Path,
) -> None:
    archive_breadcrumb = read_crash_json_context_file(reports_dir, "archive_scan_breadcrumb.json")
    if archive_breadcrumb is not None:
        context["archive_scan_breadcrumb"] = archive_breadcrumb
    ui_breadcrumb = read_crash_json_context_file(reports_dir, "ui_breadcrumb.json")
    if ui_breadcrumb is not None:
        context["ui_breadcrumb"] = ui_breadcrumb
    texture_workflow_breadcrumb = read_crash_json_context_file(reports_dir, "texture_workflow_breadcrumb.json")
    if texture_workflow_breadcrumb is not None:
        context["texture_workflow_breadcrumb"] = texture_workflow_breadcrumb
    runtime_tail = read_jsonl_tail(runtime_event_log_path, limit=80)
    if runtime_tail:
        context["persisted_runtime_event_tail"] = runtime_tail
    native_tail = read_jsonl_tail(native_diagnostic_log_path, limit=80)
    if native_tail:
        context["persisted_native_event_tail"] = native_tail


def write_ui_breadcrumb(
    reports_dir: Path,
    payload: Mapping[str, object],
    *,
    session_id: str,
    pid: int | None = None,
    timestamp: float | None = None,
) -> None:
    try:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        breadcrumb_path = reports_dir / "ui_breadcrumb.json"
        enriched = dict(payload)
        enriched.setdefault("timestamp", time.time() if timestamp is None else float(timestamp))
        enriched.setdefault("pid", os.getpid() if pid is None else int(pid))
        enriched.setdefault("session_id", str(session_id))
        temp_path = breadcrumb_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(breadcrumb_path)
    except Exception:
        pass


CRASH_REPORT_CAPTURE_DEFAULT_KINDS = frozenset(
    {
        "unhandled_exception",
        "thread_exception",
        "unraisable_exception",
        "startup_failure",
        "previous_session_unclean_exit",
        "app_hang_detected",
        "native_fault_log",
    }
)


def should_write_crash_report(
    kind: str,
    *,
    capture_enabled: bool,
    force: bool = False,
    always_allowed_kinds: frozenset[str] = CRASH_REPORT_CAPTURE_DEFAULT_KINDS,
) -> bool:
    return bool(force) or bool(capture_enabled) or str(kind or "") in always_allowed_kinds


def uncaught_exception_report(exc_type: object, exc_value: object, exc_traceback: object) -> tuple[str, str, str]:
    formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    return "unhandled_exception", "Unhandled exception", formatted


def thread_exception_report(args: object) -> tuple[str, str, str]:
    formatted = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    thread_name = getattr(getattr(args, "thread", None), "name", "unknown thread")
    return "thread_exception", f"Unhandled thread exception in {thread_name}", formatted


def unraisable_exception_report(args: object) -> tuple[str, str, str]:
    formatted = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    return "unraisable_exception", f"Unraisable exception from {getattr(args, 'object', None)!r}", formatted


def write_crash_report(
    reports_dir: Path,
    kind: str,
    title: str,
    body: str,
    *,
    app_title: str,
    app_version: str,
    session_id: str,
    context: Mapping[str, object] | None = None,
    pid: int | None = None,
    python_version: str | None = None,
    platform_label: str | None = None,
    timestamp: str | None = None,
) -> Path | None:
    try:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        process_id = os.getpid() if pid is None else int(pid)
        timestamp_value = crash_timestamp()
        report_path = reports_dir / f"{kind}_{timestamp_value}_{process_id}.log"
        details = crash_report_details(kind, title, body, report_id=report_path.stem)
        lines = [
            f"{app_title} crash/details report",
            f"Kind: {kind}",
            f"Time: {timestamp or time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Version: {app_version}",
            f"Report ID: {details['report_id']}",
            f"Likely Location: {details['likely_location']}",
            f"Exception: {details['exception']}",
            f"Fingerprint: {details['fingerprint']}",
            f"Process ID: {process_id}",
            f"Session ID: {session_id}",
            f"Python: {python_version or sys.version}",
            f"Platform: {platform_label or platform.platform()}",
            "",
            str(title).strip(),
            "",
            str(body).rstrip(),
        ]
        if context:
            lines.extend(["", "Context:", json.dumps(dict(context), indent=2, ensure_ascii=False)])
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
    except Exception:
        return None


def write_heartbeat_file(path: Path, payload: Mapping[str, object]) -> None:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass


def enable_native_fault_log(
    reports_dir: Path,
    *,
    fault_handler: object = faulthandler,
) -> object | None:
    try:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        fault_log_handle = (reports_dir / "native_fault_current.log").open("a", encoding="utf-8")
        fault_log_handle.flush()
        fault_handler.enable(file=fault_log_handle, all_threads=True)  # type: ignore[attr-defined]
        return fault_log_handle
    except Exception:
        return None


def cleanup_native_fault_log_on_exit(
    fault_log_handle: object | None,
    reports_dir: Path,
    *,
    clean_exit: bool,
    fault_handler: object = faulthandler,
) -> None:
    try:
        if fault_log_handle is None:
            return
        fault_log_path = Path(reports_dir) / "native_fault_current.log"
        if clean_exit:
            try:
                fault_handler.disable()  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            fault_log_handle.flush()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            fault_log_handle.close()  # type: ignore[attr-defined]
        except Exception:
            pass
        if clean_exit:
            try:
                if fault_log_path.is_file() and fault_log_path.stat().st_size == 0:
                    fault_log_path.unlink()
            except Exception:
                pass
    except Exception:
        pass
def process_is_alive(pid_value: object) -> bool:
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def crash_report_kind_already_covers_session(
    reports_dir: Path,
    kind: str,
    session_id: str,
    *,
    limit: int = 80,
) -> bool:
    normalized_kind = str(kind or "").strip()
    normalized_session = str(session_id or "").strip()
    if not normalized_kind or not normalized_session:
        return False
    try:
        candidates = sorted(
            reports_dir.glob(f"{normalized_kind}_*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return False
    for report_path in candidates[: max(1, int(limit))]:
        try:
            text = report_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if normalized_session in text:
            return True
    return False


def check_previous_unclean_exit(
    heartbeat_path: Path,
    *,
    session_id: str,
    reports_dir: Path,
    process_is_alive_fn: Callable[[object], bool] = process_is_alive,
    add_breadcrumbs_fn: Callable[[dict[str, object]], None] | None = None,
    write_crash_report_fn: Callable[..., object] | None = None,
    record_runtime_event_fn: Callable[..., object] | None = None,
    duplicate_report_checker: Callable[[Path, str, str], bool] = crash_report_kind_already_covers_session,
    now: float | None = None,
) -> bool:
    try:
        heartbeat_path = Path(heartbeat_path)
        if not heartbeat_path.is_file():
            return False
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        if bool(payload.get("clean_shutdown")):
            return False
        if str(payload.get("session_id") or "") == session_id:
            return False
        last_beat = float(payload.get("last_beat_epoch") or 0.0)
        now_epoch = time.time() if now is None else float(now)
        age_s = max(0.0, now_epoch - last_beat) if last_beat > 0 else 0.0
        previous_pid_alive = process_is_alive_fn(payload.get("pid"))
        if age_s < 20.0 and previous_pid_alive:
            return False
        previous_session_id = str(payload.get("session_id") or "").strip()
        if duplicate_report_checker(Path(reports_dir), "previous_session_unclean_exit", previous_session_id):
            if record_runtime_event_fn is not None:
                record_runtime_event_fn(
                    "previous_session_unclean_exit_suppressed_duplicate",
                    previous_session_id=previous_session_id,
                    heartbeat_age_seconds=round(age_s, 3),
                    previous_pid_alive=previous_pid_alive,
                )
            return True
        previous_context: dict[str, object] = {
            "previous_heartbeat": payload,
            "heartbeat_age_seconds": round(age_s, 3),
            "previous_pid_alive": previous_pid_alive,
        }
        if add_breadcrumbs_fn is not None:
            add_breadcrumbs_fn(previous_context)
        if write_crash_report_fn is not None:
            write_crash_report_fn(
                "previous_session_unclean_exit",
                "Previous session did not shut down cleanly",
                (
                    "The previous app session left an active heartbeat file. "
                    "This usually means the process crashed, froze and was force-closed, or Windows terminated it."
                ),
                context=previous_context,
                force=True,
            )
        return True
    except Exception as exc:
        if write_crash_report_fn is not None:
            write_crash_report_fn(
                "previous_session_heartbeat_read_error",
                "Could not inspect previous heartbeat",
                str(exc),
                force=True,
            )
        return False


def format_thread_dump() -> str:
    frames = sys._current_frames()
    thread_names = {thread.ident: thread.name for thread in threading.enumerate()}
    parts: list[str] = []
    for thread_id, frame in sorted(frames.items(), key=lambda item: str(thread_names.get(item[0], item[0]))):
        parts.append(f"\n--- Thread {thread_names.get(thread_id, 'unknown')} ({thread_id}) ---")
        parts.extend(traceback.format_stack(frame))
    return "".join(parts).strip()


def start_hang_watchdog(
    stop_event: threading.Event,
    last_heartbeat_written_at_fn: Callable[[], float],
    write_crash_report_fn: Callable[..., object],
    *,
    interval_seconds: float = 10.0,
    stale_seconds: float = 45.0,
    recovered_seconds: float = 15.0,
    thread_name: str = "cdmw-hang-watchdog",
    format_thread_dump_fn: Callable[[], str] = format_thread_dump,
) -> threading.Thread:
    def _watchdog() -> None:
        reported_stale = False
        while not stop_event.wait(max(0.001, float(interval_seconds))):
            age_s = time.time() - float(last_heartbeat_written_at_fn())
            if age_s >= stale_seconds and not reported_stale:
                reported_stale = True
                write_crash_report_fn(
                    "app_hang_detected",
                    "GUI heartbeat stalled",
                    (
                        f"The GUI heartbeat has not advanced for {age_s:.1f} seconds. "
                        "If the app later recovered, this report still marks the stall point."
                    ),
                    context={
                        "heartbeat_age_seconds": round(age_s, 3),
                        "thread_dump": format_thread_dump_fn(),
                    },
                    force=True,
                )
            elif age_s < recovered_seconds:
                reported_stale = False

    thread = threading.Thread(target=_watchdog, name=thread_name, daemon=True)
    thread.start()
    return thread


def heartbeat_payload(
    app_title: str,
    app_version: str,
    session_id: str,
    phase: str,
    *,
    clean_shutdown: bool = False,
    pid: int | None = None,
    now: float | None = None,
    platform_label: str | None = None,
) -> dict[str, object]:
    beat_epoch = time.time() if now is None else float(now)
    return {
        "app": str(app_title),
        "version": str(app_version),
        "pid": os.getpid() if pid is None else int(pid),
        "session_id": str(session_id),
        "phase": str(phase or "running"),
        "clean_shutdown": bool(clean_shutdown),
        "started_at": str(session_id).split("-", 1)[-1],
        "last_beat_epoch": beat_epoch,
        "last_beat": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(beat_epoch)),
        "platform": platform.platform() if platform_label is None else str(platform_label),
    }


def write_app_heartbeat(
    heartbeat_path: Path,
    *,
    app_title: str,
    app_version: str,
    session_id: str,
    phase: str,
    clean_shutdown: bool = False,
    platform_label: str | None = None,
) -> dict[str, object]:
    payload = heartbeat_payload(
        app_title,
        app_version,
        session_id,
        phase,
        clean_shutdown=clean_shutdown,
        platform_label=platform_label,
    )
    write_heartbeat_file(heartbeat_path, payload)
    return payload
def timing_value(timings: Mapping[str, object] | None, key: str) -> float:
    if not timings:
        return 0.0
    raw_value = timings.get(key, 0.0)
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return 0.0


def merge_timing_maps(*timing_maps: Mapping[str, object] | None) -> dict[str, float]:
    merged: dict[str, float] = {}
    for timing_map in timing_maps:
        if not timing_map:
            continue
        for key, value in timing_map.items():
            try:
                merged[str(key)] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return merged


def format_timing_summary(
    prefix: str,
    source: str,
    timings: Mapping[str, object] | None,
    ordered_fields: Sequence[tuple[str, str]],
) -> str:
    parts = [prefix, f"source={str(source or '').strip() or 'unknown'}"]
    for key, label in ordered_fields:
        parts.append(f"{label}={timing_value(timings, key):.2f}s")
    return " | ".join(parts)


def is_expected_cancellation_message(message: object) -> bool:
    text = str(message or "")
    return "Processing stopped by user." in text or "stopped by user" in text.lower() or "cancelled by user" in text.lower()


__all__ = [
    "CRASH_REPORT_CAPTURE_DEFAULT_KINDS",
    "DiagnosticsService",
    "RuntimeEventRecorder",
    "add_persisted_crash_breadcrumbs",
    "append_runtime_event_log",
    "crash_report_context_from_text",
    "crash_report_details",
    "crash_report_kind_already_covers_session",
    "crash_timestamp",
    "cleanup_native_fault_log_on_exit",
    "diagnostic_report_index",
    "enable_native_fault_log",
    "check_previous_unclean_exit",
    "format_issue_summary",
    "format_timing_summary",
    "format_thread_dump",
    "heartbeat_payload",
    "is_expected_cancellation_message",
    "latest_diagnostic_report_files",
    "merge_timing_maps",
    "parse_crash_report_header",
    "process_is_alive",
    "read_crash_json_context_file",
    "read_jsonl_tail",
    "rotate_runtime_event_logs",
    "runtime_event_child_memory",
    "runtime_event_log_sibling",
    "sanitize_runtime_event_value",
    "should_write_crash_report",
    "start_hang_watchdog",
    "timing_value",
    "traceback_diagnostic_details",
    "write_crash_report",
    "write_app_heartbeat",
    "write_heartbeat_file",
    "write_ui_breadcrumb",
]
