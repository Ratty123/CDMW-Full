from __future__ import annotations

import time
import weakref
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QMainWindow


CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS = 8.0


WORKER_TAB_NAMES = (
    "text_search_tab",
    "research_tab",
    "replace_assistant_tab",
    "mesh_editor_tab",
    "texture_editor_tab",
    "item_icons_tab",
    "model_library_tab",
    "recolor_variants_tab",
    "mod_package_retrofit_tab",
    "settings_tab",
)


def register_transient_worker_controller(owner: object, controller: object) -> None:
    """Make modeless-dialog workers visible to the shell close lifecycle."""
    references = list(getattr(owner, "_transient_worker_controller_refs", ()))
    references = [reference for reference in references if reference() is not None]
    references.append(weakref.ref(controller))
    setattr(owner, "_transient_worker_controller_refs", references)


def iter_transient_shutdown_workers(
    owner: object,
    *,
    on_error: Callable[[str, str], None] | None = None,
) -> Iterator[tuple[str, Any, Any]]:
    for reference in tuple(getattr(owner, "_transient_worker_controller_refs", ())):
        controller = reference()
        if controller is None:
            continue
        iterator = getattr(controller, "iter_shutdown_workers", None)
        if not callable(iterator):
            continue
        try:
            for worker_name, thread, worker in tuple(iterator()):
                yield f"transient.{worker_name}", thread, worker
        except RuntimeError:
            continue
        except Exception as exc:
            if on_error is not None:
                on_error(type(controller).__name__, str(exc))


def request_transient_shutdowns(
    owner: object,
    *,
    on_error: Callable[[str, str], None] | None = None,
) -> None:
    for reference in tuple(getattr(owner, "_transient_worker_controller_refs", ())):
        controller = reference()
        request_shutdown = getattr(controller, "request_shutdown", None)
        if not callable(request_shutdown):
            continue
        try:
            request_shutdown()
        except RuntimeError:
            continue
        except Exception as exc:
            if on_error is not None:
                on_error(type(controller).__name__, str(exc))


def iter_tab_shutdown_workers(
    owner: object,
    *,
    tab_names: Sequence[str] = WORKER_TAB_NAMES,
    on_error: Callable[[str, str], None] | None = None,
) -> Iterator[tuple[str, Any, Any]]:
    for tab_name in tab_names:
        tab = getattr(owner, tab_name, None)
        iterator = getattr(tab, "iter_shutdown_workers", None)
        if not callable(iterator):
            continue
        try:
            for worker_name, thread, worker in tuple(iterator()):
                yield f"{tab_name}.{worker_name}", thread, worker
        except RuntimeError:
            continue
        except Exception as exc:
            if on_error is not None:
                on_error(tab_name, str(exc))


def request_tab_shutdowns(
    owner: object,
    *,
    tab_names: Sequence[str] = WORKER_TAB_NAMES,
    on_error: Callable[[str, str], None] | None = None,
) -> None:
    for tab_name in tab_names:
        tab = getattr(owner, tab_name, None)
        request_shutdown = getattr(tab, "request_shutdown", None)
        if not callable(request_shutdown):
            continue
        try:
            request_shutdown()
        except RuntimeError:
            continue
        except Exception as exc:
            if on_error is not None:
                on_error(tab_name, str(exc))


