"""Read-only diagnostic bundle assembly outside the UI thread."""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.core.chainner import analyze_chainner_chain_paths, format_chainner_analysis
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ChainnerChainAnalysis
from cdmw.services.diagnostics_service import (
    diagnostic_report_index,
    format_issue_summary,
    latest_diagnostic_report_files,
)


@dataclass(frozen=True, slots=True)
class ChainnerDiagnosticSnapshot:
    chain_path: str = ""
    original_dds_root: str = ""
    staging_png_root: str = ""
    png_root: str = ""
    override_json: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticBundleRequest:
    target: Path
    app_title: str
    app_version: str
    theme: str
    settings_file_path: Path
    archive_cache_root: Path
    crash_reports_dir: Path
    profile_json: str
    chainner: ChainnerDiagnosticSnapshot
    live_log: str
    archive_scan_log: str
    crash_context_json: str = "{}"
    text_search_entries: tuple[tuple[str, str], ...] = ()
    documentation_files: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticBundleResult:
    target: Path
    chainner_warning_count: Optional[int]


def resolve_chainner_diagnostic(
    snapshot: ChainnerDiagnosticSnapshot,
) -> tuple[Optional[ChainnerChainAnalysis], str]:
    chain_path_text = snapshot.chain_path.strip()
    if not chain_path_text:
        return None, "Select a .chn file to inspect and validate it."

    try:
        chain_path = Path(chain_path_text).expanduser().resolve()
    except OSError as exc:
        return None, f"Could not resolve chain path: {exc}"
    if not chain_path.exists() or not chain_path.is_file():
        return None, f"Chain file not found: {chain_path}"

    def _optional_root(value: str) -> Optional[Path]:
        return Path(value).expanduser().resolve() if value.strip() else None

    original_root = _optional_root(snapshot.original_dds_root)
    staging_root = _optional_root(snapshot.staging_png_root)
    png_root = _optional_root(snapshot.png_root)
    analysis = analyze_chainner_chain_paths(
        chain_path,
        original_dds_root=original_root,
        staging_png_root=staging_root,
        png_root=png_root,
        chainner_override_json=snapshot.override_json,
    )
    text = format_chainner_analysis(analysis)

    notes: list[str] = []
    if snapshot.override_json.strip():
        notes.append(
            "Override JSON is configured. Runtime overrides may replace some hardcoded chain paths shown above."
        )
    if original_root is None or png_root is None:
        notes.append(
            "Path-mismatch validation is limited until Original DDS root and PNG root are configured. "
            "DDS staging validation is also limited until DDS staging root is configured when staging is enabled."
        )
    if notes:
        text += "\n\nNotes:\n" + "\n".join(f"- {note}" for note in notes)
    return analysis, text


def _read_text(path: Path, stop_event: Optional[threading.Event]) -> str:
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as source:
        while True:
            raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
    return "".join(chunks)


def _write_text_file_to_zip(
    archive: zipfile.ZipFile,
    archive_name: str,
    source_path: Path,
    stop_event: Optional[threading.Event],
) -> None:
    with (
        source_path.open("r", encoding="utf-8", errors="replace") as source,
        archive.open(archive_name, "w") as destination,
    ):
        while True:
            raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            destination.write(chunk.encode("utf-8"))
    raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")


def build_diagnostic_bundle(
    request: DiagnosticBundleRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> DiagnosticBundleResult:
    """Build then atomically publish one bundle; cancellation leaves prior output intact."""

    raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
    analysis, analysis_text = resolve_chainner_diagnostic(request.chainner)
    raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")

    cache_files: list[dict[str, object]] = []
    if request.archive_cache_root.exists():
        for cache_file in sorted(request.archive_cache_root.glob("*"), key=lambda path: path.name.casefold()):
            raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
            if not cache_file.is_file():
                continue
            try:
                stat = cache_file.stat()
            except OSError:
                continue
            cache_files.append(
                {
                    "name": cache_file.name,
                    "size_bytes": stat.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                }
            )

    crash_reports = latest_diagnostic_report_files(request.crash_reports_dir, limit=20)
    latest_log = next((path for path in crash_reports if path.suffix.lower() == ".log"), None)
    context = None
    if latest_log is None:
        try:
            parsed_context = json.loads(request.crash_context_json or "{}")
        except (TypeError, ValueError):
            parsed_context = {}
        context = parsed_context if isinstance(parsed_context, dict) else {}
    issue_summary = format_issue_summary(
        app_title=request.app_title,
        app_version=request.app_version,
        report_path=latest_log,
        report_text=_read_text(latest_log, stop_event) if latest_log is not None else "",
        context=context,
    )
    diagnostics_index = diagnostic_report_index(crash_reports)
    diagnostics = {
        "app": request.app_title,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "python_version": sys.version,
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "theme": request.theme,
        "settings_file": str(request.settings_file_path),
        "archive_cache_root": str(request.archive_cache_root),
        "archive_cache_files": cache_files,
        "profile": json.loads(request.profile_json),
        "chainner_warning_count": len(analysis.warnings) if analysis is not None else None,
    }

    target = request.target
    target.parent.mkdir(parents=True, exist_ok=True)
    staged_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.cdmw-tmp")
    try:
        with zipfile.ZipFile(staged_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            entries = (
                ("diagnostics.json", json.dumps(diagnostics, indent=2)),
                ("issue_summary.txt", issue_summary),
                ("diagnostics_index.json", json.dumps(diagnostics_index, indent=2)),
                ("chainner_analysis.txt", analysis_text),
                ("live_log.txt", request.live_log),
                ("archive_scan_log.txt", request.archive_scan_log),
            )
            for archive_name, text in entries:
                raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
                archive.writestr(archive_name, text)

            source_files = (request.settings_file_path, *request.documentation_files)
            for source_path in source_files:
                raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
                if source_path.exists():
                    _write_text_file_to_zip(archive, source_path.name, source_path, stop_event)

            for crash_report in crash_reports:
                try:
                    _write_text_file_to_zip(
                        archive,
                        f"crash_reports/{crash_report.name}",
                        crash_report,
                        stop_event,
                    )
                except OSError:
                    pass

            for archive_name, text in request.text_search_entries:
                raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
                archive.writestr(archive_name, text)

        raise_if_cancelled(stop_event, "Diagnostic bundle export stopped by user.")
        os.replace(staged_path, target)
    finally:
        staged_path.unlink(missing_ok=True)

    return DiagnosticBundleResult(
        target=target,
        chainner_warning_count=len(analysis.warnings) if analysis is not None else None,
    )


__all__ = [
    "ChainnerDiagnosticSnapshot",
    "DiagnosticBundleRequest",
    "DiagnosticBundleResult",
    "build_diagnostic_bundle",
    "resolve_chainner_diagnostic",
]
