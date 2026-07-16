"""Native preview package prefetch helpers for the archive browser."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import QThread

from cdmw.models import ArchiveEntry
from cdmw.services.preview_rendering_service import (
    lookup_native_preview_package_cache,
    native_preview_package_prefetch_limit,
)
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11
from cdmw.ui.shell.diagnostics_controller import windows_process_memory_snapshot as _windows_process_memory_snapshot
from cdmw.workers.archive_preview_native import NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker
from cdmw.workers.d3d11_package_workers import ArchiveNativePreviewPrefetchWorker


def _record_archive_prefetch_lifecycle(target: object, event: str, **fields: object) -> None:
    recorder = getattr(target, "_record_runtime_event", None)
    if callable(recorder):
        try:
            recorder(str(event), **fields)
        except Exception:
            return


class ArchivePreviewNativePrefetchMixin:
    """Visible-neighbor native preview package prefetch orchestration."""

    def _archive_native_prefetch_candidate_entries(self) -> Tuple[ArchiveEntry, ...]:
        if self._native_preview_package_cache_mode() != "aggressive":
            return ()
        if self.archive_preview_thread is not None or self.archive_native_prefetch_thread is not None:
            return ()
        try:
            memory_snapshot = _windows_process_memory_snapshot(os.getpid())
            if int(memory_snapshot.get("private_bytes", 0) or 0) > 3500 * 1024 * 1024:
                return ()
        except Exception as exc:
            _record_archive_prefetch_lifecycle(
                self,
                "archive_native_prefetch_memory_probe_failed",
                reason="worker_failed",
                error=str(exc),
            )
        current_entry = self._current_archive_entry()
        if current_entry is None:
            return ()
        filtered_entries = tuple(getattr(self, "archive_filtered_entries", ()) or ())
        if not filtered_entries:
            return ()
        try:
            current_index = next(
                index
                for index, candidate in enumerate(filtered_entries)
                if str(getattr(candidate, "path", "") or "") == str(getattr(current_entry, "path", "") or "")
            )
        except StopIteration:
            return ()
        limit = native_preview_package_prefetch_limit(self._native_preview_package_cache_mode())
        if limit <= 0:
            return ()
        result: List[ArchiveEntry] = []
        for offset in (1, -1, 2, -2):
            if len(result) >= limit:
                break
            candidate_index = current_index + offset
            if candidate_index < 0 or candidate_index >= len(filtered_entries):
                continue
            candidate = filtered_entries[candidate_index]
            if str(getattr(candidate, "extension", "") or "").strip().lower() not in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS:
                continue
            companion_entry = self._find_archive_preview_companion_entry(candidate)
            cache_key = self._archive_native_preview_package_cache_key(
                candidate,
                companion_entry,
                self._collect_archive_preview_loose_roots(),
            )
            if not cache_key:
                continue
            if lookup_native_preview_package_cache(
                self._native_preview_package_cache_root(),
                cache_key,
                validate_package=self._validate_d3d11_preview_package_paths,
            ) is not None:
                continue
            result.append(candidate)
        return tuple(result)

    def _start_archive_native_preview_prefetch(self) -> None:
        if self._shutting_down:
            return
        if self._archive_model_renderer_backend() != ARCHIVE_MODEL_RENDERER_D3D11:
            return
        entries = self._archive_native_prefetch_candidate_entries()
        if not entries:
            return
        self.archive_native_prefetch_request_id += 1
        if self.archive_native_prefetch_worker is not None:
            _record_archive_prefetch_lifecycle(
                self,
                "archive_native_prefetch_cancelled",
                reason="cancelled_by_new_request",
                request_id=self.archive_native_prefetch_request_id,
            )
            self.archive_native_prefetch_worker.stop()
        if self.archive_native_prefetch_thread is not None:
            return
        render_settings = self._current_model_preview_render_settings()
        package_root = (
            Path(self.archive_package_root_edit.text().strip()).expanduser()
            if self.archive_package_root_edit.text().strip()
            else None
        )
        cache_mode = self._native_preview_package_cache_mode()
        cache_max_bytes, cache_target_bytes = self._native_preview_package_cache_budget()
        loose_search_roots = self._collect_archive_preview_loose_roots()
        jobs = tuple(
            (
                entry,
                self._find_archive_preview_companion_entry(entry),
                self._archive_native_preview_package_cache_key(
                    entry,
                    self._find_archive_preview_companion_entry(entry),
                    loose_search_roots,
                ),
            )
            for entry in entries
        )
        worker = ArchiveNativePreviewPrefetchWorker(
            jobs,
            render_settings,
            self.archive_cache_root / "native_preview_core",
            package_root,
            cache_mode,
            cache_max_bytes,
            cache_target_bytes,
            validate_package=ArchivePreviewWorker._validate_native_preview_core_package_basic,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_archive_native_prefetch_refs)
        self.archive_native_prefetch_worker = worker
        self.archive_native_prefetch_thread = thread
        thread.start()

    def _cleanup_archive_native_prefetch_refs(self) -> None:
        self.archive_native_prefetch_worker = None
        self.archive_native_prefetch_thread = None

    def _stop_archive_native_preview_prefetch(self) -> None:
        if hasattr(self, "archive_native_prefetch_timer"):
            self.archive_native_prefetch_timer.stop()
        if self.archive_native_prefetch_worker is not None:
            _record_archive_prefetch_lifecycle(
                self,
                "archive_native_prefetch_cancelled",
                reason="cancelled_by_shutdown" if self._shutting_down else "cancelled_by_filter_change",
            )
            try:
                self.archive_native_prefetch_worker.stop()
            except Exception as exc:
                _record_archive_prefetch_lifecycle(
                    self,
                    "archive_native_prefetch_failed",
                    reason="worker_failed",
                    error=str(exc),
                )
