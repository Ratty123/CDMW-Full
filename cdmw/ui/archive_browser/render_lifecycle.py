"""Archive browser render readiness and post-ready background work."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Callable, List, Optional

from PySide6.QtCore import QTimer

from cdmw.domain.archives.filters import normalize_archive_browser_sort_column
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget


class ArchiveRenderLifecycleMixin:
    """Archive browser render-ready state and deferred background work."""

    def _ensure_archive_basic_index_worker_started(self) -> bool:
        if not self._archive_basic_index_missing_for_lookup():
            return False
        if self.archive_basic_index_thread is None:
            self.archive_deferred_basic_index_start_pending = False
            self.archive_basic_index_state = "warming"
            QTimer.singleShot(0, self._start_archive_basic_index_worker)
        return True

    def _ensure_archive_enhanced_index_worker_started(self) -> bool:
        if not self._archive_enhanced_index_missing_for_search():
            return False
        if self.archive_enhanced_index_thread is None:
            self.archive_deferred_enhanced_index_start_pending = False
            self.archive_enhanced_index_state = "warming"
            self.archive_enhanced_index_activity = "loading"
            QTimer.singleShot(0, self._start_archive_enhanced_index_worker)
        return True

    def _schedule_archive_enhanced_index_auto_prewarm(self, delay_ms: int = 900) -> None:
        if self._shutting_down or self._startup_benchmark_enabled():
            return
        if not bool(getattr(self, "archive_enhanced_index_auto_prewarm_pending", False)):
            return
        QTimer.singleShot(max(0, int(delay_ms)), self._start_archive_enhanced_index_auto_prewarm)

    def _start_archive_enhanced_index_auto_prewarm(self) -> None:
        if self._shutting_down or self._startup_benchmark_enabled():
            return
        if not bool(getattr(self, "archive_enhanced_index_auto_prewarm_pending", False)):
            return
        if (
            getattr(self, "_startup_splash_window", None) is not None
            or bool(getattr(self, "archive_startup_hold_until_ready", False))
            or not self.archive_browser_first_visible_paint_done
            or self.worker_thread is not None
        ):
            self._schedule_archive_enhanced_index_auto_prewarm(900)
            return
        if self._ensure_archive_enhanced_index_worker_started():
            self.append_archive_log("Item-name search cache warming after archive list opened.")

    def _archive_background_search_ready(self) -> bool:
        return (
            str(getattr(self, "archive_basic_index_state", "idle") or "idle") in {"ready", "idle", "failed"}
            and str(getattr(self, "archive_enhanced_index_state", "idle") or "idle") in {"ready", "idle", "failed"}
            and self.archive_derived_cache_thread is None
            and not self.archive_derived_cache_write_pending
            and not self.archive_deferred_derived_cache_write_pending
        )

    def _archive_status_text(self, base_text: str = "") -> str:
        pending: List[str] = []
        if str(getattr(self, "archive_basic_index_state", "") or "") == "warming":
            pending.append("Building path lookup")
        if str(getattr(self, "archive_enhanced_index_state", "") or "") == "warming":
            activity = str(getattr(self, "archive_enhanced_index_activity", "") or "").lower()
            pending.append("Loading archive search cache" if activity == "loading" else "Preparing archive search cache")
        if (
            self.archive_derived_cache_thread is not None
            or self.archive_derived_cache_write_pending
            or self.archive_deferred_derived_cache_write_pending
        ):
            pending.append("Saving archive search cache")
        if bool(getattr(self, "archive_startup_saved_filter_apply_pending", False)):
            pending.append("Filters will apply when search is ready")
        if pending:
            prefix = str(base_text or "Archive list available").strip()
            if "archive list available" not in prefix.lower():
                prefix = "Archive list available"
            return f"{prefix}. " + "; ".join(pending) + "."
        clean_base = str(base_text or "").strip()
        if clean_base.startswith("Applied archive filters"):
            return clean_base
        return "Archive ready."

    def _archive_progress_format_text(self) -> str:
        return f"{min(max(int(getattr(self, '_archive_load_progress_percent', 100)), 0), 100)}%"

    def _set_archive_list_status(self, base_text: str = "Archive list available") -> None:
        status_text = self._archive_status_text(base_text)
        if self._archive_background_search_ready():
            self._set_archive_load_progress(status_text, phase="Ready", percent=100)
        else:
            self._set_archive_load_progress(status_text, phase="Indexing", percent=90)
        self.set_status_message(status_text)

    def _startup_archive_core_ready(self) -> bool:
        return (
            self._startup_archive_browser_render_ready()
            and self.worker_thread is None
            and not self.archive_scan_finalize_pending
        )

    def _startup_archive_browser_render_ready(self) -> bool:
        if not self.archive_entries:
            return True
        if not self._is_tool_visible_or_current(self.archive_browser_tab):
            return True
        return bool(self._archive_browser_render_is_ready())

    def _maybe_release_startup_after_archive_ready(self) -> None:
        if not bool(getattr(self, "archive_startup_hold_until_ready", False)):
            return
        if getattr(self, "_startup_splash_window", None) is None:
            self.archive_startup_hold_until_ready = False
            self.archive_startup_index_warmup_required = False
            self._schedule_archive_post_ready_background_work()
            return
        if self.archive_startup_saved_filter_apply_pending:
            self._try_apply_startup_saved_filters()
            if self.archive_startup_saved_filter_apply_pending or self.worker_thread is not None:
                QTimer.singleShot(750, self._maybe_release_startup_after_archive_ready)
                return
        if not self._startup_archive_core_ready():
            if not self._archive_startup_progress_work_active():
                if not self._startup_archive_browser_render_ready():
                    self._update_startup_splash("Rendering archive browser view...", 90, 100)
                else:
                    self._update_startup_splash(self._archive_status_text("Archive list available"), 0, 0)
            QTimer.singleShot(1000, self._maybe_release_startup_after_archive_ready)
            return
        self.archive_startup_hold_until_ready = False
        self.archive_startup_index_warmup_required = False
        self._update_startup_splash("Archive ready.", 1, 1)
        self._write_heartbeat("running")
        self._release_startup_splash()
        self._schedule_archive_post_ready_background_work()

    def _try_apply_startup_saved_filters(self) -> None:
        if self._shutting_down or not bool(getattr(self, "archive_startup_saved_filter_apply_pending", False)):
            return
        saved_state = getattr(self, "archive_startup_saved_filter_state", {}) or {}
        if not isinstance(saved_state, Mapping):
            self.archive_startup_saved_filter_apply_pending = False
            return
        allow_hidden_startup_filter = bool(getattr(self, "archive_startup_hold_until_ready", False))
        if not self.archive_browser_first_visible_paint_done and not allow_hidden_startup_filter:
            return
        waits_for_item_search = self._archive_filter_state_waits_for_item_search(saved_state)
        if waits_for_item_search:
            self._ensure_archive_enhanced_index_worker_started()
            if not self.archive_startup_saved_filter_wait_logged:
                self.archive_startup_saved_filter_wait_logged = True
                self.append_archive_log("Filters will apply when item-name search is ready.")
                self._set_archive_list_status("Archive list available")
            return
        if (
            self._archive_filter_state_explicitly_requires_item_search(saved_state)
            and self._archive_enhanced_index_missing_for_search()
            and not self._startup_benchmark_enabled()
        ):
            self.archive_enhanced_filter_refresh_pending = True
            self._ensure_archive_enhanced_index_worker_started()
        needs_basic_lookup = self._archive_filter_state_needs_basic_lookup(saved_state)
        if needs_basic_lookup and self._archive_basic_index_missing_for_lookup():
            self._ensure_archive_basic_index_worker_started()
            if not self.archive_startup_saved_filter_wait_logged:
                self.archive_startup_saved_filter_wait_logged = True
                self.append_archive_log("Filters will apply when archive lookup indexes are ready.")
                self._set_archive_list_status("Archive list available")
            return
        if self.worker_thread is not None:
            QTimer.singleShot(300, self._try_apply_startup_saved_filters)
            return
        self.archive_startup_saved_filter_apply_pending = False
        self.archive_startup_saved_filter_wait_logged = False
        self._apply_archive_filter_state(saved_state)
        self.archive_filters_dirty = True
        self._update_archive_filter_button_state()
        self.append_archive_log("Applying queued filters after archive list opened.")
        self._apply_archive_filter()

    def _archive_sort_waits_for_enhanced_index(self) -> bool:
        column = normalize_archive_browser_sort_column(self.archive_tree_sort_column)
        return column == 1 and self._archive_enhanced_index_missing_for_search()

    def _schedule_archive_initial_sort_after_first_paint(self, delay_ms: int = 250) -> None:
        if self._shutting_down or not self.archive_initial_sort_apply_pending:
            return
        QTimer.singleShot(max(0, int(delay_ms)), self._apply_archive_initial_sort_after_first_paint)

    def _apply_archive_initial_sort_after_first_paint(self) -> None:
        if self._shutting_down or not self.archive_initial_sort_apply_pending:
            return
        if self.worker_thread is not None:
            self._schedule_archive_initial_sort_after_first_paint(300)
            return
        if self._archive_sort_waits_for_enhanced_index():
            self._ensure_archive_enhanced_index_worker_started()
            self.append_archive_log(
                "Archive column sort is waiting for item-name search before applying name evidence order.",
                verbose=True,
            )
            self._schedule_archive_initial_sort_after_first_paint(700)
            return
        current_entry = self._current_archive_entry()
        preferred_path = current_entry.path if current_entry is not None else ""
        self.archive_initial_sort_apply_pending = False
        self.append_archive_log("Applying deferred archive column sort after first paint.", verbose=True)
        if self.archive_entries:
            self._start_archive_filter_worker(preferred_path)
        else:
            self._sort_current_archive_filtered_entries()
            self._rebuild_archive_browser_indexes_for_current_sort()
            self._populate_archive_tree(preferred_path, rebuild_index=False)

    def _invalidate_archive_browser_name_columns(self) -> None:
        self.archive_browser_row_display_cache.clear()
        if hasattr(self.archive_tree, "invalidate_archive_rows"):
            self.archive_tree.invalidate_archive_rows((1,))
            return
        current_entry = self._current_archive_entry()
        preferred_path = current_entry.path if current_entry is not None else ""
        self._populate_archive_tree(preferred_path, rebuild_index=False, defer_default_selection=True)

    def _schedule_archive_pending_enhanced_filter_refresh(self, delay_ms: int = 250) -> None:
        if self._shutting_down or not self.archive_enhanced_filter_refresh_pending:
            return
        QTimer.singleShot(max(0, int(delay_ms)), self._apply_pending_archive_enhanced_filter_refresh)

    def _apply_pending_archive_enhanced_filter_refresh(self) -> None:
        if self._shutting_down or not self.archive_enhanced_filter_refresh_pending:
            return
        if not self.archive_filter_edit.text().strip() or self.archive_filters_dirty:
            self.archive_enhanced_filter_refresh_pending = False
            return
        if not self._is_tool_visible_or_current(self.archive_browser_tab):
            self.append_archive_log(
                "Archive Browser activation timing | cause=item_search_filter_refresh | state=deferred",
                verbose=True,
            )
            return
        if (
            self.worker_thread is not None
            or (
                self._archive_saved_filter_needs_item_search(self._capture_archive_filter_state())
                and self._archive_enhanced_index_missing_for_search()
            )
            or (
                self._current_archive_filter_needs_basic_lookup()
                and self._archive_basic_index_missing_for_lookup()
            )
        ):
            if self._archive_saved_filter_needs_item_search(self._capture_archive_filter_state()):
                self._ensure_archive_enhanced_index_worker_started()
            if self._current_archive_filter_needs_basic_lookup():
                self._ensure_archive_basic_index_worker_started()
            self.append_archive_log(
                "Archive Browser activation timing | cause=item_search_filter_refresh | state=deferred",
                verbose=True,
            )
            self._schedule_archive_pending_enhanced_filter_refresh(500)
            return
        current_entry = self._current_archive_entry()
        preferred_path = current_entry.path if current_entry is not None else ""
        self.archive_enhanced_filter_refresh_pending = False
        self.append_archive_log(
            "Archive Browser activation timing | cause=item_search_filter_refresh | state=applied",
            verbose=True,
        )
        self._start_archive_filter_worker(preferred_path)

    def _archive_browser_render_is_ready(self) -> bool:
        return (
            self.archive_browser_preload_state == "ready"
            and bool(self.archive_browser_render_signature)
            and self.archive_browser_render_signature == self._current_archive_browser_render_signature()
            and not self.archive_filters_dirty
        )

    def _refresh_archive_browser_view(
        self,
        on_complete: Optional[Callable[[], None]] = None,
        *,
        reason: str = "refresh",
    ) -> None:
        if self._archive_browser_render_is_ready():
            self.append_archive_log(
                f"Archive Browser activation timing | cause={reason} | skipped=ready",
                verbose=True,
            )
            if on_complete is not None:
                QTimer.singleShot(0, on_complete)
            return
        self.archive_browser_preload_state = "rendering"
        self.archive_browser_render_signature = ()
        self.archive_browser_render_started_at = time.perf_counter()
        self.archive_browser_render_reason = reason
        QTimer.singleShot(
            0,
            lambda on_complete=on_complete, reason=reason: self._refresh_archive_browser_view_stage_controls(
                on_complete=on_complete,
                reason=reason,
            ),
        )

    def _log_archive_browser_render_stage(self, stage: str, started_at: float) -> None:
        elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        total_ms = 0.0
        if self.archive_browser_render_started_at:
            total_ms = max(0.0, (time.perf_counter() - self.archive_browser_render_started_at) * 1000.0)
        self.append_archive_log(
            "Archive Browser activation timing | "
            f"cause={self.archive_browser_render_reason or 'refresh'} | "
            f"stage={stage} | elapsed={elapsed_ms:.0f}ms | total={total_ms:.0f}ms",
            verbose=True,
        )

    def _refresh_archive_browser_view_stage_controls(
        self,
        *,
        on_complete: Optional[Callable[[], None]],
        reason: str,
    ) -> None:
        if self._shutting_down:
            return
        if self._archive_browser_render_is_ready():
            if on_complete is not None:
                QTimer.singleShot(0, on_complete)
            return
        started_at = time.perf_counter()
        self._rebuild_archive_extension_filter_choices()
        self._rebuild_archive_structure_filter_controls(defer_missing_children=True)
        self._log_archive_browser_render_stage("controls", started_at)
        rebuild_tree_index = self._archive_folder_tree_enabled() and not self.archive_tree_index_ready
        rebuild_category_index = (
            self._archive_category_view_enabled()
            and self.archive_filtered_entries
            and not self._archive_category_index_ready()
        )
        if (rebuild_tree_index or rebuild_category_index) and self.archive_entries:
            current_entry = self._current_archive_entry()
            current_entry_path = current_entry.path if current_entry is not None else ""
            self.archive_browser_refresh_pending = False
            if self.worker_thread is None:
                self._start_archive_filter_worker(
                    current_entry_path,
                    build_category_index=rebuild_category_index,
                )
            else:
                self.archive_browser_refresh_pending = True
                if on_complete is not None:
                    QTimer.singleShot(0, on_complete)
            return
        defer_default_selection = bool(getattr(self, "archive_startup_autoload_defer_preview", False)) or (
            reason == "tab_activation"
            and self.archive_tree.currentItem() is None
            and not self.archive_preview_showing_loose
        )
        self.archive_startup_autoload_defer_preview = False
        QTimer.singleShot(
            0,
            lambda rebuild_tree_index=rebuild_tree_index, on_complete=on_complete, defer_default_selection=defer_default_selection: self._refresh_archive_browser_view_stage_populate(
                rebuild_tree_index=rebuild_tree_index,
                on_complete=on_complete,
                defer_default_selection=defer_default_selection,
            ),
        )

    def _refresh_archive_browser_view_stage_populate(
        self,
        *,
        rebuild_tree_index: bool,
        on_complete: Optional[Callable[[], None]],
        defer_default_selection: bool,
    ) -> None:
        started_at = time.perf_counter()
        self._populate_archive_tree(
            rebuild_index=rebuild_tree_index,
            on_complete=on_complete,
            defer_default_selection=defer_default_selection,
        )
        self._log_archive_browser_render_stage("populate_call", started_at)
        self.archive_browser_refresh_pending = False

    def _refresh_archive_browser_if_pending(self, reason: str = "pending_refresh") -> None:
        if not self.archive_browser_refresh_pending:
            return
        if self._archive_browser_render_is_ready():
            self.archive_browser_refresh_pending = False
            self.append_archive_log(
                f"Archive Browser activation timing | cause={reason} | skipped=ready",
                verbose=True,
            )
            return
        self.append_archive_log(
            f"Archive Browser activation timing | cause={reason} | pending_refresh=start",
            verbose=True,
        )
        self._refresh_archive_browser_view(reason=reason)

    def _refresh_or_defer_archive_browser_view(
        self,
        *,
        activate_tab: bool,
        on_complete: Optional[Callable[[], None]] = None,
        force_render: bool = False,
    ) -> None:
        if activate_tab:
            self._activate_tool_widget(self.archive_browser_tab)
        if force_render or self._is_tool_visible_or_current(self.archive_browser_tab):
            self._refresh_archive_browser_view(
                on_complete=on_complete,
                reason="startup_preload" if force_render else "visible_refresh",
            )
        else:
            self.archive_browser_refresh_pending = True
            self.archive_startup_autoload_defer_preview = False
            if on_complete is not None:
                QTimer.singleShot(0, on_complete)

    def _refresh_or_defer_research_archive_picker(self) -> None:
        research_tab = created_tool_widget(getattr(self, "research_tab", None))
        if research_tab is None:
            return
        if self._is_tool_visible_or_current(self.research_tab):
            research_tab.refresh_archive_picker()
        else:
            research_tab.mark_archive_picker_dirty()

    def _mark_archive_browser_render_stale(self) -> None:
        if self.archive_browser_preload_state == "rendering":
            return
        self.archive_browser_preload_state = "stale" if self.archive_entries else "idle"
        self.archive_browser_render_signature = ()
        self.archive_browser_first_visible_paint_done = False

    def _mark_archive_browser_render_ready(self, *, reason: str, on_complete: Optional[Callable[[], None]] = None) -> None:
        self.archive_browser_preload_state = "ready"
        self.archive_browser_render_signature = self._current_archive_browser_render_signature()
        self.archive_browser_refresh_pending = False
        self.archive_browser_ready_at = time.perf_counter()
        self.append_archive_log(
            f"Archive Browser activation timing | cause={reason} | state=ready | rows={len(self.archive_filtered_entries):,}",
            verbose=True,
        )
        if self._is_tool_visible_or_current(self.archive_browser_tab):
            self.archive_browser_first_visible_started_at = time.perf_counter()
            self._schedule_archive_browser_first_visible_paint_marker()
        self._schedule_archive_post_ready_background_work()
        if on_complete is not None:
            delay_ms = max(1, int(self.archive_selection_state_timer.interval()) + 1)
            QTimer.singleShot(delay_ms, on_complete)

    def _archive_browser_background_work_allowed(self) -> bool:
        if self._shutting_down or self.archive_browser_preload_state != "ready":
            return False
        now = time.perf_counter()
        if not self.archive_browser_first_visible_paint_done:
            return False
        return (now - float(self.archive_browser_first_visible_painted_at or now)) >= 0.45

    def _schedule_archive_browser_first_visible_paint_marker(self, delay_ms: int = 16) -> None:
        if self._shutting_down or not self.isVisible() or not self._is_tool_visible_or_current(self.archive_browser_tab):
            return
        try:
            self.archive_tree.viewport().update()
        except Exception as exc:
            recorder = getattr(self, "_record_runtime_event", None)
            if callable(recorder):
                recorder("archive_browser_viewport_update_failed", reason="worker_failed", error=str(exc))
        QTimer.singleShot(max(0, int(delay_ms)), self._handle_archive_browser_first_visible_paint)

    def _schedule_archive_post_ready_background_work(self, delay_ms: Optional[int] = None) -> None:
        if self.archive_deferred_background_start_pending or self._shutting_down:
            return
        self.archive_deferred_background_start_pending = True
        if delay_ms is None:
            delay_ms = 550 if self.archive_browser_first_visible_paint_done else 2000
        QTimer.singleShot(max(0, int(delay_ms)), self._start_archive_deferred_background_work)

    def _start_archive_deferred_background_work(self) -> None:
        self.archive_deferred_background_start_pending = False
        if self._shutting_down:
            return
        startup_hold = bool(getattr(self, "archive_startup_hold_until_ready", False))
        browser_visible = self._is_tool_visible_or_current(self.archive_browser_tab)
        background_allowed = bool(startup_hold or (not browser_visible) or self._archive_browser_background_work_allowed())
        if self.archive_deferred_basic_index_start_pending and self.archive_basic_index_thread is None:
            if not background_allowed:
                self._schedule_archive_post_ready_background_work(250)
                return
            self.archive_deferred_basic_index_start_pending = False
            self._start_archive_basic_index_worker()
            self._schedule_archive_post_ready_background_work(900)
            return
        if not background_allowed:
            self._schedule_archive_post_ready_background_work(
                250 if browser_visible else 1000
            )
            return
        if (
            self.archive_basic_index_thread is not None
            or
            self.archive_enhanced_index_thread is not None
            or self.archive_derived_cache_thread is not None
            or self.archive_sidecar_thread is not None
        ):
            self._schedule_archive_post_ready_background_work(900)
            return
        if self.archive_deferred_enhanced_index_start_pending and self.archive_enhanced_index_thread is None:
            self.archive_deferred_enhanced_index_start_pending = False
            self._start_archive_enhanced_index_worker()
            self._schedule_archive_post_ready_background_work(900)
            return
        if self.archive_deferred_derived_cache_write_pending and self.archive_derived_cache_thread is None:
            self.archive_deferred_derived_cache_write_pending = False
            self._start_archive_derived_index_cache_writer()
            self._schedule_archive_post_ready_background_work(900)
            return
        if startup_hold:
            self._maybe_release_startup_after_archive_ready()
            return
        if self.archive_deferred_sidecar_start_pending:
            self.archive_deferred_sidecar_start_pending = False
            if self.worker_thread is None and self.archive_sidecar_thread is None:
                self.append_archive_log("Archive Browser activation timing | cause=sidecar_index | start=deferred", verbose=True)
                self._start_archive_sidecar_index_worker()
                self._schedule_archive_post_ready_background_work(900)
                return
        if self.archive_item_icon_preload_pending_after_ready:
            self.archive_item_icon_preload_pending_after_ready = False
            self.append_archive_log("Archive Browser activation timing | cause=icon_warmup | start=deferred", verbose=True)
            self._schedule_archive_asset_catalog_icon_preload(delay_ms=700)

    def _handle_archive_browser_first_visible_paint(self) -> None:
        if self._shutting_down or not self.isVisible() or not self._is_tool_visible_or_current(self.archive_browser_tab):
            return
        if not self.archive_browser_first_visible_paint_done:
            self.archive_browser_first_visible_paint_done = True
            self.archive_browser_first_visible_painted_at = time.perf_counter()
            elapsed_ms = max(
                0.0,
                (self.archive_browser_first_visible_painted_at - float(self.archive_browser_first_visible_started_at or self.archive_browser_first_visible_painted_at)) * 1000.0,
            )
            self.append_archive_log(
                f"Archive Browser activation timing | cause=first_paint | elapsed={elapsed_ms:.0f}ms",
                verbose=True,
            )
            self._record_runtime_event("first_paint", surface="archive_browser", elapsed_ms=elapsed_ms)
            if (
                getattr(self, "_startup_splash_window", None) is not None
                and float(getattr(self, "_startup_splash_finish_after_paint_deadline", 0.0) or 0.0) > 0.0
            ):
                self._schedule_startup_splash_finish_after_main_window_paint(80)
        self._schedule_archive_post_ready_background_work(550)
        if self.archive_initial_sort_apply_pending:
            self._schedule_archive_initial_sort_after_first_paint(150)
        self._try_apply_startup_saved_filters()
        self._schedule_archive_enhanced_index_auto_prewarm()


__all__ = ["ArchiveRenderLifecycleMixin"]
