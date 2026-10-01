"""Bounded, read-only evidence collection for reviewed problem reports.

Only app-owned diagnostic files and resolved application/helper binaries are
inspected. Inputs, archive payloads, settings files and export folders are not.
All I/O runs in the existing report collection worker; the caller redacts the
result before saving or displaying it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.mesh_interaction_diagnostics import _recent_event_summary

EVENT_BYTE_LIMIT = 256 * 1024
EVENT_LIMIT = 120
TEXT_BYTE_LIMIT = 32 * 1024
CRASH_REPORT_LIMIT = 3
CRASH_REPORT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*_\d{8}_\d{6}(?:_\d{3})?_\d+\.log$")


def _linked(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _excerpt(path: Path, *, max_bytes: int, tail: bool = True, captured_at: float = 0,
             stop_event=None) -> tuple[str, dict]:
    raise_if_cancelled(stop_event)
    metadata = {"file": path.name, "status": "missing", "truncated": False}
    try:
        info = path.lstat()
        if _linked(info) or not stat.S_ISREG(info.st_mode):
            return "", {**metadata, "status": "skipped_link_or_non_file"}
        metadata.update(source_bytes=info.st_size, modified_at=info.st_mtime)
        if not tail and captured_at and info.st_mtime > captured_at:
            return "", {**metadata, "status": "newer_than_snapshot"}
        size = info.st_size
        with path.open("rb") as handle:
            if tail:
                offset = max(0, size - max_bytes)
                handle.seek(offset)
                data = handle.read(min(size, max_bytes))
                if offset:
                    _, _, data = data.partition(b"\n")
            elif size > max_bytes:
                head = handle.read(max_bytes // 4)
                handle.seek(max(0, size - max_bytes * 3 // 4))
                data = head + b"\n<excerpt truncated>\n" + handle.read(max_bytes * 3 // 4)
            else:
                data = handle.read(max_bytes)
        raise_if_cancelled(stop_event)
        metadata.update(status="available", truncated=size > max_bytes, read_bytes=len(data))
        return data.decode("utf-8", errors="replace"), metadata
    except FileNotFoundError:
        return "", metadata
    except OSError as exc:
        return "", {**metadata, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}


def _events(path: Path, *, captured_at: float, mesh: bool = False, stop_event=None) -> tuple[list, dict]:
    text, metadata = _excerpt(path, max_bytes=EVENT_BYTE_LIMIT, stop_event=stop_event)
    events = []
    invalid = later = unknown_time = 0
    for line in text.splitlines():
        raise_if_cancelled(stop_event)
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not an event")
        except (ValueError, TypeError):
            invalid += 1
            continue
        stamp = row.get("timestamp", row.get("recorded_at_utc"))
        if isinstance(stamp, (int, float)) and math.isfinite(stamp):
            if captured_at and stamp > captured_at:
                later += 1
                continue
        else:
            unknown_time += 1
        events.append(_recent_event_summary(row) if mesh else row)
    metadata.update(invalid_lines=invalid, events_after_snapshot=later,
                    events_without_timestamp=unknown_time, retained_events=min(EVENT_LIMIT, len(events)),
                    event_limit_reached=len(events) > EVENT_LIMIT)
    return events[-EVENT_LIMIT:], metadata


def _json_file(path: Path, *, captured_at: float, stop_event=None) -> tuple[dict, dict]:
    text, metadata = _excerpt(path, max_bytes=TEXT_BYTE_LIMIT, tail=False,
                              captured_at=captured_at, stop_event=stop_event)
    if metadata["status"] != "available" or metadata["truncated"]:
        return {}, ({**metadata, "status": "size_limit"} if metadata["truncated"] else metadata)
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value, metadata
    except (ValueError, TypeError):
        return {}, {**metadata, "status": "invalid_json"}


def collect_report_logs(snapshot, *, stop_event=None) -> dict:
    directory = Path(snapshot.event_log).parent if snapshot.event_log else Path(snapshot.workspace_root) / "logs"
    coverage = {}
    runtime = []
    for name, path in (("runtime_rotated", directory / "diagnostics_current.jsonl.1"),
                       ("runtime_current", Path(snapshot.event_log) if snapshot.event_log else directory / "diagnostics_current.jsonl")):
        rows, coverage[name] = _events(path, captured_at=snapshot.captured_at, stop_event=stop_event)
        runtime.extend(rows)
    runtime.extend(json.loads(snapshot.recent_events_json))
    # Memory also contains the events preceding a handled error when verbose
    # disk logging is disabled. Dedupe persisted rows without changing them.
    unique = {}
    for row in runtime:
        if isinstance(row, dict):
            unique[json.dumps(row, sort_keys=True, default=str)] = row
    all_runtime = list(unique.values())
    failures = [row for row in all_runtime if str(row.get("severity", "")).lower() in {"error", "critical"}
                or any(marker in str(row.get("event", "")).lower() for marker in ("fail", "error", "exception", "rejected", "timeout"))]
    runtime = all_runtime[-EVENT_LIMIT:]
    mesh_memory = json.loads(snapshot.mesh_diagnostics_json)
    mesh_path = Path(mesh_memory.get("path") or directory / "dotnet_protocol_current.jsonl")
    if mesh_path.suffix.lower() == ".jsonl":
        mesh, coverage["mesh_protocol"] = _events(mesh_path, captured_at=snapshot.captured_at, mesh=True, stop_event=stop_event)
    else:
        mesh, coverage["mesh_protocol"] = [], {"status": "skipped_non_diagnostic_extension"}
    native_path = Path(snapshot.native_log) if snapshot.native_log else directory / "native_diagnostics_verbose.jsonl"
    if native_path.suffix.lower() == ".jsonl":
        native, coverage["native_events"] = _events(native_path, captured_at=snapshot.captured_at, stop_event=stop_event)
    else:
        native, coverage["native_events"] = [], {"status": "skipped_non_diagnostic_extension"}
    fault, coverage["native_fault"] = _excerpt(directory / "native_fault_current.log", max_bytes=TEXT_BYTE_LIMIT,
                                               tail=False, captured_at=snapshot.captured_at, stop_event=stop_event)
    breadcrumbs = {}
    for name in ("archive_scan_breadcrumb", "ui_breadcrumb", "texture_workflow_breadcrumb", "app_heartbeat"):
        value, coverage[name] = _json_file(directory / f"{name}.json", captured_at=snapshot.captured_at, stop_event=stop_event)
        if value:
            breadcrumbs[name] = value
    crashes = []
    candidates = []
    scanned = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                raise_if_cancelled(stop_event)
                scanned += 1
                if scanned > 250:
                    break
                # The crash writer owns this dated naming convention for every
                # feature, including kinds unknown to the report collector.
                if CRASH_REPORT_NAME.fullmatch(entry.name):
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if not _linked(info) and info.st_mtime <= snapshot.captured_at:
                            candidates.append((info.st_mtime, Path(entry.path)))
                    except OSError:
                        pass
        coverage["crash_reports"] = {"status": "available", "directory_limit_reached": scanned > 250,
                                      "report_limit_reached": len(candidates) > CRASH_REPORT_LIMIT}
    except OSError as exc:
        coverage["crash_reports"] = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    for _, path in sorted(candidates, reverse=True)[:CRASH_REPORT_LIMIT]:
        text, metadata = _excerpt(path, max_bytes=TEXT_BYTE_LIMIT, tail=False,
                                  captured_at=snapshot.captured_at, stop_event=stop_event)
        crashes.append({**metadata, "excerpt": text})
    return {"live": snapshot.live_log[-32000:], "archive": snapshot.archive_log[-32000:],
            "tool_logs": json.loads(snapshot.tool_logs_json),
            "runtime_events": runtime, "mesh_events": mesh, "mesh_recorder": mesh_memory,
            "latest_failures": failures[-12:],
            "native_events": native, "native_fault": fault, "breadcrumbs": breadcrumbs,
            "crash_reports": crashes, "collection": coverage,
            "scope": "recent excerpts at report time; historical crash reports may belong to earlier sessions; mesh payloads summarized"}


def _binary_identity(path: Path, *, stop_event=None) -> dict:
    result = {"name": path.name, "path": str(path), "status": "missing"}
    raise_if_cancelled(stop_event)
    if path.suffix.lower() not in {".exe", ".dll"}:
        return {**result, "status": "skipped_non_binary_extension"}
    try:
        info = path.lstat()
        if _linked(info) or not stat.S_ISREG(info.st_mode):
            return {**result, "status": "skipped_link_or_non_file"}
        result.update(size=info.st_size, modified_ns=str(info.st_mtime_ns))
        if info.st_size > 512 * 1024 * 1024:
            return {**result, "status": "hash_size_limit"}
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            remaining = info.st_size
            while remaining > 0:
                raise_if_cancelled(stop_event)
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(handle.fileno())
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return {**result, "status": "changed_during_collection"}
        return {**result, "status": "available", "sha256": digest.hexdigest()}
    except OSError as exc:
        return {**result, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}


def collect_report_build_identity(*, stop_event=None) -> dict:
    result = {"scope": "resolved application/helper files at collection time; running helper identity comes from events"}
    if getattr(sys, "frozen", False):
        result["application"] = _binary_identity(Path(sys.executable), stop_event=stop_event)
    else:
        result["application"] = {"status": "source_run", "sha256": "unavailable for source runs"}
    raise_if_cancelled(stop_event)
    try:
        from cdmw.services.mesh_rust_contract import RUST_MESH_PROVENANCE_FILE, resolve_rust_mesh_editor

        resolution = resolve_rust_mesh_editor()
        if resolution.resolved_path and resolution.is_file:
            path = Path(resolution.resolved_path)
            result["rust_helper"] = {**_binary_identity(path, stop_event=stop_event), "source": resolution.source}
            manifest, status = _json_file(path.with_name(RUST_MESH_PROVENANCE_FILE), captured_at=0, stop_event=stop_event)
            result["rust_provenance"] = {"collection": status, "manifest": manifest}
        else:
            result["rust_helper"] = {"status": "missing", "source": resolution.source}
    except RunCancelled:
        raise
    except Exception as exc:
        result["rust_helper"] = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    raise_if_cancelled(stop_event)
    try:
        from cdmw.modding.mesh_native_core import find_native_mesh_core_binary

        native = find_native_mesh_core_binary()
        result["native_mesh_core"] = _binary_identity(Path(native), stop_event=stop_event) if native else {"status": "missing"}
        if native:
            result["native_mesh_core_dll"] = _binary_identity(Path(native).with_name("cdmw-mesh-core.dll"), stop_event=stop_event)
    except RunCancelled:
        raise
    except Exception as exc:
        result["native_mesh_core"] = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    return result
