from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional

from cdmw.domain.mesh.validation import mesh_import_mode_availability
from cdmw.services.diagnostics_service import (
    RuntimeEventRecorder,
    add_persisted_crash_breadcrumbs as _add_persisted_crash_breadcrumbs_service,
    check_previous_unclean_exit as _check_previous_unclean_exit_service,
    cleanup_native_fault_log_on_exit as _cleanup_native_fault_log_file,
    enable_native_fault_log as _enable_native_fault_log_file,
    format_thread_dump as _format_thread_dump,
    process_is_alive as _process_is_alive,
    read_jsonl_tail as _read_jsonl_tail,
    should_write_crash_report as _should_write_crash_report,
    start_hang_watchdog as _start_hang_watchdog_service,
    thread_exception_report as _thread_exception_report,
    uncaught_exception_report as _uncaught_exception_report,
    unraisable_exception_report as _unraisable_exception_report,
    write_app_heartbeat as _write_app_heartbeat,
    write_crash_report as _write_crash_report_file,
    write_ui_breadcrumb as _write_ui_breadcrumb_file,
)
from cdmw.services.settings_service import create_settings, resolve_settings_file_path
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.shell.diagnostics_controller import (
    start_heartbeat_timer as _start_heartbeat_timer_controller,
    windows_process_memory_snapshot as _windows_process_memory_snapshot,
)
from cdmw.ui.shell.activation_controller import ActivationController
from cdmw.ui.shell.main_window_proxy import (
    MAIN_WINDOW_CLASS_ONLY_ENV,
    MainWindow,
    set_loaded_main_window_class,
)
from cdmw.ui.shell.theme_controller import ThemeChangeBusyOverlay
from cdmw.ui.shell.window_feature_controller import WindowFeatureController, install_window_feature_controller
from cdmw.ui.shell.window_feature_providers import (
    ARCHIVE_FEATURE_PROVIDERS,
    MESH_FEATURE_PROVIDERS,
    SHELL_FEATURE_PROVIDERS,
    TEXTURE_FEATURE_PROVIDERS,
)
from cdmw.ui.app_icon import load_app_icon


from cdmw.constants import APP_TITLE, APP_VERSION



