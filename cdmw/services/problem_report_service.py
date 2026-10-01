"""Reviewed problem reports. Collection is read-only and runs outside the UI thread."""

from __future__ import annotations

import base64
import io
import json
import os
import platform
import re
import stat
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from cdmw.constants import APP_VERSION
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.atomic_file_service import atomic_write_bytes

REPORT_ENDPOINT = "https://cdmw-reports-test.fredriccarlberg.workers.dev/reports"
REPORT_DESTINATION = "Ratty123's private CDMW-Reports inbox (Cloudflare and GitHub)"
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
MAX_LAYOUT_ENTRIES = 250
FREQUENCIES = ("Every time", "Sometimes", "Once")
PLATFORMS = ("Steam", "Epic Games", "Other / unsure")
CLEAN_TESTS = ("Not tried", "Still happens without mods", "Works without mods", "No mods installed")


@dataclass(frozen=True)
class ProblemDetails:
    summary: str
    tool: str
    steps: str
    expected: str
    actual: str
    frequency: str
    game_version: str
    game_platform: str
    mod_setup: str
    clean_test: str
    contact: str = ""


def validate_details(details: ProblemDetails) -> tuple[str, ...]:
    errors = []
    for key, label, minimum, maximum in (
        ("summary", "Summary", 10, 120), ("tool", "Tool", 2, 120),
        ("steps", "Steps to reproduce", 20, 6000),
        ("expected", "Expected result", 10, 3000), ("actual", "Actual result", 10, 3000),
        ("game_version", "Game version (or Unknown)", 2, 80),
        ("mod_setup", "Mods and mod manager (or None)", 4, 2000),
    ):
        value = getattr(details, key).strip()
        if len(value) < minimum:
            errors.append(f"{label}: please provide at least {minimum} characters.")
        elif len(value) > maximum:
            errors.append(f"{label}: keep this under {maximum} characters.")
    for key, choices, label in (
        ("frequency", FREQUENCIES, "How often"), ("game_platform", PLATFORMS, "Game platform"),
        ("clean_test", CLEAN_TESTS, "Test without mods"),
    ):
        if getattr(details, key) not in choices:
            errors.append(f"{label}: choose an option.")
    if len(details.contact) > 200:
        errors.append("Contact: keep this under 200 characters.")
    return tuple(errors)


@dataclass(frozen=True)
class ProblemSnapshot:
    """Only values copied from UI state; no live widgets or full settings payload."""

    context_json: str = "{}"
    archive_root: str = ""
    workspace_root: str = ""
    event_log: str = ""
    live_log: str = ""
    archive_log: str = ""
    captured_at: float = 0


@dataclass(frozen=True)
class ProblemReportRequest:
    details: ProblemDetails
    snapshot: ProblemSnapshot
    include_logs: bool = True
    include_layout: bool = True
    screenshot_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewedProblemReport:
    report_id: str
    body: bytes
    preview: str
    draft_path: Path


class ReportRedactor:
    def __init__(self, snapshot: ProblemSnapshot) -> None:
        game_root = _game_root(snapshot.archive_root)
        roots = ((snapshot.archive_root, "<ARCHIVE_ROOT>"), (game_root, "<GAME_ROOT>"),
                 (snapshot.workspace_root, "<CDMW_WORKSPACE>"),
                 (os.environ.get("USERPROFILE", ""), "<USER_PROFILE>"),
                 (os.environ.get("TEMP", ""), "<TEMP>"))
        self.roots = sorted(((path, name) for path, name in roots if path),
                            key=lambda item: len(item[0]), reverse=True)

    def text(self, value: str) -> str:
        text = str(value).replace("\x00", "")
        # Handle both JSON-decoded slash styles without touching archive-internal paths.
        for root, label in self.roots:
            pattern = r"[\\/]".join(re.escape(part) for part in re.split(r"[\\/]", root.rstrip("\\/")))
            text = re.sub(pattern + r"(?=$|[\\/\s\"'])", lambda _: label, text, flags=re.I)
        text = re.sub(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "<REDACTED>", text)
        text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\r\n,;]+", r"\1<REDACTED>", text)
        text = re.sub(r"(?i)((?:api[_ -]?key|access[_ -]?token|password|secret|token)\s*[=:]\s*)[^\s,;]+",
                      r"\1<REDACTED>", text)
        text = re.sub(r"https?://[^\s\"<>]+", "<URL_REDACTED>", text)
        # Unknown absolute paths can contain spaces. Err toward removing the whole value.
        text = re.sub(r"(?i)(?:\b[A-Z]:[\\/]|\\\\)[^\r\n\"<>|]+", "<LOCAL_PATH>", text)
        text = re.sub(r"(?<![\w<>])/(?:home|Users|tmp|mnt)/[^\r\n\"<>|]+", "<LOCAL_PATH>", text)
        return text

    def value(self, value: object, *, depth: int = 0) -> object:
        if depth > 8:
            return "<TRUNCATED>"
        if isinstance(value, dict):
            return {self.text(str(key)): ("<REDACTED>" if re.search(
                r"(?i)password|secret|token|api.?key|authorization", str(key))
                else self.value(item, depth=depth + 1)) for key, item in list(value.items())[:100]}
        if isinstance(value, (list, tuple)):
            return [self.value(item, depth=depth + 1) for item in value[:MAX_LAYOUT_ENTRIES]]
        if isinstance(value, str):
            return self.text(value[:32000])
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.text(str(value)[:1000])


