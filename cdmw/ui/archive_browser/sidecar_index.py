"""Archive sidecar index worker orchestration."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QThread, QTimer

from cdmw.services.diagnostics_service import timing_value as _timing_value
from cdmw.workers.archive_sidecar_workers import ArchiveSidecarIndexWorker


class ArchiveSidecarIndexMixin:
    """Texture sidecar index worker lifecycle and compact status."""

    def _start_archive_sidecar_index_worker(self) -> None:
        if self._shutting_down:
            self.archive_sidecar_pending_start = False
            return
        if not self._current_archive_performance_settings().enable_sidecar_indexing:
            self.archive_sidecar_pending_start = False
            self.archive_browser_warmup_pending = False
            self.archive_tree.setEnabled(True)
            return
        if self.archive_sidecar_thread is not None:
            self.archive_sidecar_pending_start = True
            return
        if not self.archive_entries:
            self.archive_sidecar_pending_start = False
            return
        package_root_text = self.archive_package_root_edit.text().strip()
        if not package_root_text:
            self.archive_sidecar_pending_start = False
            return

        self.archive_sidecar_pending_start = False
        request_id = self.archive_sidecar_request_id + 1
        self.archive_sidecar_request_id = request_id
        self._archive_sidecar_last_ui_progress_at = 0.0
        self._archive_sidecar_last_ui_detail = ""
        package_root = Path(package_root_text).expanduser()

        if self.archive_browser_warmup_pending:
            progress_text = "Loading texture sidecar cache..."
        else:
            progress_text = "Checking texture sidecar cache in background..."
        if not self.archive_browser_warmup_pending:
            self.append_archive_log(progress_text)
        self.set_status_message(progress_text)
        self._set_archive_sidecar_status(progress_text)

        worker = ArchiveSidecarIndexWorker(
            request_id,
            package_root,
            self.archive_cache_root,
            self.archive_entries,
            sidecar_worker_count=(
                self._current_archive_performance_settings().sidecar_worker_count
                or self._archive_background_worker_limit()
            ),
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.log_message.connect(self.append_archive_log)
        worker.progress_changed.connect(self._handle_archive_sidecar_progress)
        worker.completed.connect(self._handle_archive_sidecar_complete)
        worker.error.connect(self._handle_archive_sidecar_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_archive_sidecar_refs)

        self.archive_sidecar_worker = worker
        self.archive_sidecar_thread = thread
        try:
            if self.archive_browser_warmup_pending or self._current_archive_performance_settings().maximum_indexing_priority:
                thread.start()
            else:
                thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _compact_archive_sidecar_status_text(self, detail: str, elapsed: float) -> str:
        detail_text = str(detail or "").strip()
        lowered = detail_text.lower()
        if "checking" in lowered and "cache" in lowered:
            phase = "Checking"
        elif "loading" in lowered and "cache" in lowered:
            phase = "Loading"
        elif "indexing" in lowered or "sidecar files" in lowered:
            phase = "Indexing"
        elif "basename" in lowered:
            phase = "Basenames"
        elif "lazy" in lowered or "lookup" in lowered:
            phase = "Lookup"
        elif "writing" in lowered:
            phase = "Writing"
        elif "ready" in lowered or "loaded" in lowered or "indexed" in lowered:
            phase = "Ready"
        elif detail_text:
            phase = detail_text.split("...", 1)[0].split(".", 1)[0][:10].strip() or "Working"
        else:
            phase = "Working"
        elapsed_value = int(max(0.0, elapsed))
        if phase == "Ready":
            return "Sidecar: Ready"
        return f"{phase} {elapsed_value}s"

    def _set_archive_sidecar_status(self, detail: str, current: int = 0, total: int = 0) -> None:
        detail_text = str(detail or "Texture sidecar cache working...").strip()
        if not detail_text:
            detail_text = "Texture sidecar cache working..."
        if float(getattr(self, "_archive_sidecar_status_started_at", 0.0) or 0.0) <= 0.0:
            self._archive_sidecar_status_started_at = time.perf_counter()
        self._archive_sidecar_status_detail = detail_text
        self._archive_sidecar_status_current = max(0, int(current or 0))
        self._archive_sidecar_status_total = max(0, int(total or 0))
        self.archive_sidecar_status_widget.setVisible(True)
        if total > 0:
            completed_value = min(max(int(current), 0), int(total))
            self.archive_sidecar_status_bar.setRange(0, int(total))
            self.archive_sidecar_status_bar.setValue(completed_value)
        else:
            self.archive_sidecar_status_bar.setRange(0, 0)
        self._refresh_archive_sidecar_status_elapsed()
        if not self._archive_sidecar_status_timer.isActive():
            self._archive_sidecar_status_timer.start()

    def _refresh_archive_sidecar_status_elapsed(self) -> None:
        if not hasattr(self, "archive_sidecar_status_label"):
            return
        started_at = float(getattr(self, "_archive_sidecar_status_started_at", 0.0) or 0.0)
        if started_at <= 0.0:
            return
        detail = str(getattr(self, "_archive_sidecar_status_detail", "") or "Texture sidecar cache working...").strip()
        elapsed = max(0.0, time.perf_counter() - started_at)
        self.archive_sidecar_status_label.setText(self._compact_archive_sidecar_status_text(detail, elapsed))
        self.archive_sidecar_status_widget.setToolTip(f"Texture sidecar cache: {detail} ({elapsed:.0f}s)")

    def _finish_archive_sidecar_status(self, detail: str, *, success: bool = True) -> None:
        if not hasattr(self, "archive_sidecar_status_label"):
            return
        started_at = float(getattr(self, "_archive_sidecar_status_started_at", 0.0) or 0.0)
        elapsed = max(0.0, time.perf_counter() - started_at) if started_at > 0.0 else 0.0
        self._archive_sidecar_status_timer.stop()
        self._archive_sidecar_status_started_at = 0.0
        label = str(detail or "Texture sidecar cache complete.").strip()
        if elapsed > 0.0:
            label = f"{label} ({elapsed:.1f}s)"
        self.archive_sidecar_status_label.setText(self._compact_archive_sidecar_status_text(label, elapsed))
        self.archive_sidecar_status_widget.setToolTip(f"Texture sidecar cache: {label}")
        self.archive_sidecar_status_widget.setVisible(True)
        self.archive_sidecar_status_bar.setRange(0, 1)
        self.archive_sidecar_status_bar.setValue(1 if success else 0)

    def _handle_archive_sidecar_progress(self, request_id: int, current: int, total: int, detail: str) -> None:
        if self._shutting_down or request_id != self.archive_sidecar_request_id:
            return
        if self._utility_updates_archive_progress:
            return
        self._set_archive_sidecar_status(detail, current, total)
        now = time.perf_counter()
        last_update_at = float(getattr(self, "_archive_sidecar_last_ui_progress_at", 0.0) or 0.0)
        previous_detail = str(getattr(self, "_archive_sidecar_last_ui_detail", "") or "")
        force_phase_update = bool(total <= 0 and detail and detail != previous_detail)
        if not force_phase_update and (total <= 0 or current < total):
            if now - last_update_at < 0.75:
                return
        self._archive_sidecar_last_ui_progress_at = now
        self._archive_sidecar_last_ui_detail = str(detail or "")
        if self.archive_entries and self.archive_browser_warmup_pending:
            self.archive_stats_label.setText(
                f"{len(self.archive_entries):,} archive entries loaded. {detail}"
            )

    def _handle_archive_sidecar_complete(self, request_id: int, result: object) -> None:
        if self._shutting_down or request_id != self.archive_sidecar_request_id:
            return
        payload = result if isinstance(result, dict) else {}
        self.archive_sidecar_entries_by_texture_path = (
            payload.get("sidecar_entries_by_texture_path", {})
            if isinstance(payload.get("sidecar_entries_by_texture_path"), Mapping)
            else {}
        )
        self.archive_sidecar_entries_by_texture_basename = (
            payload.get("sidecar_entries_by_texture_basename", {})
            if isinstance(payload.get("sidecar_entries_by_texture_basename"), Mapping)
            else {}
        )
        source = str(payload.get("source", "scan")).strip().lower() or "scan"
        cache_path_text = str(payload.get("cache_path", "")).strip()
        timings = payload.get("timings", {}) if isinstance(payload.get("timings"), dict) else {}
        timing_summary = str(payload.get("timing_summary", "")).strip()
        total_seconds = _timing_value(timings, "total_s")
        elapsed_suffix = f" in {total_seconds:.1f}s" if total_seconds > 0 else ""
        completion_text = (
            f"Texture sidecar bindings loaded from cache{elapsed_suffix}."
            if source == "cache"
            else f"Texture sidecar bindings indexed{elapsed_suffix}."
        )
        if self.worker_thread is None and not self._utility_updates_archive_progress:
            self._set_archive_load_progress(completion_text, phase="Ready", percent=100)
            self._set_archive_warmup_overlay(False)
        self._finish_archive_sidecar_status(completion_text, success=True)
        self.set_status_message(completion_text)
        self.append_archive_log(completion_text)
        if cache_path_text and source == "scan":
            self.append_archive_log(f"Texture sidecar cache ready: {cache_path_text}")
        if timing_summary:
            self.append_archive_log(timing_summary, verbose=True)
        sidecar_count = int(_timing_value(timings, "sidecar_count"))
        sidecar_group_count = int(_timing_value(timings, "sidecar_group_count"))
        sidecar_worker_count = int(_timing_value(timings, "sidecar_worker_count"))
        if sidecar_count > 0:
            self.append_archive_log(
                "Texture sidecar scan detail: "
                f"sidecars={sidecar_count:,} | paz_groups={sidecar_group_count:,} | workers={sidecar_worker_count:,}",
                verbose=True,
            )
        if source == "cache" and _timing_value(timings, "total_s") > 1.0:
            self.append_archive_log(
                f"WARNING: Texture sidecar cache hit is slower than expected: total={_timing_value(timings, 'total_s'):.2f}s.",
                verbose=True,
            )

        self.archive_sidecar_generation += 1
        self._clear_archive_preview_cache()
        self._clear_archive_asset_family_cache()
        if self.archive_browser_warmup_pending:
            self.archive_browser_warmup_pending = False
            self.archive_tree.setEnabled(True)
            self._refresh_or_defer_archive_browser_view(
                activate_tab=self._activate_archive_browser_on_scan_complete,
            )
            self._activate_archive_browser_on_scan_complete = False
            self._refresh_or_defer_research_archive_picker()
            completion_text = self.archive_browser_warmup_completion_text or (
                f"Archive scan complete. Found {len(self.archive_entries):,} entries."
            )
            self.archive_browser_warmup_completion_text = ""
            self.archive_stats_label.setText(
                f"{len(self.archive_entries):,} archive entries loaded. Texture sidecar cache ready."
            )
            self._set_archive_load_progress(completion_text, phase="Ready", percent=100)
            self._set_archive_warmup_overlay(False)
            self.set_status_message(completion_text)
            self.append_archive_log(completion_text)
            if self.worker_thread is None:
                self.set_busy(False, build_mode=False)
            return
        current_entry = self._current_archive_entry()
        current_result_generation = int(
            getattr(self.current_archive_preview_result, "sidecar_generation", -1)
            if self.current_archive_preview_result is not None
            else -1
        )
        if (
            current_entry is not None
            and self.archive_preview_thread is None
            and not self.archive_preview_showing_loose
            and (
                self.current_archive_preview_result is None
                or current_result_generation < self.archive_sidecar_generation
                or not self.current_archive_model_texture_references
            )
        ):
            QTimer.singleShot(0, lambda entry=current_entry: self._render_archive_preview(entry))

    def _handle_archive_sidecar_error(self, request_id: int, message: str) -> None:
        if self._shutting_down or request_id != self.archive_sidecar_request_id:
            return
        error_text = f"Texture sidecar indexing failed: {message}"
        self.set_status_message(error_text, error=True)
        self.append_log(f"ERROR: {error_text}")
        self.append_archive_log(f"ERROR: {error_text}")
        if self.worker_thread is None and not self._utility_updates_archive_progress:
            self._set_archive_load_progress(error_text, phase="Failed", percent=0, allow_decrease=True)
        self._finish_archive_sidecar_status(error_text, success=False)
        self._set_archive_warmup_overlay(False)
        if self.archive_browser_warmup_pending:
            self.archive_browser_warmup_pending = False
            self.archive_tree.setEnabled(True)
            self._refresh_or_defer_archive_browser_view(
                activate_tab=self._activate_archive_browser_on_scan_complete,
            )
            self._activate_archive_browser_on_scan_complete = False
            self._refresh_or_defer_research_archive_picker()
            if self.worker_thread is None:
                self.set_busy(False, build_mode=False)

    def _cleanup_archive_sidecar_refs(self) -> None:
        self.archive_sidecar_thread = None
        self.archive_sidecar_worker = None
        if self._shutting_down:
            self.archive_sidecar_pending_start = False
            return
        if self.archive_sidecar_pending_start and self._current_archive_performance_settings().enable_sidecar_indexing:
            QTimer.singleShot(0, self._start_archive_sidecar_index_worker)
        else:
            self.archive_sidecar_pending_start = False


__all__ = ["ArchiveSidecarIndexMixin"]