def run_gui() -> int:
    try:
        from PySide6.QtCore import QThread, QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow
    except ImportError:
        print("PySide6 is required to run the GUI. Install it with: pip install PySide6", file=sys.stderr)
        return 1

    from cdmw.ui.shell.app_context import AppContext

    settings_file_path = resolve_settings_file_path()
    _workspace_paths = workspace_paths(settings_file_path.parent)
    crash_reports_dir = _workspace_paths["crash_reports_dir"]
    heartbeat_path = crash_reports_dir / "app_heartbeat.json"
    _default_sys_excepthook = sys.excepthook
    _default_threading_excepthook = getattr(threading, "excepthook", None)
    _default_unraisablehook = getattr(sys, "unraisablehook", None)
    _active_main_window: Optional["MainWindow"] = None
    _capture_crash_details_enabled = False
    _session_id = f"{os.getpid()}-{int(time.time() * 1000)}"
    _heartbeat_stop_event = threading.Event()
    _heartbeat_lock = threading.Lock()
    _last_heartbeat_written_at = time.time()
    _heartbeat_phase = "starting"
    _heartbeat_timer: Optional[QTimer] = None
    _fault_log_handle = None
    _cached_crash_context: Dict[str, object] = {}
    _previous_session_unclean = False
    _runtime_event_log_path = crash_reports_dir / "runtime_events_current.jsonl"
    _native_diagnostic_log_path = crash_reports_dir / "native_events_current.jsonl"
    _runtime_event_recorder = RuntimeEventRecorder(
        _runtime_event_log_path, session_id=_session_id, memory_snapshot=_windows_process_memory_snapshot
    )
    _last_active_operation: Dict[str, object] = {
        "operation": "startup", "timestamp": time.time(), "pid": os.getpid(), "session_id": _session_id,
    }
    os.environ.setdefault("CDMW_CRASH_DIR", str(crash_reports_dir))
    os.environ.setdefault("CDMW_NATIVE_DIAGNOSTIC_LOG", str(_native_diagnostic_log_path))
    os.environ.setdefault("CDMW_TEMP_CACHE_ROOT", str(_workspace_paths["archive_cache_root"]))

    def _set_crash_capture_enabled(enabled: bool) -> None:
        nonlocal _capture_crash_details_enabled
        _capture_crash_details_enabled = bool(enabled)

    def _record_runtime_event(event: str, **fields: object) -> Dict[str, object]:
        return _runtime_event_recorder.record(event, **fields)

    def _set_last_active_operation(operation: str, **fields: object) -> None:
        nonlocal _last_active_operation
        _last_active_operation = _record_runtime_event(
            "last_active_operation", operation=str(operation or "operation"), **fields
        )

    def _add_persisted_crash_breadcrumbs(context: Dict[str, object]) -> None:
        _add_persisted_crash_breadcrumbs_service(
            context,
            reports_dir=crash_reports_dir,
            runtime_event_log_path=_runtime_event_log_path,
            native_diagnostic_log_path=_native_diagnostic_log_path,
        )

    def _write_ui_breadcrumb(payload: Mapping[str, object]) -> None:
        _write_ui_breadcrumb_file(crash_reports_dir, payload, session_id=_session_id, pid=os.getpid())

    def _collect_crash_context() -> Dict[str, object]:
        nonlocal _cached_crash_context
        window = _active_main_window
        context: Dict[str, object] = {}
        app = QApplication.instance()
        if app is not None and app.thread() != QThread.currentThread():
            context.update(_cached_crash_context)
            _add_persisted_crash_breadcrumbs(context)
            return context
        if window is None:
            return context
        process_memory = _windows_process_memory_snapshot(os.getpid())
        if process_memory:
            context["process_memory"] = process_memory
        try:
            current_tab_index = window.main_tabs.currentIndex()
            if current_tab_index >= 0:
                context["current_tab"] = window.main_tabs.tabText(current_tab_index)
        except Exception:
            pass
        try:
            entry = window._current_archive_entry()
            if entry is not None:
                context["selected_archive_path"] = entry.path
                context["selected_archive_package"] = str(entry.pamt_path)
        except Exception:
            pass
        try:
            context["texconv_path"] = window.texconv_path_edit.text().strip()
        except Exception:
            pass
        try:
            context["archive_package_root"] = window.archive_package_root_edit.text().strip()
        except Exception:
            pass
        try:
            context["last_active_operation"] = dict(_last_active_operation)
        except Exception:
            pass
        try:
            context["runtime_event_tail"] = _runtime_event_recorder.tail(limit=120)
        except Exception:
            pass
        try:
            context["native_diagnostic_log_path"] = str(_native_diagnostic_log_path)
            context["native_diagnostic_event_tail"] = _read_jsonl_tail(_native_diagnostic_log_path, limit=120)
        except Exception:
            pass
        try:
            context["archive_renderer_backend"] = window._archive_model_renderer_backend()
            context["archive_preview_request_id"] = int(getattr(window, "archive_preview_request_id", 0) or 0)
            context["archive_isolated_package_request_id"] = int(
                getattr(window, "archive_isolated_package_request_id", 0) or 0
            )
            context["pending_archive_preview_request"] = str(getattr(window, "pending_archive_preview_request", None))
            context["scheduled_archive_preview_request"] = str(getattr(window, "scheduled_archive_preview_request", None))
            context["active_d3d11_package"] = str(getattr(window, "archive_isolated_renderer_active_package", "") or "")
            status_file = getattr(window, "archive_isolated_renderer_status_file", None)
            context["d3d11_status_file"] = str(status_file or "")
            if status_file is not None and Path(status_file).is_file():
                try:
                    status_payload = json.loads(Path(status_file).read_text(encoding="utf-8"))
                except Exception as exc:
                    status_payload = {"read_error": str(exc)}
                context["d3d11_status_payload"] = status_payload
            process = getattr(window, "archive_isolated_renderer_process", None)
            if process is not None:
                try:
                    context["d3d11_process_pid"] = int(process.processId())
                except RuntimeError:
                    context["d3d11_process_pid"] = "deleted"
                d3d11_process_memory = _windows_process_memory_snapshot(context.get("d3d11_process_pid", 0))
                if d3d11_process_memory:
                    context["d3d11_process_memory"] = d3d11_process_memory
                try:
                    context["d3d11_process_state"] = str(process.state())
                except RuntimeError:
                    context["d3d11_process_state"] = "deleted"
            package_worker = getattr(window, "archive_isolated_package_worker", None)
            package_thread = getattr(window, "archive_isolated_package_thread", None)
            context["archive_isolated_package_worker_active"] = package_worker is not None
            if package_thread is not None:
                try:
                    context["archive_isolated_package_thread_running"] = bool(package_thread.isRunning())
                except RuntimeError:
                    context["archive_isolated_package_thread_running"] = "deleted"
            preview_worker = getattr(window, "archive_preview_worker", None)
            preview_thread = getattr(window, "archive_preview_thread", None)
            context["archive_preview_worker_active"] = preview_worker is not None
            if preview_thread is not None:
                try:
                    context["archive_preview_thread_running"] = bool(preview_thread.isRunning())
                except RuntimeError:
                    context["archive_preview_thread_running"] = "deleted"
        except Exception:
            pass
        _add_persisted_crash_breadcrumbs(context)
        try:
            log_lines = window.log_view.toPlainText().splitlines()
            context["recent_log_tail"] = log_lines[-80:]
        except Exception:
            pass
        try:
            archive_log_lines = window.archive_log_view.toPlainText().splitlines()
            context["recent_archive_log_tail"] = archive_log_lines[-80:]
        except Exception:
            pass
        _cached_crash_context = dict(context)
        return context

    def _clear_active_main_window(window: object) -> None:
        nonlocal _active_main_window
        if _active_main_window is window:
            _active_main_window = None

    def _write_crash_report(
        kind: str,
        title: str,
        body: str,
        *,
        context: Optional[Dict[str, object]] = None,
        force: bool = False,
    ) -> None:
        if not _should_write_crash_report(
            kind,
            capture_enabled=_capture_crash_details_enabled,
            force=force,
        ):
            return
        report_context = context if context is not None else _collect_crash_context()
        _write_crash_report_file(
            crash_reports_dir,
            kind,
            title,
            body,
            app_title=APP_TITLE,
            app_version=APP_VERSION,
            session_id=_session_id,
            context=report_context,
            pid=os.getpid(),
            python_version=sys.version,
            platform_label=platform.platform(),
        )

    def _write_heartbeat(phase: str = "", *, clean_shutdown: bool = False) -> None:
        nonlocal _heartbeat_phase, _last_heartbeat_written_at
        try:
            if phase:
                _heartbeat_phase = str(phase)
            payload = _write_app_heartbeat(
                heartbeat_path,
                app_title=APP_TITLE,
                app_version=APP_VERSION,
                session_id=_session_id,
                phase=_heartbeat_phase,
                clean_shutdown=clean_shutdown,
                platform_label=sys.platform,
            )
            with _heartbeat_lock:
                _last_heartbeat_written_at = float(payload["last_beat_epoch"])
        except Exception:
            pass

    def _check_previous_unclean_exit() -> bool:
        return _check_previous_unclean_exit_service(
            heartbeat_path,
            session_id=_session_id,
            reports_dir=crash_reports_dir,
            process_is_alive_fn=_process_is_alive,
            add_breadcrumbs_fn=_add_persisted_crash_breadcrumbs,
            write_crash_report_fn=_write_crash_report,
            record_runtime_event_fn=_record_runtime_event,
        )

    def _start_heartbeat_timer(app: QApplication) -> QTimer:
        return _start_heartbeat_timer_controller(app, _write_heartbeat)  # type: ignore[return-value]

    def _start_hang_watchdog() -> threading.Thread:
        def _last_heartbeat_written_epoch() -> float:
            with _heartbeat_lock:
                return _last_heartbeat_written_at

        return _start_hang_watchdog_service(
            _heartbeat_stop_event,
            _last_heartbeat_written_epoch,
            _write_crash_report,
            format_thread_dump_fn=_format_thread_dump,
        )

    def _enable_native_fault_log() -> None:
        nonlocal _fault_log_handle
        _fault_log_handle = _enable_native_fault_log_file(crash_reports_dir)

    def _cleanup_native_fault_log_on_exit(*, clean_exit: bool) -> None:
        nonlocal _fault_log_handle
        if _fault_log_handle is not None:
            _cleanup_native_fault_log_file(
                _fault_log_handle,
                crash_reports_dir,
                clean_exit=clean_exit,
            )
            _fault_log_handle = None

    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        kind, title, formatted = _uncaught_exception_report(exc_type, exc_value, exc_traceback)
        _write_crash_report(kind, title, formatted, force=True)
        _default_sys_excepthook(exc_type, exc_value, exc_traceback)

    def _handle_thread_exception(args) -> None:
        kind, title, formatted = _thread_exception_report(args)
        _write_crash_report(kind, title, formatted, force=True)
        if _default_threading_excepthook is not None:
            _default_threading_excepthook(args)

    def _handle_unraisable_exception(args) -> None:
        kind, title, formatted = _unraisable_exception_report(args)
        _write_crash_report(kind, title, formatted, force=True)
        if _default_unraisablehook is not None:
            _default_unraisablehook(args)

    sys.excepthook = _handle_uncaught_exception
    if _default_threading_excepthook is not None:
        threading.excepthook = _handle_thread_exception
    if _default_unraisablehook is not None:
        sys.unraisablehook = _handle_unraisable_exception
    _enable_native_fault_log()
    _previous_session_unclean = _check_previous_unclean_exit()
    _record_runtime_event(
        "session_start",
        crash_reports_dir=str(crash_reports_dir),
        previous_session_unclean=bool(_previous_session_unclean),
    )
    _write_heartbeat("starting")
    _start_hang_watchdog()

    class MainWindow(QMainWindow):
        def __init__(self, startup_splash: Optional[object] = None, app_context: Optional[AppContext] = None) -> None:
            from cdmw.ui.shell.startup_splash import make_startup_splash_pump

            super().__init__()
            self._shell_feature_controller = WindowFeatureController(self, SHELL_FEATURE_PROVIDERS)
            self._archive_feature_controller = WindowFeatureController(self, ARCHIVE_FEATURE_PROVIDERS)
            self._texture_feature_controller = WindowFeatureController(self, TEXTURE_FEATURE_PROVIDERS)
            self._mesh_feature_controller = WindowFeatureController(self, MESH_FEATURE_PROVIDERS)
            self._activation_controller = ActivationController(self)

            pump_startup_splash = make_startup_splash_pump(startup_splash)
            pump_startup_splash("Preparing application...")
            nonlocal _active_main_window
            _active_main_window = self
            self._initialize_window_bootstrap_state(
                app_context=app_context,
                settings_file_path=settings_file_path,
                crash_reports_dir=crash_reports_dir,
                session_id=_session_id,
                previous_session_unclean=bool(_previous_session_unclean),
                set_crash_capture_enabled=_set_crash_capture_enabled,
                record_runtime_event=_record_runtime_event,
                set_last_active_operation=_set_last_active_operation,
                collect_crash_context=_collect_crash_context,
                clear_active_main_window=_clear_active_main_window,
                write_crash_report=_write_crash_report,
                write_heartbeat=_write_heartbeat,
            )
            self._initialize_window_runtime_state()
            self._initialize_archive_runtime_state()
            pump_startup_splash("Preparing workspace...")

            app_icon, _icon_path = load_app_icon(self.current_theme_key)
            if not app_icon.isNull():
                self.setWindowIcon(app_icon)
            self._configure_system_tray_icon(app_icon)

            self._build_shell_menus()
            central = self._build_shell_root_tabs()

            self._build_texture_workflow_shell_tab(pump_startup_splash)
            self._build_archive_browser_shell_tab(pump_startup_splash)
            self._build_shell_tool_tabs(pump_startup_splash)
            self._register_shell_tool_tabs()
            self.setCentralWidget(central)
            self.theme_change_overlay = ThemeChangeBusyOverlay(central)
            self.theme_change_overlay.setGeometry(central.rect())
            self._restore_shell_startup_state(
                pump_startup_splash,
                previous_session_unclean=bool(_previous_session_unclean),
            )

        def _initialize_existing_instance_activation_polling(self) -> None:
            self._activation_controller.initialize_polling()

        def _configure_system_tray_icon(self, app_icon: object) -> None:
            self._activation_controller.configure_system_tray_icon(app_icon)

        def _handle_system_tray_activated(self, reason: object) -> None:
            self._activation_controller.handle_system_tray_activated(reason)

        def _present_main_window(self, reason: str = "") -> None:
            self._activation_controller.present_main_window(reason)

        def _poll_existing_instance_activation_request(self) -> None:
            self._activation_controller.poll_existing_instance_activation_request()

    install_window_feature_controller(
        MainWindow,
        controller_attribute="_shell_feature_controller",
        providers=SHELL_FEATURE_PROVIDERS,
    )
    install_window_feature_controller(
        MainWindow,
        controller_attribute="_archive_feature_controller",
        providers=ARCHIVE_FEATURE_PROVIDERS,
    )
    install_window_feature_controller(
        MainWindow,
        controller_attribute="_texture_feature_controller",
        providers=TEXTURE_FEATURE_PROVIDERS,
    )
    install_window_feature_controller(
        MainWindow,
        controller_attribute="_mesh_feature_controller",
        providers=MESH_FEATURE_PROVIDERS,
    )

    set_loaded_main_window_class(MainWindow)
    globals()["MainWindow"] = MainWindow
    if os.environ.get(MAIN_WINDOW_CLASS_ONLY_ENV) == "1":
        return MainWindow  # type: ignore[return-value]

    app: Optional[QApplication] = None
    normal_exit = False
    exit_code = 1
    try:
        from cdmw.ui.shell.app_startup import (
            finish_gui_startup_smoke_if_requested,
            prepare_shell_application,
            prepare_shell_main_window,
            run_shell_event_loop,
        )
        from cdmw.ui.shell.icon_controller import apply_windows_app_user_model_id
        from cdmw.ui.shell.startup_controller import queue_startup_archive_autoload
        from cdmw.ui.shell.startup_splash import create_startup_splash

        apply_windows_app_user_model_id()
        app = QApplication(sys.argv)
        nonlocal_heartbeat_timer = _start_heartbeat_timer(app)
        globals()["_cdmw_heartbeat_timer_ref"] = nonlocal_heartbeat_timer
        _write_heartbeat("settings")
        application_startup = prepare_shell_application(app, settings_file_path=settings_file_path)
        startup_theme = application_startup.theme_key
        globals()["_cdmw_app_window_icon_filter_ref"] = application_startup.app_window_icon_filter
        globals()["_cdmw_tree_column_width_filter_ref"] = application_startup.tree_column_width_filter

        _write_heartbeat("startup_splash")
        startup_splash = create_startup_splash(app, startup_theme)

        _write_heartbeat("main_window")
        window = MainWindow(
            startup_splash=startup_splash,
            app_context=AppContext.from_settings(application_startup.settings),
        )
        prepare_shell_main_window(
            window,
            app,
            startup_splash,
            application_startup.app_window_icon_filter,
            _record_runtime_event,
        )
        if finish_gui_startup_smoke_if_requested(window, app):
            normal_exit = True
            exit_code = 0
            return 0
        queue_startup_archive_autoload(window, startup_splash, _write_heartbeat)
        exit_code = run_shell_event_loop(app, _write_crash_report)
        normal_exit = True
        return exit_code
    except Exception:
        formatted = traceback.format_exc()
        _write_crash_report(
            "startup_failure" if app is None else "gui_runtime_failure",
            "GUI failed before clean shutdown",
            formatted,
            force=True,
        )
        raise
    finally:
        _heartbeat_stop_event.set()
        if normal_exit:
            _write_heartbeat("closed", clean_shutdown=True)
        _cleanup_native_fault_log_on_exit(clean_exit=bool(normal_exit))

__all__ = ["MainWindow", "mesh_import_mode_availability", "run_gui"]