class CloseControllerMixin:
    """Nonblocking close and worker shutdown behavior for the shell window."""

    def _record_close_event(self, event: str, **fields: object) -> None:
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(event, **fields)

    def _tracked_worker_threads(self) -> list[tuple[str, QThread | None, object | None]]:
        tracked: list[tuple[str, QThread | None, object | None]] = [
            ("worker_thread", self.worker_thread, self.scan_worker or self.archive_scan_worker or self.archive_filter_worker or self.build_worker or self.dds_to_png_worker or self.utility_worker),
            ("archive_sidecar_thread", self.archive_sidecar_thread, self.archive_sidecar_worker),
            ("archive_basic_index_thread", self.archive_basic_index_thread, self.archive_basic_index_worker),
            ("archive_derived_cache_thread", self.archive_derived_cache_thread, self.archive_derived_cache_worker),
            ("archive_enhanced_index_thread", self.archive_enhanced_index_thread, self.archive_enhanced_index_worker),
            ("archive_structure_filter_thread", self.archive_structure_filter_thread, self.archive_structure_filter_worker),
            ("archive_item_icon_warmup_thread", self.archive_item_icon_warmup_thread, self.archive_item_icon_warmup_worker),
            ("archive_item_icon_priority_thread", self.archive_item_icon_priority_thread, self.archive_item_icon_priority_worker),
            ("compare_preview_thread", self.compare_preview_thread, self.compare_preview_worker),
            ("archive_preview_thread", self.archive_preview_thread, self.archive_preview_worker),
            ("archive_isolated_package_thread", self.archive_isolated_package_thread, self.archive_isolated_package_worker),
            ("archive_native_prefetch_thread", self.archive_native_prefetch_thread, self.archive_native_prefetch_worker),
        ]

        def _record_tab_worker_error(tab_name: str, message: str) -> None:
            self._record_close_event(
                "close_tab_worker_discovery_failed",
                close_phase="discover_tab_workers",
                tab=tab_name,
                message=message,
            )

        tracked.extend(iter_tab_shutdown_workers(self, on_error=_record_tab_worker_error))
        tracked.extend(iter_transient_shutdown_workers(self, on_error=_record_tab_worker_error))
        return tracked

    def _running_worker_thread_entries(self) -> list[tuple[str, QThread]]:
        running: list[tuple[str, QThread]] = []
        for name, thread, _worker in self._tracked_worker_threads():
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    running.append((name, thread))
            except RuntimeError:
                continue
        return running

    def _running_worker_threads(self) -> list[QThread]:
        return [thread for _name, thread in self._running_worker_thread_entries()]

    def _request_tab_shutdowns(self) -> None:
        def _record_tab_shutdown_error(tab_name: str, message: str) -> None:
            self._record_close_event(
                "close_tab_shutdown_request_failed",
                close_phase="request_tab_shutdown",
                tab=tab_name,
                message=message,
            )

        request_tab_shutdowns(self, on_error=_record_tab_shutdown_error)
        request_transient_shutdowns(self, on_error=_record_tab_shutdown_error)

    def _request_tracked_workers_to_stop(self) -> None:
        self._request_tab_shutdowns()
        for _name, thread, worker in self._tracked_worker_threads():
            if worker is not None:
                stop = getattr(worker, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
            if thread is not None:
                try:
                    thread.requestInterruption()
                except Exception:
                    pass
                try:
                    thread.quit()
                except Exception:
                    pass

    def _force_stop_close_worker_threads(self, running_entries: Sequence[tuple[str, QThread]]) -> None:
        worker_names = [name for name, _thread in running_entries]
        self._record_close_event(
            "close_force_stop_workers",
            close_phase="force_stop",
            workers=tuple(worker_names),
            worker_count=len(worker_names),
        )
        for _name, thread in running_entries:
            try:
                thread.requestInterruption()
            except Exception:
                pass
            try:
                thread.quit()
            except Exception:
                pass

    def _finish_deferred_close_if_workers_stopped(self) -> None:
        if not self._close_after_workers_requested:
            return
        running_entries = self._running_worker_thread_entries()
        if running_entries:
            elapsed = (
                time.monotonic() - self._close_pending_started_at
                if self._close_pending_started_at > 0.0
                else 0.0
            )
            if elapsed >= CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS and not self._close_force_stop_requested:
                self._close_force_stop_requested = True
                self._force_stop_close_worker_threads(running_entries)
                self.set_status_message("Still waiting for background worker(s) to stop safely...")
                return
            running_names = ", ".join(name for name, _thread in running_entries[:3])
            if len(running_entries) > 3:
                running_names += ", ..."
            suffix = f" ({running_names})" if running_names else ""
            self.set_status_message(f"Closing after {len(running_entries):,} background worker(s) stop{suffix}...")
            self._record_close_event(
                "close_waiting_for_workers",
                close_phase="waiting",
                worker_count=len(running_entries),
                workers=tuple(name for name, _thread in running_entries[:8]),
                elapsed_seconds=round(elapsed, 3),
            )
            return
        self._close_worker_wait_timer.stop()
        self._close_after_workers_requested = False
        self._close_pending_started_at = 0.0
        self._close_force_stop_requested = False
        self._close_force_accept = True
        self._record_close_event("close_workers_stopped", close_phase="ready_to_accept")
        QTimer.singleShot(0, self.close)

    def _begin_deferred_close_for_workers(self, event) -> None:
        try:
            event.ignore()
        except Exception:
            pass
        if self._close_after_workers_requested:
            self._request_tracked_workers_to_stop()
            self._finish_deferred_close_if_workers_stopped()
            return
        self._close_after_workers_requested = True
        self._close_pending_started_at = time.monotonic()
        self._close_force_stop_requested = False
        self._shutting_down = True
        self._record_close_event(
            "close_begin_deferred",
            close_phase="begin_deferred",
            worker_count=len(self._running_worker_thread_entries()),
        )
        self._release_startup_splash()
        self._save_detached_tool_geometries()
        self._settings_save_timer.stop()
        self._external_activation_timer.stop()
        self._chainner_analysis_timer.stop()
        self._compare_preview_timer.stop()
        self.archive_preview_debounce_timer.stop()
        self.archive_native_prefetch_timer.stop()
        self.archive_preview_loading_timer.stop()
        self.archive_selection_state_timer.stop()
        self.archive_item_icon_preload_timer.stop()
        self.pending_compare_preview_selection = None
        self.pending_compare_preview_request = None
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.compare_preview_request_id += 1
        self.archive_preview_request_id += 1
        self.archive_item_icon_preload_queue.clear()
        self.archive_item_icon_priority_queue.clear()
        self.archive_item_icon_visible_warmup_remaining = 0
        self._request_tracked_workers_to_stop()
        self.set_status_message("Closing after active background workers stop...")
        self._close_worker_wait_timer.start()
        for thread in self._running_worker_threads():
            try:
                thread.finished.connect(self._finish_deferred_close_if_workers_stopped, Qt.UniqueConnection)
            except Exception:
                try:
                    thread.finished.connect(self._finish_deferred_close_if_workers_stopped)
                except Exception:
                    pass
        self._finish_deferred_close_if_workers_stopped()

    def _finalize_close(self) -> None:
        self._record_close_event("close_finalize", close_phase="finalize")
        self._request_tab_shutdowns()
        self._close_worker_wait_timer.stop()
        self._shutting_down = True
        self._release_startup_splash()
        self._save_detached_tool_geometries()
        self._attach_all_detached_tools(select_after=False)
        self._shutdown_archive_isolated_renderer_host()
        clear_active_main_window = getattr(self, "_clear_active_main_window", None)
        if callable(clear_active_main_window):
            clear_active_main_window(self)
        self._settings_save_timer.stop()
        self._chainner_analysis_timer.stop()
        self._compare_preview_timer.stop()
        self.archive_preview_debounce_timer.stop()
        self.archive_native_prefetch_timer.stop()
        self.archive_preview_loading_timer.stop()
        self.archive_selection_state_timer.stop()
        self.archive_item_icon_preload_timer.stop()
        self.archive_media_preview.shutdown()
        self.pending_compare_preview_selection = None
        self.pending_compare_preview_request = None
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.compare_preview_request_id += 1
        self.archive_preview_request_id += 1
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.flush_settings_save()
        self.settings_tab.flush_settings_save()
        self.replace_assistant_tab.flush_settings_save()
        self.texture_editor_tab.flush_settings_save()
        self.text_search_tab.shutdown()
        self.research_tab.shutdown()
        self.replace_assistant_tab.shutdown()
        self.texture_editor_tab.shutdown()
        self.item_icons_tab.shutdown()
        tray_icon = getattr(self, "app_tray_icon", None)
        if tray_icon is not None:
            try:
                tray_icon.hide()
            except Exception:
                pass
        write_heartbeat = getattr(self, "_write_heartbeat", None)
        if callable(write_heartbeat):
            write_heartbeat("closed", clean_shutdown=True)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self._close_force_accept and self._running_worker_threads():
            self._begin_deferred_close_for_workers(event)
            return
        self._finalize_close()
        QMainWindow.closeEvent(self, event)  # type: ignore[arg-type]


__all__ = [
    "CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS",
    "CloseControllerMixin",
    "iter_tab_shutdown_workers",
    "iter_transient_shutdown_workers",
    "register_transient_worker_controller",
    "request_tab_shutdowns",
    "request_transient_shutdowns",
]