def _game_root(archive_root: str) -> str:
    if not archive_root:
        return ""
    root = Path(archive_root)
    return str(root.parent) if root.name.lower() == "image" else ""


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _folder_layout(root: str, stop_event: threading.Event | None) -> dict:
    """Bounded names/stat only; do not traverse symlinks, junctions or backup contents."""
    if not root:
        return {"status": "not configured", "entries": []}
    entries: list[dict] = []
    truncated = False
    try:
        if _is_link(Path(root).lstat()):
            return {"status": "linked root skipped", "entries": []}
        pending = [(Path(root), 0)]
        while pending:
            folder, depth = pending.pop(0)
            raise_if_cancelled(stop_event)
            with os.scandir(folder) as children:
                for child in children:
                    raise_if_cancelled(stop_event)
                    if len(entries) >= MAX_LAYOUT_ENTRIES:
                        truncated = True
                        break
                    relative = str(Path(child.path).relative_to(root)).replace("\\", "/")
                    try:
                        info = child.stat(follow_symlinks=False)
                        link = _is_link(info)
                        directory = stat.S_ISDIR(info.st_mode)
                        entries.append({"path": relative, "kind": "link skipped" if link else "folder" if directory else "file",
                                        "size": info.st_size if not directory and not link else None})
                        # A small installation layout, not a recursive dump of user content.
                        descend = depth == 0 and child.name.lower() in {"image", "bin64", "plugins", "cdmods", "mods"}
                        if descend and directory and not link:
                            pending.append((Path(child.path), depth + 1))
                    except OSError:
                        entries.append({"path": relative, "kind": "unavailable"})
            if truncated:
                break
        return {"status": "partial" if truncated else "collected", "truncated": truncated,
                "entries": sorted(entries, key=lambda item: item["path"].lower())}
    except OSError:
        return {"status": "unavailable", "entries": entries}


def _event_tail(snapshot: ProblemSnapshot) -> list:
    if not snapshot.event_log:
        return []
    try:
        with Path(snapshot.event_log).open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            offset = max(0, size - 64 * 1024)
            handle.seek(offset)
            data = handle.read(64 * 1024)
        if offset:
            _, _, data = data.partition(b"\n")
        events = []
        for line in data.decode("utf-8", errors="replace").splitlines()[-80:]:
            try:
                event = json.loads(line)
                if isinstance(event, dict) and float(event.get("timestamp", 0)) <= snapshot.captured_at:
                    events.append(event)
            except (ValueError, TypeError):
                continue
        return events[-40:]
    except OSError:
        return []


def _screenshot(path: str, index: int) -> dict:
    from PIL import Image

    source = Path(path)
    if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Screenshots must be PNG, JPEG or WebP images.")
    if source.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Choose screenshots smaller than 12 MB each.")
    with source.open("rb") as handle, Image.open(handle) as original:
        if original.width * original.height > 40_000_000 or original.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Choose a PNG, JPEG or WebP screenshot under 40 megapixels.")
        image = original.convert("RGB")
        image.info.clear()
        image.thumbnail((1920, 1920))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
    data = output.getvalue()
    if len(data) > MAX_SCREENSHOT_BYTES:
        raise ValueError("A screenshot is too large after resizing. Crop it and try again.")
    return {"name": f"screenshot-{index}.jpg", "mime": "image/jpeg",
            "data": base64.b64encode(data).decode("ascii"), "size": len(data)}


