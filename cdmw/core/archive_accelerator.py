from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_compact_index import ArchiveRowIndex, append_archive_row_id, compact_archive_rows_mapping
from cdmw.core.archive_filtering import (
    archive_browser_sort_is_active,
    build_archive_entry_basename_index,
    build_archive_entry_extension_index,
    build_archive_entry_path_index,
    build_archive_entry_role_index,
)
from cdmw.core.archive_preview_support import prepare_archive_browser_state
from cdmw.core.archive_scan_cache import load_or_update_archive_scan_shards
from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled
from cdmw.models import ArchiveEntry


ARCHIVE_ACCELERATOR_PROTOCOL = 1
ARCHIVE_ACCELERATOR_BACKEND_ID = "cdmw_archive_accelerator_0.1"
ARCHIVE_ACCELERATOR_BINARY_NAME = "cdmw-archive-accelerator.exe" if os.name == "nt" else "cdmw-archive-accelerator"
_ARCHIVE_ACCELERATOR_VERSION_CACHE: dict[tuple[str, int, int], int | None] = {}


def find_native_archive_accelerator() -> Path | None:
    override = os.environ.get("CDMW_ARCHIVE_ACCELERATOR_BIN", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / ARCHIVE_ACCELERATOR_BINARY_NAME)
    if exe_root is not None:
        candidates.append(exe_root / "native" / ARCHIVE_ACCELERATOR_BINARY_NAME)
    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            repo_root / "native" / "cdmw_archive_accelerator" / "build" / "Release" / ARCHIVE_ACCELERATOR_BINARY_NAME,
            repo_root / "native" / "cdmw_archive_accelerator" / "build" / "Debug" / ARCHIVE_ACCELERATOR_BINARY_NAME,
            repo_root / "native" / "cdmw_archive_accelerator" / "build" / ARCHIVE_ACCELERATOR_BINARY_NAME,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _native_diagnostic_args() -> list[str]:
    args: list[str] = []
    crash_dir = str(os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    diagnostic_log = str(os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "") or "").strip()
    if crash_dir:
        args.extend(["--crash-dir", crash_dir])
    if diagnostic_log:
        args.extend(["--diagnostic-log", diagnostic_log])
    return args


def _archive_accelerator_cache_key(binary: Path) -> tuple[str, int, int] | None:
    try:
        resolved = binary.expanduser().resolve()
        stat_result = resolved.stat()
        return (
            str(resolved),
            int(stat_result.st_size),
            int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        )
    except OSError:
        return None


