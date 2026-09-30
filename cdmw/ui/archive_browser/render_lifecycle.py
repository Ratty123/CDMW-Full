"""Archive browser render readiness and post-ready background work."""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget


class ArchiveRenderLifecycleMixin:
    """Archive browser render-ready state and deferred background work."""


    def _archive_progress_format_text(self) -> str:
        return f"{min(max(int(getattr(self, '_archive_load_progress_percent', 100)), 0), 100)}%"

    def _set_archive_list_status(self, base_text: str = "Archive list available") -> None:
        status_text = base_text
        if not self.archive_remote_query_pending:
            self._set_archive_load_progress(status_text, phase="Ready", percent=100)
        else:
            self._set_archive_load_progress(status_text, phase="Indexing", percent=90)
        self.shell.set_status_message(status_text)

    def _startup_archive_core_ready(self) -> bool:
        return (
            self._startup_archive_browser_render_ready()
            and self.shell.worker_thread is None
        )

    def _startup_archive_browser_render_ready(self) -> bool:
        if not self.archive_entries:
            return True
        if not self.shell._is_tool_visible_or_current(self.shell.archive_browser_tab):
            return True
        return bool(self._archive_browser_render_is_ready())

    def _maybe_release_startup_after_archive_ready(self) -> None:
        if not bool(getattr(self, "archive_startup_hold_until_ready", False)):
            return
        if getattr(self.shell, "_startup_splash_window", None) is None:
            self.archive_startup_hold_until_ready = False
            self.archive_startup_index_warmup_required = False
            self._schedule_archive_post_ready_background_work()
            return
        if self.archive_startup_saved_filter_apply_pending:
            self._try_apply_startup_saved_filters()
            if self.archive_startup_saved_filter_apply_pending or self.shell.worker_thread is not None:
                QTimer.singleShot(750, self._maybe_release_startup_after_archive_ready)
                return
        if not self._startup_archive_core_ready():
            if not self.shell._archive_startup_progress_work_active():
                if not self._startup_archive_browser_render_ready():
                    self.shell._update_startup_splash("Rendering archive browser view...", 90, 100)
                else:
                    self.shell._update_startup_splash("Archive list available", 0, 0)
            QTimer.singleShot(1000, self._maybe_release_startup_after_archive_ready)
            return
        self.archive_startup_hold_until_ready = False
        self.archive_startup_index_warmup_required = False
        self.shell._update_startup_splash("Archive ready.", 1, 1)
        self.shell._write_heartbeat("running")
        self.shell._release_startup_splash()
        self._schedule_archive_post_ready_background_work()


    def _invalidate_archive_browser_name_columns(self) -> None:
        self.archive_browser_row_display_cache.clear()
        if hasattr(self.archive_tree, "invalidate_archive_rows"):
            self.archive_tree.invalidate_archive_rows((1,))
            return
        current_entry = self._current_archive_entry()
        preferred_path = current_entry.path if current_entry is not None else ""
        self._populate_archive_tree(preferred_path, rebuild_index=False, defer_default_selection=True)


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
            self.shell.append_archive_log(
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
        self.shell.append_archive_log(
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
        if self.shell._shutting_down:
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
            if self.shell.worker_thread is None:
                self._submit_archive_filter(
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
            self.shell.append_archive_log(
                f"Archive Browser activation timing | cause={reason} | skipped=ready",
                verbose=True,
            )
            return
        self.shell.append_archive_log(
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
            self.shell._activate_tool_widget(self.shell.archive_browser_tab)
        if force_render or self.shell._is_tool_visible_or_current(self.shell.archive_browser_tab):
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
        research_tab = created_tool_widget(getattr(self.shell, "research_tab", None))
        if research_tab is None:
            return
        if self.shell._is_tool_visible_or_current(self.shell.research_tab):
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
        self.shell.append_archive_log(
            f"Archive Browser activation timing | cause={reason} | state=ready | rows={len(self.archive_filtered_entries):,}",
            verbose=True,
        )
        if self.shell._is_tool_visible_or_current(self.shell.archive_browser_tab):
            self.archive_browser_first_visible_started_at = time.perf_counter()
            self._schedule_archive_browser_first_visible_paint_marker()
        self._schedule_archive_post_ready_background_work()
        if on_complete is not None:
            delay_ms = max(1, int(self.archive_selection_state_timer.interval()) + 1)
            QTimer.singleShot(delay_ms, on_complete)

    def _archive_browser_background_work_allowed(self) -> bool:
        if self.shell._shutting_down or self.archive_browser_preload_state != "ready":
            return False
        now = time.perf_counter()
        if not self.archive_browser_first_visible_paint_done:
            return False
        return (now - float(self.archive_browser_first_visible_painted_at or now)) >= 0.45

    def _schedule_archive_browser_first_visible_paint_marker(self, delay_ms: int = 16) -> None:
        if self.shell._shutting_down or not self.isVisible() or not self.shell._is_tool_visible_or_current(self.shell.archive_browser_tab):
            return
        try:
            self.archive_tree.viewport().update()
        except Exception as exc:
            recorder = getattr(self.shell, "_record_runtime_event", None)
            if callable(recorder):
                recorder("archive_browser_viewport_update_failed", reason="worker_failed", error=str(exc))
        QTimer.singleShot(max(0, int(delay_ms)), self._handle_archive_browser_first_visible_paint)

    def _schedule_archive_post_ready_background_work(self, delay_ms: Optional[int] = None) -> None:
        if self.archive_deferred_background_start_pending or self.shell._shutting_down:
            return
        self.archive_deferred_background_start_pending = True
        if delay_ms is None:
            delay_ms = 550 if self.archive_browser_first_visible_paint_done else 2000
        QTimer.singleShot(max(0, int(delay_ms)), self._start_archive_deferred_background_work)


    def _try_apply_startup_saved_filters(self) -> None:
        # Saved filters are part of the immutable query captured before opening.
        self.archive_startup_saved_filter_apply_pending = False

    def _start_archive_deferred_background_work(self) -> None:
        self.archive_deferred_background_start_pending = False
        if self.shell._shutting_down:
            return
        if not self._archive_browser_background_work_allowed():
            return
        self._start_archive_preview_core_prewarm()

    def _handle_archive_browser_first_visible_paint(self) -> None:
        if self.shell._shutting_down or not self.isVisible() or not self.shell._is_tool_visible_or_current(self.shell.archive_browser_tab):
            return
        if not self.archive_browser_first_visible_paint_done:
            self.archive_browser_first_visible_paint_done = True
            self.archive_browser_first_visible_painted_at = time.perf_counter()
            elapsed_ms = max(
                0.0,
                (self.archive_browser_first_visible_painted_at - float(self.archive_browser_first_visible_started_at or self.archive_browser_first_visible_painted_at)) * 1000.0,
            )
            self.shell.append_archive_log(
                f"Archive Browser activation timing | cause=first_paint | elapsed={elapsed_ms:.0f}ms",
                verbose=True,
            )
            self.shell._record_runtime_event("first_paint", surface="archive_browser", elapsed_ms=elapsed_ms)
            if (
                getattr(self.shell, "_startup_splash_window", None) is not None
                and float(getattr(self.shell, "_startup_splash_finish_after_paint_deadline", 0.0) or 0.0) > 0.0
            ):
                self.shell._schedule_startup_splash_finish_after_main_window_paint(80)
        self._schedule_archive_post_ready_background_work(550)
        self._try_apply_startup_saved_filters()


__all__ = ["ArchiveRenderLifecycleMixin"]
