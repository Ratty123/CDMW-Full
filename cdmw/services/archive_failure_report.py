"""Bounded, copyable diagnostics for a logical archive operation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import sys

from cdmw.constants import APP_VERSION
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError


REPORT_LIMIT = 16 * 1024


def bounded_text(value: str, limit: int) -> str:
    data = str(value).encode("utf-8", "replace")
    if len(data) <= limit:
        return str(value)
    return data[:max(0, limit - 16)].decode("utf-8", "ignore") + "\n[truncated]"


def redact_archive_paths(value: str, package_root: str = "") -> str:
    prefixes = [(package_root, "<game>"), (os.environ.get("USERPROFILE", str(Path.home())), "<profile>")]
    result = str(value)
    for prefix, replacement in sorted(prefixes, key=lambda item: len(item[0]), reverse=True):
        if not prefix:
            continue
        # Reports can contain either slash style and escaped exception paths.
        pattern = "[/\\\\]+".join(re.escape(part) for part in re.split(r"[/\\]+", prefix.rstrip("/\\")))
        result = re.sub(pattern + r"(?=$|[/\\\s'\"\):,])", lambda _: replacement, result, flags=re.IGNORECASE)
    return result


def _bounded_tail(value: str, limit: int) -> str:
    data = value.encode("utf-8", "replace")
    if len(data) <= limit:
        return value
    marker = "[earlier diagnostics omitted]\n"
    if limit <= len(marker):
        return data[-limit:].decode("utf-8", "ignore") if limit > 0 else ""
    return marker + data[-(limit - len(marker)):].decode("utf-8", "ignore")


@dataclass(frozen=True, slots=True)
class ArchiveOperationFailure:
    """Local presentation context; the worker error wire schema is unchanged."""

    code: str
    message: str
    detail: str | None
    report: str
    request_id: str

    def __str__(self) -> str:
        return self.message


def archive_failure_report(
    error: ArchiveBackendError,
    *,
    operation: str,
    backend: str,
    attempts: int,
    phase: str,
    completed: int,
    total: int,
    elapsed: float,
    current_item: str,
    progress: tuple[str, ...],
    diagnostic_tail: str,
    package_root: str,
) -> str:
    runtime = "packaged" if getattr(sys, "frozen", False) else "source"
    def field(value: str, limit: int) -> str:
        return bounded_text(redact_archive_paths(value, package_root), limit)

    # Allocate space to the error before the noisy diagnostic tail.
    report = (
        f"CDMW {APP_VERSION}\nRuntime: {runtime}; Python {platform.python_version()}; {platform.platform()}\n"
        f"Operation: {field(operation, 64)}\nBackend: {field(backend, 512)}\nAttempts: {attempts} / 2\n"
        f"Last stage: {field(phase or 'waiting for worker', 256)}\nProgress: {completed} / {total}\n"
        f"Elapsed: {elapsed:.1f} seconds\nAffected path: {field(current_item or '(not supplied)', 768)}\n"
        f"Error code: {field(error.code, 128)}\nError: {field(error.message, 2048)}\n"
        f"Details:\n{field(error.detail or '', 6144)}\n"
        "Last progress entries:\n" + "\n".join(field(item, 384) for item in progress[-12:])
        + "\nDiagnostic tail:\n"
    )
    tail_limit = min(4096, max(0, REPORT_LIMIT - len(report.encode("utf-8", "replace"))))
    report += _bounded_tail(redact_archive_paths(diagnostic_tail, package_root), tail_limit)
    return bounded_text(report, REPORT_LIMIT)
