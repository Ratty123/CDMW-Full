from __future__ import annotations

import time
import weakref
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from PySide6.QtCore import QProcess, Qt, QThread, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from cdmw.services.process_control_service import force_stop_windows_process_tree


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
        candidates = [
            (name, thread)
            for name, thread, _worker in self._tracked_worker_threads()
            if thread is not None
        ]
        find_children = getattr(self, "findChildren", None)
        if callable(find_children):
            for thread in find_children(QThread):
                name = str(thread.objectName() or "owned_qthread")
                candidates.append((name, thread))
        candidates.extend(getattr(self, "_close_pending_worker_threads", ()))
        seen: set[int] = set()
        for name, thread in candidates:
            identity = id(thread)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                if not thread.wait(0):
                    running.append((name, thread))
            except RuntimeError:
                continue
        if self._close_after_workers_requested:
            self._close_pending_worker_threads = list(running)
        return running

    def _running_worker_threads(self) -> list[QThread]:
        return [thread for _name, thread in self._running_worker_thread_entries()]

    def _running_owned_process_entries(self) -> list[tuple[str, QProcess]]:
        candidates: list[tuple[str, QProcess]] = list(
            getattr(self, "_close_pending_processes", ())
        )
        find_children = getattr(self, "findChildren", None)
        if callable(find_children):
            try:
                for process in find_children(QProcess):
                    candidates.append((str(process.objectName() or "owned_qprocess"), process))
            except RuntimeError:
                pass
        backend_process = getattr(getattr(self, "archive_backend_client", None), "_process", None)
        if isinstance(backend_process, QProcess):
            candidates.append(("archive_backend", backend_process))

        running: list[tuple[str, QProcess]] = []
        seen: set[int] = set()
        for name, process in candidates:
            identity = id(process)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                if process.state() != QProcess.NotRunning:
                    running.append((name, process))
            except RuntimeError:
                continue
        if bool(getattr(self, "_close_after_workers_requested", False)):
            self._close_pending_processes = list(running)
        return running

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
        catalogue = getattr(self, "archive_catalogue_service", None)
        request_catalogue_shutdown = getattr(catalogue, "request_shutdown", None)
        if callable(request_catalogue_shutdown):
            try:
                request_catalogue_shutdown()
            except (AttributeError, RuntimeError):
                pass
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

    def _close_modeless_alignment_builders(self) -> None:
        dialogs = list(getattr(self, "_modeless_alignment_dialogs", {}).items())
        self._close_pending_builder_dialogs = [dialog for _key, dialog in dialogs if dialog is not None]
        for key, dialog in dialogs:
            if dialog is None:
                getattr(self, "_modeless_alignment_dialogs", {}).pop(str(key or ""), None)
                continue
            try:
                dialog.reject()
            except RuntimeError:
                getattr(self, "_modeless_alignment_dialogs", {}).pop(str(key or ""), None)
            except Exception as exc:
                self._record_close_event(
                    "close_builder_reject_failed",
                    close_phase="close_builders",
                    builder=str(key or ""),
                    message=str(exc),
                )
                try:
                    dialog.close()
                except RuntimeError:
                    getattr(self, "_modeless_alignment_dialogs", {}).pop(str(key or ""), None)
            if getattr(self, "_modeless_alignment_dialogs", {}).get(str(key or "")) is dialog:
                disposer = getattr(self, "_dispose_partial_alignment_builder", None)
                if callable(disposer):
                    disposer(
                        str(key or ""),
                        dialog,
                        context=getattr(dialog, "_cdmw_builder_construction_context", None),
                    )
                else:
                    getattr(self, "_modeless_alignment_dialogs", {}).pop(str(key or ""), None)

        for widget in QApplication.topLevelWidgets():
            try:
                if widget.objectName() != "MeshAlignmentAdvancedTextureTuningSection":
                    continue
                widget.hide()
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                pass

    def _force_stop_owned_external_processes(
        self,
        running_entries: Sequence[tuple[str, QProcess]],
    ) -> None:
        process_names = [name for name, _process in running_entries]
        self._record_close_event(
            "close_force_stop_processes",
            close_phase="force_stop_processes",
            processes=tuple(process_names),
            process_count=len(process_names),
        )
        for _name, process in running_entries:
            try:
                process_id = int(process.processId())
            except (RuntimeError, TypeError, ValueError):
                process_id = 0
            if process_id > 0:
                force_stop_windows_process_tree(process_id, include_root=False)
            try:
                process.kill()
            except RuntimeError:
                pass

    def _archive_backend_shutdown_complete(self) -> bool:
        backend = getattr(self, "archive_backend_client", None)
        state = str(getattr(getattr(backend, "state", None), "value", "stopped"))
        return state in {"stopped", "failed"}

    def _finish_deferred_close_if_workers_stopped(self) -> None:
        if not self._close_after_workers_requested:
            return
        running_entries = self._running_worker_thread_entries()
        running_processes = self._running_owned_process_entries()
        backend_ready = self._archive_backend_shutdown_complete()
        registered_builders = len(getattr(self, "_modeless_alignment_dialogs", {}))
        if running_entries or running_processes or not backend_ready or registered_builders:
            elapsed = (
                time.monotonic() - self._close_pending_started_at
                if self._close_pending_started_at > 0.0
                else 0.0
            )
            if elapsed >= CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS and not self._close_force_stop_requested:
                self._close_force_stop_requested = True
                self._force_stop_owned_external_processes(running_processes)
                self._request_tracked_workers_to_stop()
                self.set_status_message("Still waiting for owned background work to stop safely...")
                return
            running_names = [name for name, _thread in running_entries]
            running_names.extend(name for name, _process in running_processes)
            if not backend_ready and "archive_backend" not in running_names:
                running_names.append("archive_backend")
            display_names = ", ".join(running_names[:3])
            if len(running_names) > 3:
                display_names += ", ..."
            suffix = f" ({display_names})" if display_names else ""
            remaining_count = (
                len(running_entries)
                + len(running_processes)
                + registered_builders
                + (0 if backend_ready else 1)
            )
            self.set_status_message(f"Closing after {remaining_count:,} owned task(s) stop{suffix}...")
            self._record_close_event(
                "close_waiting_for_workers",
                close_phase="waiting",
                worker_count=len(running_entries),
                process_count=len(running_processes),
                builder_count=registered_builders,
                backend_ready=backend_ready,
                workers=tuple(name for name, _thread in running_entries[:8]),
                processes=tuple(name for name, _process in running_processes[:8]),
                elapsed_seconds=round(elapsed, 3),
            )
            return
        self._close_worker_wait_timer.stop()
        self._close_pending_worker_threads.clear()
        self._close_pending_processes.clear()
        self._close_pending_builder_dialogs.clear()
        self._close_pending_started_at = 0.0
        self._close_force_stop_requested = False
        self._close_force_accept = True
        self._record_close_event("close_workers_stopped", close_phase="ready_to_accept")
        QTimer.singleShot(0, self.close)

    def _begin_deferred_close_for_workers(
        self,
        event,
        initial_entries: Sequence[tuple[str, QThread]] = (),
    ) -> None:
        try:
            event.ignore()
        except Exception:
            pass
        if self._close_after_workers_requested:
            self._request_tracked_workers_to_stop()
            self._finish_deferred_close_if_workers_stopped()
            return
        self._close_after_workers_requested = True
        self._close_pending_worker_threads = list(initial_entries)
        self._close_pending_processes = self._running_owned_process_entries()
        self._close_pending_started_at = time.monotonic()
        self._close_force_stop_requested = False
        self._shutting_down = True
        self._record_close_event(
            "close_begin_deferred",
            close_phase="begin_deferred",
            worker_count=len(initial_entries),
        )
        self.hide()
        tray_icon = getattr(self, "app_tray_icon", None)
        if tray_icon is not None:
            try:
                tray_icon.hide()
            except RuntimeError:
                pass
        self._release_startup_splash()
        self._save_detached_tool_geometries()
        self._close_modeless_alignment_builders()
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
        self._shutdown_archive_isolated_renderer_host()
        self._request_tracked_workers_to_stop()
        archive_backend = getattr(self, "archive_backend_client", None)
        shutdown_backend = getattr(archive_backend, "shutdown", None)
        if callable(shutdown_backend):
            try:
                shutdown_backend()
            except (AttributeError, RuntimeError):
                pass
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
        if bool(getattr(self, "_close_finalized", False)):
            return
        self._close_finalized = True
        self._record_close_event("close_finalize", close_phase="finalize")
        self._request_tab_shutdowns()
        catalogue = getattr(self, "archive_catalogue_service", None)
        request_catalogue_shutdown = getattr(catalogue, "request_shutdown", None)
        if callable(request_catalogue_shutdown):
            try:
                request_catalogue_shutdown()
            except (AttributeError, RuntimeError):
                pass
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
        if bool(getattr(self, "_close_force_accept", False)):
            self._finalize_close()
            QMainWindow.closeEvent(self, event)  # type: ignore[arg-type]
            application = QApplication.instance()
            if application is not None:
                application.quit()
            return
        if bool(getattr(self, "_close_after_workers_requested", False)):
            try:
                event.ignore()
            except Exception:
                pass
            self._finish_deferred_close_if_workers_stopped()
            return
        self._begin_deferred_close_for_workers(event, self._running_worker_thread_entries())


__all__ = [
    "CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS",
    "CloseControllerMixin",
    "iter_tab_shutdown_workers",
    "iter_transient_shutdown_workers",
    "register_transient_worker_controller",
    "request_tab_shutdowns",
    "request_transient_shutdowns",
]