def collect_problem_report(request: ProblemReportRequest, *, stop_event: threading.Event | None = None) -> ReviewedProblemReport:
    errors = validate_details(request.details)
    if errors:
        raise ValueError("\n".join(errors))
    if len(request.screenshot_paths) > MAX_SCREENSHOTS:
        raise ValueError("Attach at most three screenshots.")
    raise_if_cancelled(stop_event)
    snapshot = request.snapshot
    redactor = ReportRedactor(snapshot)
    context = json.loads(snapshot.context_json)
    evidence = {"captured_at": snapshot.captured_at, "context": context,
                "environment": {"cdmw_version": APP_VERSION, "os": platform.system(),
                                "os_release": platform.release(), "architecture": platform.machine(),
                                "python": platform.python_version(), "packaged": bool(getattr(sys, "frozen", False))}}
    selected = context.get("selected_archive_package", "")
    if selected:
        try:
            info = Path(selected).lstat()
            evidence["selected_archive_source"] = {"path": selected, "exists": True,
                "linked": _is_link(info), "size": info.st_size, "modified_ns": info.st_mtime_ns}
        except OSError:
            evidence["selected_archive_source"] = {"path": selected, "exists": False}
    if request.include_logs:
        evidence["logs"] = {"live": snapshot.live_log[-32000:], "archive": snapshot.archive_log[-32000:],
                            "runtime_events": _event_tail(snapshot), "scope": "recent excerpts at report time"}
    if request.include_layout:
        evidence["folder_layout"] = {"archive_root": _folder_layout(snapshot.archive_root, stop_event),
                                     "game_root": _folder_layout(_game_root(snapshot.archive_root), stop_event),
                                     "scope": "bounded names and sizes; no file contents; not a clean-install verification"}
    raise_if_cancelled(stop_event)
    report_id = str(uuid4())
    payload = {"schema_version": 1, "report_id": report_id, "created_at": time.time(),
               "details": redactor.value(asdict(request.details)), "evidence": redactor.value(evidence),
               "screenshots": []}
    for index, path in enumerate(request.screenshot_paths, 1):
        raise_if_cancelled(stop_event)
        payload["screenshots"].append(_screenshot(path, index))
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_REPORT_BYTES:
        raise ValueError("Report exceeds 8 MB. Remove a screenshot and collect it again.")
    # The review includes all textual evidence. Image contents must be checked visually.
    labels = {"summary": "Summary", "tool": "Tool / workflow", "steps": "Steps to reproduce",
              "expected": "Expected result", "actual": "Actual result / error", "frequency": "How often",
              "game_version": "Game version", "game_platform": "Game platform", "mod_setup": "Mods and manager",
              "clean_test": "Test without mods", "contact": "Contact"}
    preview = f"Report ID: {report_id}\n\n" + "\n\n".join(
        f"{label}\n{payload['details'][key] or 'Not provided'}" for key, label in labels.items())
    preview += "\n\nCollected evidence\n" + json.dumps(payload["evidence"], ensure_ascii=False, indent=2)
    preview += "\n\nScreenshots\n" + json.dumps(
        [{key: value for key, value in shot.items() if key != "data"} for shot in payload["screenshots"]], indent=2)
    draft_path = Path(snapshot.workspace_root) / "problem_reports" / f"{report_id}.json"
    raise_if_cancelled(stop_event)
    atomic_write_bytes(draft_path, body)
    return ReviewedProblemReport(report_id, body, preview, draft_path)


def report_test_token() -> str:
    return os.environ.get("CDMW_REPORT_TEST_TOKEN", "").strip()


def parse_report_receipt(body: bytes, *, report_id: str) -> str:
    """A timeout/error/pending delivery must never appear as a successful submission."""
    try:
        receipt = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("The report service returned an invalid receipt.") from None
    if (not isinstance(receipt, dict) or receipt.get("status") != "accepted" or receipt.get("report_id") != report_id
            or type(receipt.get("issue_number")) is not int or receipt["issue_number"] < 1):
        raise ValueError("Delivery is not confirmed. Keep the draft and retry the same report.")
    return f"CDMW-{receipt['issue_number']} ({report_id})"