def _archive_accelerator_version(binary: Path, *, timeout_seconds: float = 2.0) -> Optional[int]:
    try:
        completed = subprocess.run(
            [str(binary), "--version", *_native_diagnostic_args()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    text = completed.stdout.decode("utf-8", errors="replace")
    marker = "protocol="
    if marker not in text:
        return None
    try:
        return int(text.split(marker, 1)[1].split()[0].strip())
    except (TypeError, ValueError, IndexError):
        return None


def _native_archive_accelerator_ready(binary: Optional[Path]) -> bool:
    if binary is None:
        return False
    cache_key = _archive_accelerator_cache_key(binary)
    if cache_key is None:
        protocol = _archive_accelerator_version(binary)
    else:
        if cache_key not in _ARCHIVE_ACCELERATOR_VERSION_CACHE:
            _ARCHIVE_ACCELERATOR_VERSION_CACHE[cache_key] = _archive_accelerator_version(binary)
        protocol = _ARCHIVE_ACCELERATOR_VERSION_CACHE.get(cache_key)
    return protocol == ARCHIVE_ACCELERATOR_PROTOCOL


def _entry_from_native_row(
    row: Mapping[str, object],
    *,
    pamt_path_cache: Optional[dict[str, Path]] = None,
    paz_path_cache: Optional[dict[str, Path]] = None,
) -> Optional[ArchiveEntry]:
    try:
        pamt_text = str(row.get("pamt_path") or "")
        paz_text = str(row.get("paz_file") or "")
        pamt_path: Path
        paz_path: Path
        if pamt_path_cache is not None:
            pamt_path = pamt_path_cache.get(pamt_text) or Path(pamt_text)
            pamt_path_cache[pamt_text] = pamt_path
        else:
            pamt_path = Path(pamt_text)
        if paz_path_cache is not None:
            paz_path = paz_path_cache.get(paz_text) or Path(paz_text)
            paz_path_cache[paz_text] = paz_path
        else:
            paz_path = Path(paz_text)
        return ArchiveEntry(
            path=str(row.get("path") or ""),
            pamt_path=pamt_path,
            paz_file=paz_path,
            offset=int(row.get("offset") or 0),
            comp_size=int(row.get("comp_size") or 0),
            orig_size=int(row.get("orig_size") or 0),
            flags=int(row.get("flags") or 0),
            paz_index=int(row.get("paz_index") or 0),
        )
    except (TypeError, ValueError, OSError):
        return None


def scan_archive_entries_native(
    package_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: object = None,
    timeout_seconds: float = 120.0,
) -> Optional[list[ArchiveEntry]]:
    binary = find_native_archive_accelerator()
    if not _native_archive_accelerator_ready(binary):
        return None
    assert binary is not None
    raise_if_cancelled(stop_event)
    started_at = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cdmw_archive_accelerator_scan_") as temp_dir:
        temp_path = Path(temp_dir)
        job_path = temp_path / "scan_job.json"
        report_path = temp_path / "scan_report.json"
        progress_path = temp_path / "scan_progress.json"
        job_path.write_text(
            json.dumps(
                {
                    "protocol": ARCHIVE_ACCELERATOR_PROTOCOL,
                    "package_root": str(Path(package_root)),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if on_log:
            on_log("Native archive accelerator: scanning archive indexes...")
        try:
            completed = subprocess.run(
                [
                    str(binary),
                    "scan-job",
                    str(job_path),
                    str(report_path),
                    str(progress_path),
                    *_native_diagnostic_args(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            if on_log:
                on_log(f"Native archive accelerator scan unavailable; using Python fallback ({exc}).")
            return None
        raise_if_cancelled(stop_event)
        if completed.returncode != 0 or not report_path.is_file():
            if on_log:
                stderr = completed.stderr.decode("utf-8", errors="replace").strip()
                on_log(f"Native archive accelerator scan failed; using Python fallback ({stderr[:300]}).")
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    if not isinstance(report, dict) or report.get("status") != "ok":
        return None
    rows = report.get("entries")
    if not isinstance(rows, list):
        return None
    entries: list[ArchiveEntry] = []
    pamt_path_cache: dict[str, Path] = {}
    paz_path_cache: dict[str, Path] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        entry = _entry_from_native_row(
            row,
            pamt_path_cache=pamt_path_cache,
            paz_path_cache=paz_path_cache,
        )
        if entry is None or not entry.path:
            return None
        entries.append(entry)
    if on_progress:
        on_progress(0, 0, f"Native archive scan loaded {len(entries):,} entries; preparing shard cache...")
    if on_log:
        elapsed = time.perf_counter() - started_at
        on_log(f"Native archive accelerator scanned {len(entries):,} entries in {elapsed:.1f}s.")
    return entries


def scan_archive_entries_cached_accelerated(
    package_root: Path,
    cache_root: Path,
    *,
    force_refresh: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: object = None,
) -> tuple[list[ArchiveEntry], str, Optional[Path], dict[str, float], dict[str, object]]:
    started_at = time.perf_counter()
    timings: dict[str, float] = {}
    scan_metadata: dict[str, object] = {}
    entries, source, cache_path = load_or_update_archive_scan_shards(
        package_root,
        cache_root,
        force_refresh=force_refresh,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
        timings=timings,
        metadata_out=scan_metadata,
        full_scan_func=lambda: scan_archive_entries_native(
            package_root,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
        ),
        shard_scan_func=lambda pamt_path: scan_archive_entries_native(
            pamt_path,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
        ),
        shard_scan_source="native_scan",
        full_scan_source="native_scan",
    )
    timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
    return entries, source, cache_path, timings, scan_metadata


def read_archive_entry_data_native(
    entry: ArchiveEntry,
    *,
    stop_event: object = None,
    timeout_seconds: float = 30.0,
) -> Optional[tuple[bytes, bool, str]]:
    binary = find_native_archive_accelerator()
    if not _native_archive_accelerator_ready(binary):
        return None
    assert binary is not None
    raise_if_cancelled(stop_event)
    with tempfile.TemporaryDirectory(prefix="cdmw_archive_accelerator_entry_") as temp_dir:
        temp_path = Path(temp_dir)
        job_path = temp_path / "entry_job.json"
        output_path = temp_path / "entry_output.bin"
        report_path = temp_path / "entry_report.json"
        job_path.write_text(
            json.dumps(
                {
                    "protocol": ARCHIVE_ACCELERATOR_PROTOCOL,
                    "path": str(entry.path or ""),
                    "paz_file": str(entry.paz_file),
                    "offset": int(entry.offset),
                    "comp_size": int(entry.comp_size),
                    "orig_size": int(entry.orig_size),
                    "flags": int(entry.flags),
                    "paz_index": int(entry.paz_index),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    str(binary),
                    "entry-read-job",
                    str(job_path),
                    str(output_path),
                    str(report_path),
                    *_native_diagnostic_args(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        raise_if_cancelled(stop_event)
        if completed.returncode != 0 or not report_path.is_file():
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(report, Mapping):
            return None
        if report.get("status") != "ok" or report.get("supported") is not True:
            return None
        if not output_path.is_file():
            return None
        try:
            data = output_path.read_bytes()
        except OSError:
            return None
    bytes_written = report.get("bytes_written")
    try:
        if int(bytes_written) != len(data):
            return None
    except (TypeError, ValueError):
        return None
    return data, bool(report.get("decompressed", False)), str(report.get("note") or "NativeRaw")


def _native_browser_state_block_reason(
    entries: Sequence[ArchiveEntry],
    *,
    filter_text: str,
    exclude_filter_text: str,
    item_search_aliases: Optional[Mapping[str, str]],
    archive_name_search_index: object,
    sort_column: object,
    role_filter: str,
) -> str:
    if not entries:
        return "empty_entries"
    if archive_name_search_index is not None and str(filter_text or "").strip():
        return "item_name_search_python_path"
    if item_search_aliases and str(filter_text or "").strip():
        return "item_name_search_python_path"
    if str(filter_text or "").strip() and len(entries) <= 250_000:
        return "small_text_filter_python_path"
    if archive_browser_sort_is_active(sort_column):
        return "sort_python_path"
    for text in (filter_text, exclude_filter_text):
        if any(char in str(text or "") for char in '"|:-[]?*'):
            return "advanced_pattern_python_path"
    normalized_role = str(role_filter or "all").strip().lower()
    if normalized_role not in {"", "all"}:
        return "role_filter_python_path"
    return ""


def _write_browser_entries_tsv(path: Path, entries: Sequence[ArchiveEntry]) -> None:
    def clean(value: object) -> str:
        return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for index, entry in enumerate(entries):
            stream.write(
                "\t".join(
                    (
                        str(index),
                        clean(entry.path),
                        clean(entry.pamt_path),
                        clean(entry.paz_file),
                        str(int(entry.offset)),
                        str(int(entry.comp_size)),
                        str(int(entry.orig_size)),
                        str(int(entry.flags)),
                        str(int(entry.paz_index)),
                    )
                )
                + "\n"
            )


def _tuple_key(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        return tuple(part for part in value.split("/") if part)
    return ()


def _decode_native_browser_state(report: Mapping[str, object], entries: Sequence[ArchiveEntry]) -> Optional[dict]:
    raw_indexes = report.get("filtered_indexes")
    if not isinstance(raw_indexes, list):
        return None
    filtered_indexes: list[int] = []
    for raw_index in raw_indexes:
        try:
            entry_index = int(raw_index)
        except (TypeError, ValueError):
            return None
        if entry_index < 0 or entry_index >= len(entries):
            return None
        filtered_indexes.append(entry_index)
    filtered_entries = [entries[index] for index in filtered_indexes]

    structure_children: dict[str, list[tuple[str, int]]] = {}
    for row in report.get("structure_children", []) or []:
        if not isinstance(row, Mapping):
            continue
        parent = str(row.get("parent") or "")
        children: list[tuple[str, int]] = []
        for child in row.get("children", []) or []:
            if isinstance(child, list) and len(child) >= 2:
                children.append((str(child[0]), int(child[1])))
        structure_children[parent] = children

    tree_child_folders: dict[tuple[str, ...], list[tuple[str, tuple[str, ...]]]] = {}
    for row in report.get("tree_child_folders", []) or []:
        if not isinstance(row, Mapping):
            continue
        parent = _tuple_key(row.get("parent"))
        children: list[tuple[str, tuple[str, ...]]] = []
        for child in row.get("children", []) or []:
            if isinstance(child, list) and len(child) >= 2:
                children.append((str(child[0]), _tuple_key(child[1])))
        tree_child_folders[parent] = children

    tree_direct_files: dict[tuple[str, ...], list[int]] = {}
    for row in report.get("tree_direct_files", []) or []:
        if isinstance(row, Mapping):
            tree_direct_files[_tuple_key(row.get("folder"))] = [int(value) for value in row.get("indexes", []) or []]

    folder_entry_indexes: dict[tuple[str, ...], list[int]] = {}
    for row in report.get("tree_folder_entry_indexes", []) or []:
        if isinstance(row, Mapping):
            folder_entry_indexes[_tuple_key(row.get("folder"))] = [int(value) for value in row.get("indexes", []) or []]

    folder_preview_stats: dict[tuple[str, ...], tuple[int, int, int]] = {}
    for row in report.get("tree_folder_preview_stats", []) or []:
        if isinstance(row, Mapping):
            stats = row.get("stats", []) or []
            if isinstance(stats, list) and len(stats) >= 3:
                folder_preview_stats[_tuple_key(row.get("folder"))] = (int(stats[0]), int(stats[1]), int(stats[2]))

    return {
        "structure_children": structure_children,
        "filtered_entries": filtered_entries,
        "tree_child_folders": tree_child_folders,
        "tree_direct_files": tree_direct_files,
        "tree_folder_entry_indexes": folder_entry_indexes,
        "tree_folder_preview_stats": folder_preview_stats,
        "tree_index_ready": bool(report.get("tree_index_ready", False)),
        "dds_count": int(report.get("dds_count") or 0),
        "archive_accelerator": {
            "backend": str(report.get("backend") or ARCHIVE_ACCELERATOR_BACKEND_ID),
            "native_requested": True,
            "native_used": True,
            "protocol": int(report.get("protocol") or ARCHIVE_ACCELERATOR_PROTOCOL),
        },
    }


def _decode_row_index(rows: object, entries: Sequence[ArchiveEntry], *, name: str = "") -> ArchiveRowIndex:
    if not isinstance(rows, list):
        raise ValueError("native derived index rows are missing")
    decoded: dict[str, object] = {}
    entry_count = len(entries)
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        key = str(row[0] or "")
        raw_indexes = row[1]
        if not key or not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < entry_count:
                append_archive_row_id(decoded, key, index)
    return ArchiveRowIndex(entries, compact_archive_rows_mapping(decoded), name=name)


def build_archive_basic_indexes_accelerated(
    entries: Sequence[ArchiveEntry],
    *,
    native_enabled: bool = True,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: object = None,
) -> tuple[
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    Mapping[str, Sequence[ArchiveEntry]],
    bool,
]:
    binary = find_native_archive_accelerator() if native_enabled else None
    if native_enabled and _native_archive_accelerator_ready(binary) and entries:
        assert binary is not None
        raise_if_cancelled(stop_event)
        with tempfile.TemporaryDirectory(prefix="cdmw_archive_accelerator_derived_") as temp_dir:
            temp_path = Path(temp_dir)
            entries_path = temp_path / "entries.tsv"
            report_path = temp_path / "derived_report.json"
            progress_path = temp_path / "derived_progress.json"
            if on_progress is not None:
                on_progress(0, max(len(entries), 1), "Building path lookup...")
            _write_browser_entries_tsv(entries_path, entries)
            try:
                completed = subprocess.run(
                    [
                        str(binary),
                        "derived-index-job",
                        str(entries_path),
                        str(report_path),
                        str(progress_path),
                        *_native_diagnostic_args(),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90.0,
                    check=False,
                    **hidden_subprocess_kwargs(),
                )
            except (OSError, subprocess.SubprocessError, ValueError):
                completed = None
            raise_if_cancelled(stop_event)
            if completed is not None and completed.returncode == 0 and report_path.is_file():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    if (
                        isinstance(report, Mapping)
                        and report.get("status") == "ok"
                        and int(report.get("entry_count") or -1) == len(entries)
                    ):
                        return (
                            _decode_row_index(report.get("path_rows"), entries, name="path"),
                            _decode_row_index(report.get("basename_rows"), entries, name="basename"),
                            _decode_row_index(report.get("extension_rows"), entries, name="extension"),
                            build_archive_entry_role_index(entries),
                            True,
                        )
                except Exception:
                    pass
    return (
        build_archive_entry_path_index(entries),
        build_archive_entry_basename_index(entries),
        build_archive_entry_extension_index(entries),
        build_archive_entry_role_index(entries),
        False,
    )


def _try_prepare_archive_browser_state_native(
    entries: Sequence[ArchiveEntry],
    **kwargs: Any,
) -> Tuple[Optional[dict], str]:
    unsupported_reason = _native_browser_state_block_reason(
        entries,
        filter_text=str(kwargs.get("filter_text", "") or ""),
        exclude_filter_text=str(kwargs.get("exclude_filter_text", "") or ""),
        item_search_aliases=kwargs.get("item_search_aliases"),
        archive_name_search_index=kwargs.get("archive_name_search_index"),
        sort_column=kwargs.get("sort_column", -1),
        role_filter=str(kwargs.get("role_filter", "all") or "all"),
    )
    if unsupported_reason:
        return None, unsupported_reason
    binary = find_native_archive_accelerator()
    if not _native_archive_accelerator_ready(binary):
        return None, "native archive accelerator binary unavailable or not ready"
    assert binary is not None
    stop_event = kwargs.get("stop_event")
    raise_if_cancelled(stop_event)
    with tempfile.TemporaryDirectory(prefix="cdmw_archive_accelerator_browser_") as temp_dir:
        temp_path = Path(temp_dir)
        entries_path = temp_path / "entries.tsv"
        job_path = temp_path / "browser_job.json"
        report_path = temp_path / "browser_report.json"
        progress_path = temp_path / "browser_progress.json"
        _write_browser_entries_tsv(entries_path, entries)
        job_path.write_text(
            json.dumps(
                {
                    "protocol": ARCHIVE_ACCELERATOR_PROTOCOL,
                    "entries_tsv": str(entries_path),
                    "filter_text": str(kwargs.get("filter_text", "") or ""),
                    "exclude_filter_text": str(kwargs.get("exclude_filter_text", "") or ""),
                    "extension_filter": str(kwargs.get("extension_filter", "*") or "*"),
                    "package_filter_text": str(kwargs.get("package_filter_text", "") or ""),
                    "structure_filter": str(kwargs.get("structure_filter", "") or ""),
                    "exclude_common_technical_suffixes": bool(kwargs.get("exclude_common_technical_suffixes", False)),
                    "min_size_kb": int(kwargs.get("min_size_kb", 0) or 0),
                    "previewable_only": bool(kwargs.get("previewable_only", False)),
                    "build_structure_children": bool(kwargs.get("build_structure_children", True)),
                    "build_tree_index": bool(kwargs.get("build_tree_index", True)),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [str(binary), "browser-state-job", str(job_path), str(report_path), str(progress_path), *_native_diagnostic_args()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60.0,
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return None, "native browser-state accelerator timed out after 60s"
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return None, f"native browser-state accelerator launch failed: {exc}"
        raise_if_cancelled(stop_event)
        if completed.returncode != 0 or not report_path.is_file():
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
            stdout = completed.stdout.decode("utf-8", errors="replace").strip()[:300]
            detail = stderr or stdout or "no diagnostic output"
            return None, f"native browser-state accelerator failed rc={completed.returncode}: {detail}"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"native browser-state accelerator report invalid: {exc}"
    if not isinstance(report, Mapping) or report.get("status") != "ok":
        return None, f"native browser-state accelerator report status={getattr(report, 'get', lambda _key, _default=None: None)('status')}"
    return _decode_native_browser_state(report, entries), ""


def prepare_archive_browser_state_accelerated(*args: Any, native_enabled: bool = True, resource_profile: str = "balanced_60fps", **kwargs: Any) -> dict:
    native_path: Optional[Path] = None
    fallback_reason = "native acceleration disabled"
    if native_enabled and args:
        native_state, fallback_reason = _try_prepare_archive_browser_state_native(args[0], **kwargs)
        if native_state is not None:
            native_path = find_native_archive_accelerator()
            native_state["archive_accelerator"]["native_path"] = str(native_path or "")
            native_state["archive_accelerator"]["resource_profile"] = str(resource_profile or "balanced_60fps")
            return native_state
    state = prepare_archive_browser_state(*args, **kwargs)
    state["archive_accelerator"] = {
        "backend": "python_fallback",
        "native_requested": bool(native_enabled),
        "native_path": str(native_path or ""),
        "native_used": False,
        "resource_profile": str(resource_profile or "balanced_60fps"),
        "fallback_reason": str(fallback_reason or "native browser-state accelerator unavailable"),
    }
    return state
