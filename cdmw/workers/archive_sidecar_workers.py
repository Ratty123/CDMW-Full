"""Archive texture sidecar indexing workers."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.archive import (
    build_archive_texture_sidecar_basename_rows,
    build_archive_texture_sidecar_path_rows,
    build_lazy_archive_texture_sidecar_entry_index,
    load_archive_texture_sidecar_cache_rows,
    resolve_archive_sidecar_cache_path,
    save_archive_texture_sidecar_cache,
)
from cdmw.models import ArchiveEntry, RunCancelled


def _timing_value(timings: Optional[Dict[str, float]], key: str) -> float:
    if not timings:
        return 0.0
    try:
        return max(0.0, float(timings.get(key, 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _format_timing_summary(
    prefix: str,
    source: str,
    timings: Optional[Dict[str, float]],
    ordered_fields: Sequence[Tuple[str, str]],
) -> str:
    parts = [prefix, f"source={str(source or '').strip() or 'unknown'}"]
    for key, label in ordered_fields:
        parts.append(f"{label}={_timing_value(timings, key):.2f}s")
    return " | ".join(parts)


class ArchiveSidecarIndexWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, int, str)
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        package_root: Path,
        cache_root: Path,
        entries: Sequence[ArchiveEntry],
        sidecar_worker_count: int = 0,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.package_root = package_root
        self.cache_root = cache_root
        self.entries = entries
        self.sidecar_worker_count = max(0, min(16, int(sidecar_worker_count or 0)))
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            timings: Dict[str, float] = {}
            started_at = time.perf_counter()
            last_progress_emit_at = 0.0

            def _emit_throttled_progress(current: int, total: int, detail: str) -> None:
                nonlocal last_progress_emit_at
                now = time.perf_counter()
                if total > 0 and current >= total:
                    last_progress_emit_at = now
                    self.progress_changed.emit(self.request_id, current, total, detail)
                    return
                if now - last_progress_emit_at < 0.75:
                    return
                last_progress_emit_at = now
                self.progress_changed.emit(self.request_id, current, total, detail)

            self.log_message.emit("Checking texture sidecar cache metadata...")
            self.progress_changed.emit(
                self.request_id,
                0,
                0,
                "Checking cache metadata...",
            )
            cached = load_archive_texture_sidecar_cache_rows(
                self.package_root,
                self.cache_root,
                self.entries,
                worker_count=self.sidecar_worker_count,
                on_log=self.log_message.emit,
                stop_event=self.stop_event,
                timings=timings,
                on_progress=_emit_throttled_progress,
            )
            if cached is not None:
                if self.stop_event.is_set():
                    return
                path_rows, basename_rows = cached
                lazy_index_started_at = time.perf_counter()
                self.progress_changed.emit(
                    self.request_id,
                    0,
                    0,
                    "Loading cache rows complete. Preparing lazy lookup indexes...",
                )
                sidecar_entries_by_texture_path = build_lazy_archive_texture_sidecar_entry_index(
                    path_rows,
                    self.entries,
                )
                sidecar_entries_by_texture_basename = build_lazy_archive_texture_sidecar_entry_index(
                    basename_rows,
                    self.entries,
                )
                if self.stop_event.is_set():
                    return
                timings["lazy_index_s"] = max(0.0, float(time.perf_counter() - lazy_index_started_at))
                timings.setdefault("path_row_build_s", 0.0)
                timings.setdefault("basename_row_build_s", 0.0)
                timings.setdefault("entry_resolve_s", 0.0)
                timings.setdefault("cache_write_s", 0.0)
                timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
                timing_summary = _format_timing_summary(
                    "Texture sidecar timings",
                    "cache",
                    timings,
                    (
                        ("cache_check_s", "cache_check"),
                        ("cache_load_s", "cache_load"),
                        ("incremental_remap_s", "remap"),
                        ("incremental_scan_s", "rescan_changed"),
                        ("incremental_update_s", "incremental_update"),
                        ("path_row_build_s", "path_rows"),
                        ("basename_row_build_s", "basename_rows"),
                        ("lazy_index_s", "lazy_index"),
                        ("entry_resolve_s", "resolve"),
                        ("cache_write_s", "cache_write"),
                        ("total_s", "total"),
                    ),
                )
                if not self.stop_event.is_set():
                    self.completed.emit(
                        self.request_id,
                        {
                            "sidecar_entries_by_texture_path": sidecar_entries_by_texture_path,
                            "sidecar_entries_by_texture_basename": sidecar_entries_by_texture_basename,
                            "sidecar_path_rows": path_rows,
                            "sidecar_basename_rows": basename_rows,
                            "source": "cache",
                            "cache_path": str(resolve_archive_sidecar_cache_path(self.package_root, self.cache_root)),
                            "timings": timings,
                            "timing_summary": timing_summary,
                        },
                    )
                return

            self.log_message.emit("Indexing texture sidecar bindings for related-file discovery...")
            self.progress_changed.emit(
                self.request_id,
                0,
                0,
                "Indexing sidecar files...",
            )
            path_rows_started_at = time.perf_counter()
            path_rows = build_archive_texture_sidecar_path_rows(
                self.entries,
                worker_count=self.sidecar_worker_count,
                stop_event=self.stop_event,
                on_progress=_emit_throttled_progress,
                timings=timings,
            )
            timings["path_row_build_s"] = max(0.0, float(time.perf_counter() - path_rows_started_at))
            self.progress_changed.emit(
                self.request_id,
                0,
                0,
                "Building basename lookup...",
            )
            basename_rows_started_at = time.perf_counter()
            basename_rows = build_archive_texture_sidecar_basename_rows(path_rows)
            timings["basename_row_build_s"] = max(0.0, float(time.perf_counter() - basename_rows_started_at))
            lazy_index_started_at = time.perf_counter()
            self.progress_changed.emit(
                self.request_id,
                0,
                0,
                "Preparing lazy sidecar lookup indexes...",
            )
            sidecar_entries_by_texture_path = build_lazy_archive_texture_sidecar_entry_index(path_rows, self.entries)
            sidecar_entries_by_texture_basename = build_lazy_archive_texture_sidecar_entry_index(
                basename_rows,
                self.entries,
            )
            timings["lazy_index_s"] = max(0.0, float(time.perf_counter() - lazy_index_started_at))
            timings["entry_resolve_s"] = 0.0
            if self.stop_event.is_set():
                return
            cache_path_text = ""
            try:
                self.progress_changed.emit(
                    self.request_id,
                    0,
                    0,
                    "Writing cache...",
                )
                cache_path = save_archive_texture_sidecar_cache(
                    self.package_root,
                    self.cache_root,
                    self.entries,
                    path_rows=path_rows,
                    basename_rows=None,
                    on_log=self.log_message.emit,
                    on_progress=lambda current, total, detail: self.progress_changed.emit(
                        self.request_id,
                        current,
                        total,
                        detail,
                    ),
                    stop_event=self.stop_event,
                    timings=timings,
                )
                cache_path_text = str(cache_path)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.log_message.emit(f"Warning: texture sidecar cache could not be written: {exc}")
                timings.setdefault("cache_write_s", 0.0)
            if self.stop_event.is_set():
                return
            self.progress_changed.emit(self.request_id, 1, 1, "Texture sidecar cache is ready.")
            timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
            timing_summary = _format_timing_summary(
                "Texture sidecar timings",
                "scan",
                timings,
                (
                    ("cache_check_s", "cache_check"),
                    ("cache_load_s", "cache_load"),
                    ("path_row_build_s", "path_rows"),
                    ("basename_row_build_s", "basename_rows"),
                    ("lazy_index_s", "lazy_index"),
                    ("entry_resolve_s", "resolve"),
                    ("cache_write_s", "cache_write"),
                    ("total_s", "total"),
                ),
            )
            if not self.stop_event.is_set():
                self.completed.emit(
                    self.request_id,
                    {
                        "sidecar_entries_by_texture_path": sidecar_entries_by_texture_path,
                        "sidecar_entries_by_texture_basename": sidecar_entries_by_texture_basename,
                        "sidecar_path_rows": path_rows,
                        "sidecar_basename_rows": basename_rows,
                        "source": "scan",
                        "cache_path": cache_path_text,
                        "timings": timings,
                        "timing_summary": timing_summary,
                    },
                )
        except RunCancelled as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit(self.request_id)


__all__ = ["ArchiveSidecarIndexWorker"]
