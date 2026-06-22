from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "cdmw_app.py"
APP_BOOTSTRAP = ROOT / "cdmw" / "app" / "bootstrap.py"
APP_GUI = ROOT / "cdmw" / "app" / "gui.py"
APP_BOOTSTRAP_REPORTS = ROOT / "cdmw" / "app" / "bootstrap_reports.py"
APP_ACTIVATION = ROOT / "cdmw" / "app" / "activation.py"
APP_SINGLE_INSTANCE = ROOT / "cdmw" / "app" / "single_instance.py"
APP_STARTUP_MAINTENANCE = ROOT / "cdmw" / "app" / "startup_maintenance.py"
APP_STARTUP_SPLASH = ROOT / "cdmw" / "app" / "startup_splash.py"
MAIN_WINDOW = ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
ARCHIVE_STATIC_REPLACEMENT_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog.py"
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_shell.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_OPEN = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_open.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_STATE_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_state_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_TRANSFORM = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_transform.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_BASE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_base.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_A = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_a.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_B = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_b.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_CALLBACK_FACTORIES = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_callback_factories.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_REMAINING_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_EDIT_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_edit_callbacks.py"
)
SHELL_WINDOW_RUNTIME_STATE = ROOT / "cdmw" / "ui" / "shell" / "window_runtime_state.py"
SIGNAL_WIRING = ROOT / "cdmw" / "ui" / "shell" / "signal_wiring.py"
ABOUT_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "about_controller.py"
PROFILE_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "profile_controller.py"
SETTINGS_PERSISTENCE = ROOT / "cdmw" / "ui" / "shell" / "settings_persistence.py"
NAVIGATION_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "navigation_controller.py"
SHELL_MENUS = ROOT / "cdmw" / "ui" / "shell" / "menus.py"
SHELL_TOOL_TABS = ROOT / "cdmw" / "ui" / "shell" / "tool_tabs.py"
SHELL_APP_STARTUP = ROOT / "cdmw" / "ui" / "shell" / "app_startup.py"
SHELL_WORKSPACE_LAYOUT = ROOT / "cdmw" / "ui" / "shell" / "workspace_layout.py"
STARTUP_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "startup_controller.py"
SHELL_STARTUP_SPLASH = ROOT / "cdmw" / "ui" / "shell" / "startup_splash.py"
PATH_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "path_controller.py"
UTILITY_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "utility_controller.py"
THEME_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "theme_controller.py"
ACTIVATION_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "activation_controller.py"
DIAGNOSTICS_SERVICE = ROOT / "cdmw" / "services" / "diagnostics_service.py"
CLOSE_CONTROLLER = ROOT / "cdmw" / "ui" / "shell" / "close_controller.py"
STARTUP_DIALOGS = ROOT / "cdmw" / "ui" / "shell" / "startup_dialogs.py"
ARCHIVE_WORKERS = ROOT / "cdmw" / "workers" / "archive_workers.py"
ARCHIVE_CONTROLS_PANEL = ROOT / "cdmw" / "ui" / "archive_browser" / "controls_panel.py"
ARCHIVE_PROGRESS = ROOT / "cdmw" / "ui" / "archive_browser" / "progress.py"
ARCHIVE_FILTERS = ROOT / "cdmw" / "ui" / "archive_browser" / "filters.py"
ARCHIVE_FILTER_CONTROLS = ROOT / "cdmw" / "ui" / "archive_browser" / "filter_controls.py"
ARCHIVE_SCAN_LIFECYCLE = ROOT / "cdmw" / "ui" / "archive_browser" / "scan_lifecycle.py"
ARCHIVE_INDEX_WORKERS_UI = ROOT / "cdmw" / "ui" / "archive_browser" / "index_workers.py"
ARCHIVE_RENDER_LIFECYCLE = ROOT / "cdmw" / "ui" / "archive_browser" / "render_lifecycle.py"
ARCHIVE_ASSET_CATALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog.py"
ARCHIVE_ASSET_CATALOG_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog_dialog.py"
ARCHIVE_ASSET_CATALOG_SCOPE = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog_scope.py"
ARCHIVE_ASSET_FAMILY_LAYOUT = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_layout.py"
ARCHIVE_ASSET_FAMILY_PANEL = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_panel.py"
ARCHIVE_ASSET_FAMILY_REFERENCES = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_references.py"
ARCHIVE_ICON_PIPELINE = ROOT / "cdmw" / "ui" / "archive_browser" / "icon_pipeline.py"
ARCHIVE_MATERIAL_FINDER = ROOT / "cdmw" / "ui" / "archive_browser" / "material_finder.py"
ARCHIVE_PREVIEW_RESULT = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_result.py"
ARCHIVE_PREVIEW_LAYOUT = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_layout.py"
ARCHIVE_UI_FORMATTING = ROOT / "cdmw" / "ui" / "archive_browser" / "ui_formatting.py"
ARCHIVE_PREVIEW_SETTINGS = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_settings.py"
TEXTURE_WORKERS = ROOT / "cdmw" / "workers" / "texture_workers.py"
WORKER_PROTOCOL = ROOT / "cdmw" / "workers" / "worker_protocol.py"
STARTUP_SPLASH_HOST = ROOT / "cdmw" / "ui" / "startup_splash_host.py"
APP_ICON = ROOT / "cdmw" / "ui" / "app_icon.py"
ARCHIVE = ROOT / "cdmw" / "core" / "archive.py"
ARCHIVE_FORMAT = ROOT / "cdmw" / "core" / "archive_format.py"
CONSTANTS = ROOT / "cdmw" / "constants.py"
THEMES = ROOT / "cdmw" / "ui" / "themes.py"
WIDGETS = ROOT / "cdmw" / "ui" / "widgets.py"
RESEARCH_TAB = ROOT / "cdmw" / "ui" / "research" / "tab.py"
RESEARCH_LAYOUT = ROOT / "cdmw" / "ui" / "research" / "layout_state.py"
RESEARCH_TREE_HELPERS = ROOT / "cdmw" / "ui" / "research" / "tree_helpers.py"
TEXT_SEARCH_TAB = ROOT / "cdmw" / "ui" / "text_search" / "tab.py"
TEXT_SEARCH_CONTROLLER = ROOT / "cdmw" / "ui" / "text_search" / "controller.py"
REPLACE_ASSISTANT_TAB = ROOT / "cdmw" / "ui" / "replace_assistant_tab.py"
TEXTURE_EDITOR_TAB = ROOT / "cdmw" / "ui" / "texture_editor_tab.py"
TEXTURE_EDITOR_WORKER_LIFECYCLE = ROOT / "cdmw" / "ui" / "texture_workflow" / "editor_worker_lifecycle.py"
ITEM_ICONS_TAB = ROOT / "cdmw" / "ui" / "item_icons" / "tab.py"


def _legacy_nested_source(path: Path) -> str:
    return "\n".join(f"    {line}" if line else line for line in path.read_text(encoding="utf-8").splitlines())


def _main_window_source() -> str:
    return (
        MAIN_WINDOW.read_text(encoding="utf-8")
        + "\n"
        + SHELL_STARTUP_SPLASH.read_text(encoding="utf-8")
        + "\n"
        + SHELL_WORKSPACE_LAYOUT.read_text(encoding="utf-8")
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_OPEN)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_STATE_CALLBACKS)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_TRANSFORM)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_BASE)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_A)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_B)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_CALLBACKS)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_CALLBACK_FACTORIES)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_REMAINING_CALLBACKS)
        + "\n"
        + _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_EDIT_CALLBACKS)
    )


class CrashReportingGuardTests(unittest.TestCase):
    def test_qt_event_filters_ignore_deleted_wrappers(self) -> None:
        main_source = _main_window_source()
        diagnostics_source = (ROOT / "cdmw" / "ui" / "shell" / "diagnostics_controller.py").read_text(encoding="utf-8")
        responsiveness_source = (ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8")
        widgets_source = WIDGETS.read_text(encoding="utf-8")

        self.assertIn("def qt_wrapper_is_valid(obj: object) -> bool:", diagnostics_source)
        self.assertIn("shiboken6.isValid(obj)", diagnostics_source)
        self.assertIn("not qt_wrapper_is_valid(tree) or not isinstance(tree, QTreeWidget)", responsiveness_source)
        self.assertIn("and qt_wrapper_is_valid(watched)", responsiveness_source)
        self.assertIn("self._viewport = tree.viewport()", main_source)
        self.assertIn("watched is not self._viewport or not _qt_object_is_valid(self._tree)", main_source)
        self.assertIn("selected_items = tuple(source_tree.selectedItems())", main_source)
        self.assertIn("except RuntimeError:", main_source)
        self.assertIn("selected_items = ()", main_source)
        self.assertIn("import shiboken6", widgets_source)
        self.assertIn("def _watched_is_valid(watched: object) -> bool:", widgets_source)
        self.assertIn("shiboken6.isValid(watched)", widgets_source)
        self.assertIn("if event_type != QEvent.Type.Wheel:", widgets_source)

    def test_morph_slider_topology_crash_uses_existing_refresh_helper(self) -> None:
        source = _main_window_source()

        self.assertNotIn("_refresh_morph_slider_controls", source)
        self.assertIn("def _morph_slider_refresh_controls() -> None:", source)
        self.assertIn("_morph_slider_refresh_controls()", source)

    def test_bootstrap_import_failures_are_reported(self) -> None:
        source = APP_BOOTSTRAP.read_text(encoding="utf-8")
        report_source = APP_BOOTSTRAP_REPORTS.read_text(encoding="utf-8")
        gui_source = APP_GUI.read_text(encoding="utf-8")
        single_instance_source = APP_SINGLE_INSTANCE.read_text(encoding="utf-8")
        maintenance_source = APP_STARTUP_MAINTENANCE.read_text(encoding="utf-8")
        splash_source = APP_STARTUP_SPLASH.read_text(encoding="utf-8")
        activation_source = APP_ACTIVATION.read_text(encoding="utf-8")
        self.assertIn("def write_bootstrap_report", report_source)
        self.assertIn("crash_report_details", report_source)
        self.assertIn("crash_timestamp", report_source)
        self.assertIn("Report ID:", report_source)
        self.assertIn("Likely Location:", report_source)
        self.assertIn("Exception:", report_source)
        self.assertIn("Fingerprint:", report_source)
        self.assertIn('"bootstrap_failure"', source)
        self.assertIn("from cdmw.ui.main_window import run_gui", gui_source)
        self.assertIn("def acquire_single_instance_guard", single_instance_source)
        self.assertIn("_single_instance_lock_handle", single_instance_source)
        self.assertIn("single_instance.lock", single_instance_source)
        self.assertIn("msvcrt.locking", single_instance_source)
        self.assertIn("def schedule_startup_maintenance", maintenance_source)
        self.assertIn("def start_external_startup_splash", splash_source)
        self.assertIn("STARTUP_SPLASH_COMMAND_FILE_ENV", splash_source)
        self.assertIn("APP_ACTIVATION_REQUEST_FILE_NAME", activation_source)
        self.assertIn("def request_existing_instance_activation", activation_source)
        self.assertIn("--startup-splash-host", splash_source)
        self.assertIn("if _startup_splash_process.poll() is None:", splash_source)
        self.assertIn("os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)", splash_source)
        self.assertIn("request_existing_instance_activation()", source)
        self.assertIn('if not os.environ.get("_PYI_SPLASH_IPC"):', splash_source)
        self.assertIn('update_pyinstaller_boot_splash("Already running.")', source)
        self.assertIn('update_pyinstaller_boot_splash("Loading...")', source)
        self.assertLess(
            source.index("args = parser.parse_args(argv)"),
            source.index("schedule_startup_maintenance()"),
        )
        self.assertLess(
            source.index("schedule_startup_maintenance()"),
            source.index("runner = run_gui_workflow"),
        )

    def test_gui_has_heartbeat_and_hang_watchdog(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8") + "\n" + SHELL_WINDOW_RUNTIME_STATE.read_text(encoding="utf-8")
        preview_core_source = (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_native_core.py").read_text(encoding="utf-8")
        preview_memory_source = (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_memory.py").read_text(encoding="utf-8")
        combined_source = source + "\n" + preview_core_source + "\n" + preview_memory_source
        diagnostics_source = (ROOT / "cdmw" / "ui" / "shell" / "diagnostics_controller.py").read_text(encoding="utf-8")
        diagnostics_service_source = DIAGNOSTICS_SERVICE.read_text(encoding="utf-8")
        self.assertIn("heartbeat_path = crash_reports_dir / \"app_heartbeat.json\"", source)
        self.assertIn("runtime_events_current.jsonl", source)
        self.assertIn("native_events_current.jsonl", source)
        self.assertIn("class RuntimeEventRecorder", diagnostics_service_source)
        self.assertIn("self._runtime_event_ring = deque(maxlen=max(1, int(ring_size)))", diagnostics_service_source)
        self.assertIn("_runtime_event_recorder = RuntimeEventRecorder(", source)
        self.assertIn("def _record_runtime_event", source)
        self.assertIn("def windows_process_memory_snapshot", diagnostics_source)
        self.assertIn("from cdmw.services.diagnostics_service import", source)
        self.assertIn("def rotate_runtime_event_logs", diagnostics_service_source)
        self.assertIn("def process_is_alive", diagnostics_service_source)
        self.assertIn("def should_write_crash_report", diagnostics_service_source)
        self.assertIn("_should_write_crash_report(", source)
        self.assertIn("process_memory", diagnostics_service_source)
        self.assertIn("child_process_memory", diagnostics_service_source)
        self.assertIn("preview_core_process_private_bytes", combined_source)
        self.assertIn("archive_memory_audit_timer", source)
        self.assertIn("def _record_archive_memory_audit", combined_source)
        self.assertIn('"archive_memory_audit"', combined_source)
        self.assertIn("shutdown_native_preview_core_service", combined_source)
        self.assertIn("archive_preview_core_idle_shutdown_timer", source)
        self.assertIn("def _shutdown_idle_native_preview_core_service(self) -> None:", combined_source)
        self.assertIn('"native_preview_core_idle_shutdown"', combined_source)
        self.assertIn('"archive_item_icon_cache_limit"', combined_source)
        self.assertIn('"archive_item_icon_preload_queue_entries"', combined_source)
        self.assertIn('"preview_core_idle_shutdown_timer_active"', combined_source)
        self.assertIn('"d3d11_frame_count"', combined_source)
        self.assertIn('"d3d11_render_request_count"', combined_source)
        self.assertIn('"d3d11_render_suppressed_count"', combined_source)
        self.assertIn('"d3d11_parent_unresponsive_count"', combined_source)
        self.assertIn("main_process_private_bytes", combined_source)
        self.assertIn("d3d11_estimated_texture_bytes", combined_source)
        self.assertIn("def _set_last_active_operation", source)
        self.assertIn("def _check_previous_unclean_exit", source)
        self.assertIn("_process_is_alive", source)
        self.assertIn("previous_pid_alive", diagnostics_service_source)
        self.assertIn("def _start_hang_watchdog", source)
        self.assertIn("def start_hang_watchdog", diagnostics_service_source)
        self.assertIn("_start_hang_watchdog_service(", source)
        self.assertIn('"app_hang_detected"', diagnostics_service_source)
        self.assertIn('"previous_session_unclean_exit"', diagnostics_service_source)
        self.assertIn("_previous_session_unclean = _check_previous_unclean_exit()", source)
        self.assertIn("def start_heartbeat_timer", diagnostics_source)
        self.assertIn("timer.timeout.connect(write_heartbeat)", diagnostics_source)
        self.assertIn("_start_heartbeat_timer_controller(app, _write_heartbeat)", source)
        self.assertIn("fault_handler.enable", diagnostics_service_source)

    def test_problem_report_sharing_actions_are_wired_and_exported(self) -> None:
        menus_source = SHELL_MENUS.read_text(encoding="utf-8")
        wiring_source = SIGNAL_WIRING.read_text(encoding="utf-8")
        profile_source = PROFILE_CONTROLLER.read_text(encoding="utf-8")
        startup_source = STARTUP_CONTROLLER.read_text(encoding="utf-8")
        diagnostics_service_source = DIAGNOSTICS_SERVICE.read_text(encoding="utf-8")

        self.assertIn('self.copy_problem_summary_action = self.help_menu.addAction("Copy Latest Problem Summary")', menus_source)
        self.assertIn('self.open_crash_reports_action = self.help_menu.addAction("Open Crash Reports Folder")', menus_source)
        self.assertIn("self.copy_problem_summary_action.triggered.connect(self.copy_latest_problem_summary)", wiring_source)
        self.assertIn("self.open_crash_reports_action.triggered.connect(self.open_crash_reports_folder)", wiring_source)
        self.assertIn("def open_crash_reports_folder(self) -> None:", profile_source)
        self.assertIn("def copy_latest_problem_summary(self) -> None:", profile_source)
        self.assertIn("format_issue_summary(", profile_source)
        self.assertIn("latest_diagnostic_report_files(", profile_source)
        self.assertIn('archive.writestr("issue_summary.txt", issue_summary)', profile_source)
        self.assertIn('archive.writestr("diagnostics_index.json", json.dumps(diagnostics_index, indent=2))', profile_source)
        self.assertIn("def traceback_diagnostic_details", diagnostics_service_source)
        self.assertIn("def diagnostic_report_index", diagnostics_service_source)
        self.assertIn("def format_issue_summary", diagnostics_service_source)
        self.assertIn("Help > Export Diagnostics", startup_source)

    def test_app_icon_is_loaded_from_packaged_and_internal_paths(self) -> None:
        source = "\n".join(
            (
                THEME_CONTROLLER.read_text(encoding="utf-8"),
                ACTIVATION_CONTROLLER.read_text(encoding="utf-8"),
                SHELL_APP_STARTUP.read_text(encoding="utf-8"),
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SHELL_STARTUP_SPLASH.read_text(encoding="utf-8"),
            )
        )
        app_icon_source = APP_ICON.read_text(encoding="utf-8")
        icon_controller_source = (ROOT / "cdmw" / "ui" / "shell" / "icon_controller.py").read_text(encoding="utf-8")
        self.assertIn("def iter_app_icon_candidate_paths(theme_key: Optional[str] = None) -> Tuple[Path, ...]:", app_icon_source)
        self.assertIn('Path("_internal") / "assets" / "cdmw.ico"', app_icon_source)
        self.assertIn('Path("assets") / "theme_icons" / f"cdmw_{theme_stem}.ico"', app_icon_source)
        self.assertIn("def load_app_icon(theme_key: Optional[str] = None) -> Tuple[QIcon, Optional[Path]]:", app_icon_source)
        self.assertIn("if not icon.isNull():", app_icon_source)
        self.assertIn("class AppWindowIconEventFilter(QObject):", icon_controller_source)
        self.assertIn("def set_app_icon(self, app_icon: QIcon) -> None:", icon_controller_source)
        self.assertIn("app_icon, _icon_path = load_app_icon(startup_theme)", source)
        self.assertIn("app_icon, _icon_path = load_app_icon(self.current_theme_key)", source)
        self.assertIn("def _apply_theme_window_icon(self, theme_key: str) -> None:", source)
        self.assertIn("self.setWindowIcon(app_icon)", source)
        self.assertIn("app.setWindowIcon(app_icon)", source)
        self.assertIn("QSystemTrayIcon", source)
        self.assertIn("def _configure_system_tray_icon", source)
        self.assertIn("tray_icon.show()", source)
        self.assertIn("def _poll_existing_instance_activation_request", source)
        self.assertIn('self._present_main_window("second_launch")', source)
        self.assertIn("startup_splash.setWindowIcon(app.windowIcon())", source)
        self.assertIn("external_splash_file is not None and external_splash_file.is_file()", source)
        self.assertIn("close_pyinstaller_boot_splash()", source)
        spec_source = ROOT.joinpath("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        self.assertIn('_add_data_tree_if_exists(datas, "assets/theme_icons", "assets/theme_icons"', spec_source)
        self.assertLess(
            source.index("apply_windows_app_user_model_id()"),
            source.index("app = QApplication(sys.argv)"),
        )

    def test_external_startup_splash_sets_taskbar_icon_before_show(self) -> None:
        source = STARTUP_SPLASH_HOST.read_text(encoding="utf-8")
        app_icon_source = APP_ICON.read_text(encoding="utf-8")
        self.assertIn("def _apply_windows_app_user_model_id() -> None:", source)
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", source)
        self.assertIn("from cdmw.ui.app_icon import resolve_app_icon_path", source)
        self.assertIn("QIcon", source)
        self.assertIn("app.setWindowIcon(app_icon)", source)
        self.assertIn("dialog.setWindowIcon(app_icon)", source)
        self.assertIn("icon_path = resolve_app_icon_path(initial_theme_key)", source)
        self.assertIn("icon_path = resolve_app_icon_path(resolved_theme_key)", source)
        self.assertLess(
            source.index("    _apply_windows_app_user_model_id()"),
            source.index("app = QApplication(sys.argv[:1])"),
        )
        self.assertLess(
            source.index("dialog.setWindowIcon(app_icon)"),
            source.index("dialog.show()"),
        )
        self.assertIn('Path("_internal") / "assets" / "cdmw.ico"', app_icon_source)
        self.assertIn('Path("assets") / "theme_icons" / f"cdmw_{theme_stem}.ico"', app_icon_source)
        self.assertIn("def resolve_app_icon_path(theme_key: Optional[str] = None) -> Optional[Path]:", app_icon_source)

    def test_external_startup_splash_reads_saved_theme(self) -> None:
        app_source = APP_STARTUP_SPLASH.read_text(encoding="utf-8")
        host_source = STARTUP_SPLASH_HOST.read_text(encoding="utf-8")
        self.assertIn("def read_startup_theme_key() -> str:", app_source)
        self.assertIn('"theme_key": str(theme_key or read_startup_theme_key())', app_source)
        self.assertIn("startup_theme_key = read_startup_theme_key()", app_source)
        self.assertIn("from cdmw.ui.themes import UI_THEME_SCHEMES", host_source)
        self.assertIn("def _set_theme(self, theme_key: object) -> None:", host_source)
        self.assertIn('self._set_theme(payload.get("theme_key", self._theme_key))', host_source)

    def test_app_icon_resolver_finds_repo_asset(self) -> None:
        from cdmw.ui.app_icon import resolve_app_icon_path

        self.assertEqual(resolve_app_icon_path(), ROOT / "assets" / "cdmw.ico")
        self.assertEqual(resolve_app_icon_path("graphite"), ROOT / "assets" / "theme_icons" / "cdmw_graphite.ico")

    def test_background_crash_context_does_not_read_live_qt_widgets(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("_cached_crash_context", source)
        self.assertIn("app.thread() != QThread.currentThread()", source)
        self.assertIn("context.update(_cached_crash_context)", source)
        self.assertIn("runtime_event_tail", source)
        self.assertIn("native_diagnostic_event_tail", source)
        self.assertIn("last_active_operation", source)
        self.assertIn("d3d11_status_payload", source)
        self.assertIn("d3d11_process_state", source)
        self.assertIn("d3d11_process_memory", source)
        self.assertIn("archive_isolated_package_worker_active", source)

    def test_runtime_events_include_performance_stability_fields(self) -> None:
        source = _main_window_source() + "\n"
        source += CLOSE_CONTROLLER.read_text(encoding="utf-8") + "\n"
        source += (ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8")
        source += "\n"
        source += (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_loading.py").read_text(encoding="utf-8")
        source += "\n" + (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_memory.py").read_text(encoding="utf-8")
        for token in (
            "close_phase",
            "responsive_resize_elapsed_ms",
            "preview_phase",
            "preview_stalled",
            "memory_total_private_bytes",
            "builder_startup_step_elapsed_ms",
        ):
            self.assertIn(token, source)

    def test_close_waits_for_workers_asynchronously(self) -> None:
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")
        close_source = CLOSE_CONTROLLER.read_text(encoding="utf-8")
        protocol_source = WORKER_PROTOCOL.read_text(encoding="utf-8")
        source = main_source + "\n" + close_source
        self.assertIn("def _begin_deferred_close_for_workers", close_source)
        self.assertIn("event.ignore()", close_source)
        self.assertIn("thread.finished.connect(self._finish_deferred_close_if_workers_stopped", close_source)
        self.assertIn("self._close_force_accept = True", close_source)
        self.assertIn("CLOSE_WORKER_FORCE_STOP_AFTER_SECONDS", close_source)
        self.assertIn("def _force_stop_close_worker_threads", close_source)
        self.assertIn("self._force_stop_close_worker_threads(running_entries)", close_source)
        self.assertIn("def _request_tab_shutdowns(self) -> None:", close_source)
        self.assertIn('getattr(tab, "request_shutdown", None)', close_source)
        self.assertIn('getattr(tab, "iter_shutdown_workers", None)', close_source)
        self.assertIn("class ShutdownAwareTab(Protocol):", protocol_source)
        self.assertIn("class CancellableWorker(Protocol):", protocol_source)
        self.assertIn('close_phase="force_stop"', close_source)
        self.assertIn('close_phase="waiting"', close_source)
        self.assertIn('close_phase="ready_to_accept"', close_source)
        self.assertIn('close_phase="begin_deferred"', close_source)
        self.assertIn('close_phase="finalize"', close_source)
        self.assertIn("def _finalize_close(self) -> None:", close_source)
        self.assertIn("def closeEvent(self, event) -> None:", close_source)
        self.assertIn("def _clear_active_main_window(window: object) -> None:", main_source)
        close_start = close_source.index("    def _begin_deferred_close_for_workers")
        close_body = close_source[close_start:]
        self.assertNotIn("self.hide()", close_body)
        self.assertNotIn("self.setEnabled(False)", close_body)
        self.assertNotIn(".wait(", close_body)
        self.assertNotIn("thread.wait(wait_ms)", source)
        self.assertNotIn("wait_ms: int = 1200", source)

    def test_worker_tabs_expose_nonblocking_shutdown_protocol(self) -> None:
        for tab_path in (
            TEXT_SEARCH_TAB,
            RESEARCH_TAB,
            REPLACE_ASSISTANT_TAB,
            TEXTURE_EDITOR_TAB,
            ITEM_ICONS_TAB,
        ):
            with self.subTest(tab=tab_path.name):
                source = tab_path.read_text(encoding="utf-8")
                if tab_path == TEXT_SEARCH_TAB:
                    source += "\n" + TEXT_SEARCH_CONTROLLER.read_text(encoding="utf-8")
                if tab_path == TEXTURE_EDITOR_TAB:
                    source += "\n" + TEXTURE_EDITOR_WORKER_LIFECYCLE.read_text(encoding="utf-8")
                self.assertIn("def iter_shutdown_workers", source)
                self.assertIn("def request_shutdown", source)
                self.assertIn("self.request_shutdown()", source)
                self.assertNotIn(".wait(", source)

    def test_clean_native_fault_log_is_suppressed_on_normal_exit(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        diagnostics_service_source = DIAGNOSTICS_SERVICE.read_text(encoding="utf-8")
        self.assertIn('"native_fault_current.log"', diagnostics_service_source)
        self.assertIn("def _cleanup_native_fault_log_on_exit(*, clean_exit: bool) -> None:", source)
        self.assertIn("fault_handler.disable", diagnostics_service_source)
        self.assertIn("fault_log_path.stat().st_size == 0", diagnostics_service_source)
        self.assertIn("fault_log_path.unlink()", diagnostics_service_source)
        self.assertIn("_cleanup_native_fault_log_on_exit(clean_exit=bool(normal_exit))", source)
        self.assertNotIn("native fault log session", source)

    def test_previous_session_unclean_reports_are_deduped_by_session(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        diagnostics_service_source = DIAGNOSTICS_SERVICE.read_text(encoding="utf-8")
        self.assertIn("def crash_report_kind_already_covers_session", diagnostics_service_source)
        self.assertIn('reports_dir.glob(f"{normalized_kind}_*.log")', diagnostics_service_source)
        self.assertIn("def check_previous_unclean_exit", diagnostics_service_source)
        self.assertIn("_check_previous_unclean_exit_service(", source)
        self.assertIn(
            'duplicate_report_checker(Path(reports_dir), "previous_session_unclean_exit", previous_session_id)',
            diagnostics_service_source,
        )
        self.assertIn('"previous_session_unclean_exit_suppressed_duplicate"', diagnostics_service_source)
        self.assertIn("record_runtime_event_fn(", diagnostics_service_source)
        self.assertIn("if bool(payload.get(\"clean_shutdown\")):\n            return False", diagnostics_service_source)

    def test_archive_scan_breadcrumbs_are_recorded_for_native_faults(self) -> None:
        scan_worker_source = (ROOT / "cdmw" / "workers" / "archive_scan_workers.py").read_text(encoding="utf-8")
        archive_source = "\n".join(
            (
                ARCHIVE.read_text(encoding="utf-8"),
                ARCHIVE_FORMAT.read_text(encoding="utf-8"),
            )
        )
        self.assertIn("archive_scan_breadcrumb.json", scan_worker_source)
        self.assertIn("def _write_scan_breadcrumb", scan_worker_source)
        self.assertIn("on_breadcrumb=self._write_scan_breadcrumb", scan_worker_source)
        self.assertIn("on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]]", archive_source)
        self.assertIn('"phase": "parse_archive_pamt"', archive_source)
        self.assertIn('"pamt_path": str(pamt_path)', archive_source)

    def test_ui_breadcrumbs_are_recorded_for_unclean_exit_context(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        diagnostics_service_source = DIAGNOSTICS_SERVICE.read_text(encoding="utf-8")
        worker_source = TEXTURE_WORKERS.read_text(encoding="utf-8")
        self.assertIn("ui_breadcrumb.json", diagnostics_service_source)
        self.assertIn("texture_workflow_breadcrumb.json", diagnostics_service_source)
        self.assertIn("def _write_ui_breadcrumb", source)
        self.assertIn("def _write_texture_workflow_breadcrumb", worker_source)
        self.assertIn("def _add_persisted_crash_breadcrumbs", source)
        self.assertIn('context["ui_breadcrumb"]', diagnostics_service_source)
        self.assertIn('context["texture_workflow_breadcrumb"]', diagnostics_service_source)
        self.assertIn("previous_context: dict[str, object]", diagnostics_service_source)
        self.assertIn("add_breadcrumbs_fn(previous_context)", diagnostics_service_source)
        self.assertIn("add_breadcrumbs_fn=_add_persisted_crash_breadcrumbs", source)
        self.assertIn("persisted_runtime_event_tail", diagnostics_service_source)
        self.assertIn("persisted_native_event_tail", diagnostics_service_source)

    def test_d3d11_qprocess_cleanup_is_runtime_guarded(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_d3d11_process.py").read_text(encoding="utf-8")
            + "\n"
            + (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_d3d11_runtime.py").read_text(encoding="utf-8")
        )
        self.assertIn("def _archive_qprocess_state", source)
        self.assertIn("def _delete_archive_qprocess_later", source)
        self.assertIn("def _cleanup_finished_archive_isolated_renderer_process", source)
        self.assertIn("_archive_qprocess_pid", source)
        self.assertIn("cleanup_finished_process", source)
        self.assertIn("kill_process_if_still_running", source)
        self.assertIn("d3d11_process_shutdown_begin", source)
        self.assertNotIn("lambda *_args, package_dir=package_dir, process=process: (", source)
        self.assertNotIn("process.finished.connect(process.deleteLater)", source)

    def test_texture_workflow_workers_write_breadcrumbs_from_callbacks(self) -> None:
        source = TEXTURE_WORKERS.read_text(encoding="utf-8")
        self.assertIn("_texture_workflow_breadcrumb_base(self.config, self.worker_name)", source)
        self.assertIn('worker_name = "BuildWorker"', source)
        self.assertIn('worker_name = "DdsToPngWorker"', source)
        self.assertIn("last_external_tool_step", source)
        self.assertIn("on_log=emit_log", source)
        self.assertIn("on_current_file=emit_current_file", source)

    def test_archive_scan_progress_is_not_emitted_from_nested_python_thread(self) -> None:
        archive_source = "\n".join(
            (
                ARCHIVE.read_text(encoding="utf-8"),
                ARCHIVE_FORMAT.read_text(encoding="utf-8"),
            )
        )
        self.assertNotIn("emit_parse_heartbeat", archive_source)
        self.assertNotIn("heartbeat_thread = threading.Thread", archive_source)
        self.assertNotIn("heartbeat_stop = threading.Event()", archive_source)

    def test_archive_pamt_parser_avoids_giant_record_lists(self) -> None:
        archive_source = ARCHIVE_FORMAT.read_text(encoding="utf-8")
        self.assertIn("max_cache_entries: int = 200_000", archive_source)
        self.assertIn("seen_offsets: set[int] = set()", archive_source)
        self.assertIn("file_table = memoryview(data)[off : off + file_table_size]", archive_source)
        self.assertIn('struct.iter_unpack("<IIIIHH", file_table)', archive_source)
        self.assertNotIn('files = list(struct.iter_unpack("<IIIIHH"', archive_source)

    def test_archive_preview_inner_splitter_keeps_references_visible_before_overlap(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_PANEL.read_text(encoding="utf-8"),
            )
        )
        self.assertIn("archive_preview_main_widget.setMinimumWidth(0)", source)
        self.assertIn("self.archive_preview_title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)", source)
        self.assertIn("self.archive_texture_refs_group.setMinimumWidth(320)", source)
        self.assertIn("self.archive_preview_content_splitter.setChildrenCollapsible(True)", source)
        self.assertIn("def _clamp_archive_preview_asset_map_splitter(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("min_preview_width = 560", source)
        self.assertIn("min_refs_width = max(240, min(320, configured_refs_min or 300))", source)
        self.assertIn("max_refs_width = min(680", source)
        self.assertIn("Keep Asset Family visible even in compact or freshly reflowed layouts.", source)
        self.assertIn("self.archive_preview_content_splitter.setCollapsible(1, not has_asset_relationships)", source)
        self.assertIn("self.archive_preview_content_splitter.setCollapsible(1, False)", source)
        self.assertNotIn("target_sizes = [total, 0]", source)
        self.assertIn("self.archive_preview_content_splitter.setSizes(target_sizes)", source)

    def test_loose_preview_toggle_is_two_state_action(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PREVIEW_RESULT.read_text(encoding="utf-8")
            + "\n"
            + (ROOT / "cdmw" / "ui" / "archive_browser" / "preview_state.py").read_text(encoding="utf-8")
        )
        self.assertIn("def _toggle_archive_loose_preview", source)
        self.assertIn("self.archive_preview_requested_loose = not bool(self.archive_preview_showing_loose)", source)
        self.assertIn("self._show_archive_preview_result(result, use_loose=self.archive_preview_requested_loose)", source)
        self.assertIn('"Archive File" if self.archive_preview_showing_loose else "Loose File"', source)
        self.assertNotIn("def _toggle_archive_loose_preview(self) -> None:\n            self.archive_preview_requested_loose = False", source)

    def test_archive_preview_refresh_respects_loose_asset_arguments(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + (ROOT / "cdmw" / "ui" / "archive_browser" / "workers.py").read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PREVIEW_SETTINGS.read_text(encoding="utf-8")
        )
        self.assertIn("include_loose_preview_assets=include_loose_preview_assets", source)
        self.assertIn("prefer_loose_preview=self.archive_preview_requested_loose", source)
        self.assertIn("self.archive_preview_requested_loose = bool(entry is not None and prefer_loose_preview)", source)
        self.assertNotIn("include_loose_preview_assets = False\n            prefer_loose_preview = False", source)

    def test_floating_preview_settings_syncs_back_to_settings_tab(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PREVIEW_SETTINGS.read_text(encoding="utf-8")
        )
        self.assertIn("def _sync_model_preview_settings_controls", source)
        self.assertIn("settings_tab._apply_model_preview_controls(settings)", source)
        self.assertIn("dialog.set_settings(settings)", source)
        self.assertIn("self._sync_model_preview_settings_controls()", source)

    def test_startup_splash_has_abstract_animation(self) -> None:
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")
        startup_source = "\n".join(
            (
                STARTUP_CONTROLLER.read_text(encoding="utf-8"),
                SHELL_STARTUP_SPLASH.read_text(encoding="utf-8"),
            )
        )
        workspace_layout_source = SHELL_WORKSPACE_LAYOUT.read_text(encoding="utf-8")
        source = "\n".join((startup_source, main_source, workspace_layout_source))
        splash_source = STARTUP_DIALOGS.read_text(encoding="utf-8")
        self.assertIn("class StartupSignalMark", splash_source)
        self.assertIn("def _draw_cdmw_block_wave", splash_source)
        self.assertIn("def _draw_iso_block", splash_source)
        self.assertIn("QLinearGradient", splash_source)
        self.assertIn("QPolygonF", splash_source)
        self.assertIn("painter.drawPolygon(top)", splash_source)
        self.assertIn("wave = (math.sin(phase_radians + col * 0.72 + row * 0.58) + 1.0) * 0.5", splash_source)
        self.assertIn("self._timer = QTimer(self)", splash_source)
        self.assertIn("def paintEvent(self, event) -> None", splash_source)
        self.assertIn("self.signal_mark = StartupSignalMark", splash_source)
        self.assertIn("self.signal_mark.stop()", splash_source)
        self.assertIn("remaining_minimum_visible_ms", splash_source)
        self.assertIn("self._minimum_visible_seconds = 3.0", splash_source)
        self.assertIn("QTimer.singleShot(remaining_ms, self._release_startup_splash)", source)
        self.assertIn("def close_pyinstaller_boot_splash() -> None:", startup_source)
        self.assertIn("close_pyinstaller_boot_splash()", source)
        self.assertIn("class ExternalStartupSplashAdapter", startup_source)
        self.assertIn('os.environ.get("CDMW_STARTUP_SPLASH_COMMAND_FILE"', source)
        self.assertIn("self.setFixedSize(420, 210)", splash_source)
        self.assertIn("self.detail_label.setMinimumHeight(42)", splash_source)
        self.assertIn("font-size: 10px", splash_source)
        self.assertIn("def format_startup_splash_detail(", startup_source)
        self.assertIn("def _show_main_window_after_startup_splash(self) -> None:", source)
        self.assertIn("def _finish_startup_splash_and_show_main_window(self) -> None:", source)
        finish_start = source.index("def _finish_startup_splash_and_show_main_window(self) -> None:")
        finish_body = source[finish_start : source.index("def _release_startup_splash(self) -> None:", finish_start)]
        self.assertIn("def _finish_startup_splash_after_main_window_paint(self) -> None:", source)
        self.assertIn("Qt.WindowStaysOnTopHint", splash_source)
        self.assertLess(finish_body.index("self._show_main_window_after_startup_splash()"), finish_body.index("self._schedule_startup_splash_finish_after_main_window_paint(180)"))
        self.assertNotIn("self._finish_startup_splash_now()\n            self._show_main_window_after_startup_splash()", finish_body)
        self.assertIn("startup_splash_first_paint_timeout", source)
        self.assertIn('self._update_startup_splash("Opening workspace...", 1, 1)', finish_body)
        self.assertIn("app.processEvents()", finish_body)
        self.assertIn("QTimer.singleShot(0, self._finish_startup_splash_and_show_main_window)", source)
        self.assertNotIn("_show_main_window_behind_startup_splash", source)
        self.assertIn("def _finish_startup_splash_now(self) -> None:", source)
        self.assertIn("def pump_animation_frame", startup_source)
        self.assertIn("MainWindow(startup_splash=startup_splash)", source)
        self.assertIn('pump_startup_splash("Preparing archive browser...")', source)
        self.assertIn("def _splash_theme_color", splash_source)
        self.assertIn("def _splash_accent_block_colors", splash_source)
        self.assertIn("self._theme_key = _splash_resolved_theme_key(theme_key)", splash_source)
        self.assertIn("StartupProgressCard(self, theme_key=self._theme_key)", splash_source)
        self.assertIn("StartupSignalMark(self.progress_card, theme_key=self._theme_key)", splash_source)
        self.assertIn("StartupSplashDialog(theme_key=startup_theme)", source)
        self.assertIn("ExternalStartupSplashAdapter(external_splash_file, theme_key=startup_theme)", source)
        self.assertNotIn("build_speed = 1.62", splash_source)
        self.assertNotIn("compass_radius", splash_source)
        self.assertNotIn("platform_y", splash_source)
        splash_animation_source = splash_source[
            splash_source.index("class StartupSignalMark") : splash_source.index("class StartupArchivePathDialog")
        ]
        self.assertNotIn("painter.drawArc", splash_animation_source)
        self.assertNotIn("dot_angle = (self._phase * math.tau)", splash_source)
        self.assertNotIn("route = QPainterPath()", splash_source)
        self.assertNotIn("Qt.DashLine", splash_source)
        self.assertIn("QFrame#StartupSignalMark", splash_source)
        self.assertNotIn('QLabel("CDMW")', splash_source)

    def test_crimson_desert_theme_is_available(self) -> None:
        source = THEMES.read_text(encoding="utf-8")
        self.assertIn('"crimson_desert"', source)
        self.assertIn('"label": "Crimson Desert"', source)
        self.assertIn('"accent": "#c56d43"', source)
        self.assertIn("QMenu::item:disabled", source)
        self.assertIn("QMenu::item:!enabled", source)
        self.assertIn("QMenu::item:selected:disabled", source)
        self.assertIn("QMenu::item:disabled:selected", source)
        self.assertIn("QMenu::item:selected:!enabled", source)
        self.assertIn("QMenu::item:!enabled:selected", source)
        self.assertIn("QToolButton#ArchiveActionMenuButton:disabled", source)
        self.assertIn('color: {theme["button_disabled_text"]};', source)

    def test_main_window_has_about_license_tab(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SHELL_MENUS.read_text(encoding="utf-8")
            + "\n"
            + SIGNAL_WIRING.read_text(encoding="utf-8")
            + "\n"
            + SHELL_TOOL_TABS.read_text(encoding="utf-8")
            + "\n"
            + ABOUT_CONTROLLER.read_text(encoding="utf-8")
            + "\n"
            + NAVIGATION_CONTROLLER.read_text(encoding="utf-8")
        )
        menu_order = [
            'self.profile_menu = menu_bar.addMenu("Profile")',
            'self.open_settings_action = menu_bar.addAction("Settings")',
            'self.window_menu = menu_bar.addMenu("Window")',
            'self.help_menu = menu_bar.addMenu("Help")',
            'self.open_about_action = menu_bar.addAction("About")',
        ]
        menu_positions = [source.index(marker) for marker in menu_order]
        self.assertEqual(menu_positions, sorted(menu_positions))
        self.assertIn('self.quick_start_menu_action = self.help_menu.addAction("Quick Start")', source)
        self.assertIn('self.open_documentation_action = self.help_menu.addAction("Documentation")', source)
        self.assertIn("self.open_settings_action.triggered.connect(self.show_settings)", source)
        self.assertIn("def show_settings(self, _checked: bool = False) -> None:", source)
        self.assertIn("settings_tab_index = self.main_tabs.addTab(self.settings_tab, \"Settings\")", source)
        self.assertIn("self.main_tabs.setTabVisible(settings_tab_index, False)", source)
        self.assertIn('self.open_about_action = menu_bar.addAction("About")', source)
        self.assertIn("def _build_about_page(self) -> QWidget:", source)
        self.assertIn("def show_about_dialog(self, _checked: bool = False) -> None:", source)
        self.assertIn("def show_documentation_dialog(self, _checked: bool = False, topic_id: str = \"\") -> None:", source)
        self.assertNotIn("support_menu_action", source)
        self.assertNotIn('self.main_tabs.addTab(self.about_tab, "About")', source)
        self.assertNotIn('about_tabs.addTab(docs_page, "Documentation")', source)
        self.assertIn('about_tabs.addTab(license_page, "License")', source)
        self.assertIn("def _read_license_text(self) -> str:", source)
        self.assertIn("self._read_project_text_file(", source)
        self.assertIn('"LICENSE"', source)
        self.assertIn("license_edit.setPlainText(self._read_license_text())", source)

    def test_settings_page_uses_left_navigation(self) -> None:
        settings_source = (ROOT / "cdmw" / "ui" / "settings_tab.py").read_text(encoding="utf-8")
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")
        navigation_source = NAVIGATION_CONTROLLER.read_text(encoding="utf-8")
        startup_source = STARTUP_CONTROLLER.read_text(encoding="utf-8")
        shell_startup_source = main_source + "\n" + startup_source
        main_behavior_source = (
            main_source
            + "\n"
            + startup_source
            + "\n"
            + (ROOT / "cdmw" / "ui" / "archive_browser" / "filter_workers.py").read_text(encoding="utf-8")
        )

        self.assertIn("self.section_nav_list = QListWidget()", settings_source)
        self.assertIn('self.section_nav_list.setObjectName("SettingsSectionNav")', settings_source)
        self.assertIn("self.section_nav_list.setFixedWidth(270)", settings_source)
        self.assertIn("item.setSizeHint(QSize(0, 40))", settings_source)
        self.assertIn("def _apply_section_nav_style(self) -> None:", settings_source)
        self.assertIn("QListWidget#SettingsSectionNav::item:hover", settings_source)
        self.assertIn("QListWidget#SettingsSectionNav::item:selected", settings_source)
        self.assertIn("self.section_stack = QStackedWidget()", settings_source)
        for title in (
            '"Setup"',
            '"Startup"',
            '"Paths"',
            '"Performance"',
            '"Appearance"',
            '"Layout"',
            '"Safety"',
        ):
            self.assertIn(title, settings_source)
        self.assertIn("self.setup_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.startup_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.paths_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.archive_performance_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.appearance_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.layout_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.safety_page_layout = _add_settings_page(", settings_source)
        self.assertIn("self.setup_page_layout.insertWidget(2, setup_section)", settings_source)
        self.assertIn("toggle_button.setVisible(False)", settings_source)
        self.assertIn("self.setup_section.set_expanded(True)", navigation_source)
        self.assertIn("self.paths_page_layout.insertWidget(2, paths_section)", settings_source)
        self.assertIn("self.paths_page_layout.insertWidget(3, archive_locations_section)", settings_source)
        self.assertNotIn("restore_archive_filters_checkbox", settings_source)
        self.assertNotIn("\"preferences/restore_archive_filters_on_startup\"", settings_source)
        self.assertNotIn("restore_archive_filters = self._preference_bool(\"restore_archive_filters_on_startup\", False)", main_source)
        self.assertIn("Archive Browser starts with neutral filters.", settings_source)
        archive_filters_source = ARCHIVE_FILTERS.read_text(encoding="utf-8")
        self.assertIn("def _neutral_archive_filter_state(self) -> Dict[str, object]:", archive_filters_source)
        self.assertIn("self._apply_archive_filter_state(self._neutral_archive_filter_state())", startup_source)
        self.assertNotIn("QTimer.singleShot(6500, window._release_startup_splash)", shell_startup_source)
        self.assertIn('_write_heartbeat("archive_autoload_queued")', startup_source)
        self.assertIn('startup_splash.set_detail("Loading Archive Browser...")', startup_source)
        autoload_start = startup_source.index("    if window._startup_archive_autoload_expected():")
        autoload_body = startup_source[autoload_start: startup_source.index("    else:", autoload_start)]
        self.assertNotIn("window._release_startup_splash()", autoload_body)
        self.assertNotIn("QTimer.singleShot(500, self._maybe_autoload_archive_on_startup)", shell_startup_source)
        self.assertIn("Startup archive auto-load skipped because the previous session did not shut down cleanly", startup_source)
        self.assertIn("self.archive_startup_autoload_defer_preview = True", startup_source)
        self.assertIn("defer_default_selection=defer_default_selection", main_behavior_source)
        self.assertIn("def show_settings_section(self, key: str) -> None:", settings_source)
        self.assertIn('self.settings_tab.show_settings_section("setup")', navigation_source)
        self.assertIn('self.settings_tab.show_settings_section("paths")', navigation_source)

    def test_archive_browser_has_asset_catalog_scope_dialog(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SHELL_WINDOW_RUNTIME_STATE.read_text(encoding="utf-8"),
                ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_FILTER_CONTROLS.read_text(encoding="utf-8"),
                ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8"),
                ARCHIVE_INDEX_WORKERS_UI.read_text(encoding="utf-8"),
                ARCHIVE_RENDER_LIFECYCLE.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_CATALOG.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_CATALOG_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_CATALOG_SCOPE.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_REFERENCES.read_text(encoding="utf-8"),
                ARCHIVE_ICON_PIPELINE.read_text(encoding="utf-8"),
                ARCHIVE_MATERIAL_FINDER.read_text(encoding="utf-8"),
                ARCHIVE_UI_FORMATTING.read_text(encoding="utf-8"),
            )
        )
        self.assertIn('self.archive_asset_catalog_button = QPushButton("Item Finder")', source)
        self.assertIn('self.archive_material_finder_button = QPushButton("Material Finder")', source)
        self.assertIn('self.archive_clear_asset_scope_button = QPushButton("Clear Scope")', source)
        self.assertIn("def _show_archive_asset_catalog_dialog(self) -> None:", source)
        self.assertIn("def _show_archive_material_finder_dialog(self) -> None:", source)
        self.assertIn("def _archive_material_catalog_rows(self) -> List[Dict[str, object]]:", source)
        self.assertIn("def _archive_material_catalog_tag_counts(", source)
        self.assertIn('tag_tree.setHeaderLabels(["Material", "Items"])', source)
        self.assertIn('result_tree.setHeaderLabels(["Item", "Material tags", "Links", "Evidence"])', source)
        self.assertIn('detail_tree.setHeaderLabels(["Group", "Value"])', source)
        self.assertIn('scope_selected_button = QPushButton("Show Selected Related Set")', source)
        self.assertIn('scope_all_button = QPushButton("Show All Matches")', source)
        self.assertIn("Material Finder scoped Archive Browser to:", source)
        self.assertIn("models, material sidecars, DDS textures, and texture-layer families", source)
        self.assertIn(
            "def _apply_archive_asset_catalog_scope(self, row: Mapping[str, object], *, include_related: bool = True) -> None:",
            source,
        )
        self.assertIn("def _resolve_archive_asset_catalog_scope_entries(", source)
        self.assertIn("def _archive_asset_catalog_preview_pixmap(", source)
        self.assertIn("def _archive_asset_catalog_inventory_icon_pixmap(", source)
        self.assertIn("category_tree.setHeaderHidden(True)", source)
        self.assertIn("item_grid.setViewMode(QListView.ViewMode.IconMode)", source)
        self.assertIn("item_grid.setIconSize(QSize(86, 86))", source)
        self.assertIn("catalog_filter_timer.setInterval(160)", source)
        self.assertIn("def _queue_catalog_row_icons_for_visible_rows() -> None:", source)
        self.assertIn("loaded_count >= 4 or (time.perf_counter() - batch_started_at) >= 0.010", source)
        self.assertNotIn("def _queue_catalog_row_icons_for_all_shown_rows() -> None:", source)
        self.assertNotIn('"thumb_preload_pending"', source)
        self.assertIn("icon_row_timer.timeout.connect(_load_next_catalog_row_icon)", source)
        self.assertIn("archive_item_icon_preload_timer = QTimer(self)", source)
        self.assertIn("def _schedule_archive_asset_catalog_icon_preload(self, delay_ms: int = 900) -> None:", source)
        self.assertIn("self._schedule_archive_asset_catalog_icon_preload()", source)
        self.assertIn("self.archive_item_icon_pixmap_cache_limit = 1200", source)
        self.assertIn("self.archive_item_icon_preload_limit = 1600", source)
        self.assertIn("self.archive_item_icon_prepared_path_cache", source)
        worker_source = ARCHIVE_WORKERS.read_text(encoding="utf-8")
        self.assertIn("class ArchiveItemIconWarmupWorker(QObject):", worker_source)
        self.assertIn("while len(self.archive_item_icon_pixmap_cache) > self.archive_item_icon_pixmap_cache_limit", source)
        self.assertIn("self._cached_archive_asset_catalog_inventory_icon_pixmap(", source)
        self.assertIn("allow_sync_prepare=False", source)
        self.assertIn("evidence_label.setMinimumHeight(112)", source)
        self.assertIn("def _apply_archive_direct_scope(", source)
        self.assertIn("def _clear_archive_asset_catalog_scope(self) -> None:", source)
        self.assertIn("linked_tree.setHeaderLabels([\"Linked files\", \"Path\"])", source)
        self.assertIn('exact_scope_button = QPushButton("Show Exact Links")', source)
        self.assertIn('scope_button = QPushButton("Show Related Set")', source)
        self.assertIn("include_related: bool = True", source)
        self.assertIn("def _archive_asset_catalog_group_choices(self, category: str = \"\") -> Tuple[str, ...]:", source)
        self.assertIn("no full archive scan", source)
        self.assertIn("Item Finder scoped Archive Browser to:", source)
        self.assertIn('self.archive_texture_scope_all_button = QPushButton("Filter to Family")', source)
        self.assertIn("def _scope_all_archive_texture_references(self) -> None:", source)
        self.assertIn("Referenced file set scoped Archive Browser to:", source)

    def test_missing_archive_package_root_prompts_on_startup_and_scan(self) -> None:
        source = "\n".join(
            (
                STARTUP_CONTROLLER.read_text(encoding="utf-8"),
                PATH_CONTROLLER.read_text(encoding="utf-8"),
                UTILITY_CONTROLLER.read_text(encoding="utf-8"),
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8"),
            )
        )
        startup_dialog_source = STARTUP_DIALOGS.read_text(encoding="utf-8")
        self.assertIn("class StartupArchivePathDialog(QDialog):", startup_dialog_source)
        startup_dialog_start = startup_dialog_source.index("class StartupArchivePathDialog(QDialog):")
        startup_dialog_body = startup_dialog_source[startup_dialog_start:]
        self.assertIn("self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint", startup_dialog_body)
        self.assertIn("self.setMinimumWidth(520)", startup_dialog_body)
        self.assertIn("root_layout.setContentsMargins(14, 14, 14, 14)", startup_dialog_body)
        self.assertNotIn("self.setMinimumHeight(360)", startup_dialog_body)
        self.assertIn("QTimer.singleShot(80, self._run_initial_autodetect)", startup_dialog_body)
        self.assertIn("autodetect_archive_package_roots(on_log=logs.append)", startup_dialog_body)
        self.assertIn("looks_like_archive_package_root(Path(path_text).expanduser())", startup_dialog_body)
        self.assertIn("After you continue, CDMW will build the archive cache", startup_dialog_body)

        self.assertIn("def _show_startup_archive_path_prompt_if_needed(", source)
        prompt_start = source.index("def _show_startup_archive_path_prompt_if_needed(")
        prompt_body = source[prompt_start : source.index("    def _prompt_for_archive_package_root_if_missing(", prompt_start)]
        self.assertIn("StartupArchivePathDialog(", prompt_body)
        self.assertIn("self._startup_archive_path_prompt_open = True", prompt_body)
        self.assertIn("self._startup_archive_path_prompt_open = False", prompt_body)
        self.assertIn("self.show_quick_start_on_launch = False", prompt_body)
        self.assertIn('self.settings.setValue("archive/package_root", selected_path)', prompt_body)
        self.assertIn('os.environ["CDMW_DEFER_TEXTURE_PREVIEW"] = "1"', prompt_body)
        self.assertIn("startup_path_prompt_accepted", prompt_body)
        self.assertIn("Building archive cache. First load can take a while; let it finish.", prompt_body)
        autoload_start = source.index("    def _maybe_autoload_archive_on_startup(self) -> None:")
        autoload_body = source[autoload_start : source.index("    def _load_game_executable_fingerprints", autoload_start)]
        self.assertIn('if bool(getattr(self, "_startup_archive_path_prompt_open", False)):', autoload_body)
        self.assertIn("QTimer.singleShot(250, self._maybe_autoload_archive_on_startup)", autoload_body)
        self.assertIn("health_report = self._check_archive_cache_health(package_root_text)", autoload_body)
        self.assertIn("self._warn_if_archive_cache_stale(health_report, package_root_text)", autoload_body)
        self.assertIn("Keep CDMW open until the cache status reaches ready.", autoload_body)
        self.assertIn("self.scan_archives(\n            force_refresh=", autoload_body)
        self.assertIn("if bool(getattr(self, \"_startup_archive_path_prompt_accepted\", False)):\n            self._release_startup_splash()", autoload_body)
        self.assertIn("window._show_startup_archive_path_prompt_if_needed(startup_splash)", source)
        self.assertIn("QTimer.singleShot(0, window._maybe_autoload_archive_on_startup)", source)
        self.assertLess(
            source.index("window._show_startup_archive_path_prompt_if_needed(startup_splash)"),
            source.index("    if window._startup_archive_autoload_expected():"),
        )

        self.assertIn("def _prompt_for_archive_package_root_if_missing(", source)
        self.assertIn('box.setWindowTitle("Crimson Desert Path Required")', source)
        self.assertIn('box.addButton("Auto-detect", QMessageBox.AcceptRole)', source)
        self.assertIn('box.addButton("Browse...", QMessageBox.ActionRole)', source)
        self.assertIn(
            "self.autodetect_archive_package_root(after_success=after_autodetect)",
            source,
        )
        self.assertIn("def _run_when_background_idle(", source)
        self.assertIn(
            'self._run_when_background_idle(after_success, label="continuing archive package setup")',
            source,
        )

        startup_start = source.index("def _show_first_run_guide_if_needed(self) -> None:")
        startup_body = source[startup_start : source.index("    def _startup_archive_path_prompt_needed", startup_start)]
        self.assertIn('reason="startup"', startup_body)
        self.assertIn("after_autodetect=self._show_first_run_guide_if_needed", startup_body)
        self.assertLess(
            startup_body.index("self._prompt_for_archive_package_root_if_missing("),
            startup_body.index("self.show_quick_start_dialog()"),
        )

        scan_start = source.index("    def scan_archives(")
        scan_body = source[scan_start : source.index("    def _ensure_archive_extension_index_ready", scan_start)]
        self.assertIn("self._prompt_for_archive_package_root_if_missing(", scan_body)
        self.assertIn('reason="refresh" if force_refresh else "scan"', scan_body)
        self.assertIn("after_autodetect=lambda: self.scan_archives(", scan_body)

    def test_archive_extension_filter_is_searchable_for_rare_extensions(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SIGNAL_WIRING.read_text(encoding="utf-8"),
                ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8"),
                ARCHIVE_FILTERS.read_text(encoding="utf-8"),
            )
        )
        self.assertIn("self.archive_extension_filter_combo.setEditable(True)", source)
        self.assertIn('self.archive_extension_filter_combo.setObjectName("ArchiveExtensionFilter")', source)
        self.assertIn("self.archive_extension_filter_combo.setInsertPolicy(QComboBox.NoInsert)", source)
        self.assertIn("self.archive_extension_filter_combo.setDuplicatesEnabled(False)", source)
        self.assertIn("self.archive_extension_filter_combo.setMaxVisibleItems(32)", source)
        self.assertIn("self.archive_filter_edit.setMinimumWidth(0)", source)
        self.assertIn("self.archive_filter_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)", source)
        self.assertIn("self.archive_extension_filter_combo.setMinimumContentsLength(8)", source)
        self.assertIn("self.archive_extension_filter_combo.setMinimumWidth(0)", source)
        self.assertIn("self.archive_extension_filter_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)", source)
        self.assertIn("QComboBox#ArchiveExtensionFilter::drop-down", source)
        self.assertIn('extension_line_edit.setPlaceholderText("Select or type extension")', source)
        self.assertIn("type a specific extension directly", source)
        self.assertIn("self.archive_extension_picker_button = QToolButton()", source)
        self.assertIn('self.archive_extension_picker_button.setText("Select")', source)
        self.assertIn("self.archive_extension_picker_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)", source)
        self.assertIn("archive_filter_grid = QGridLayout()", source)
        self.assertIn("archive_filter_grid.setColumnMinimumWidth(0, 64)", source)
        self.assertIn("archive_filter_grid.setColumnStretch(1, 1)", source)
        self.assertIn("archive_filter_grid.addWidget(self.archive_extension_filter_combo, 1, 1)", source)
        self.assertIn("archive_filter_grid.addWidget(self.archive_extension_picker_button, 1, 2)", source)
        self.assertIn("self.archive_extension_picker_button.clicked.connect(self._open_archive_extension_picker)", source)
        self.assertIn("def _open_archive_extension_picker(self) -> None:", source)
        picker_start = source.index("def _open_archive_extension_picker(self) -> None:")
        picker_body = source[picker_start : source.index("def _rebuild_archive_extension_filter_choices", picker_start)]
        self.assertIn('cancel_button = QPushButton("Cancel")', picker_body)
        self.assertNotIn("continue_build_callback", picker_body)
        self.assertIn("def _archive_extension_group_label(extension: str) -> str:", source)
        self.assertIn('extension_tree.setHeaderLabels(["Extension", "Entries", "Group"])', source)
        self.assertIn('group_order = (', source)
        self.assertIn('child.setForeground(1, count_brush)', source)
        self.assertIn('archive_extension_filter_label = QLabel("Extension")', source)
        self.assertIn("self.archive_extension_filter_combo.currentTextChanged.connect(self._mark_archive_filters_dirty)", source)
        texture_group_start = source.index('if ext in {".dds"')
        texture_group = source[texture_group_start : source.index('return "Texture / Image"', texture_group_start)]
        self.assertNotIn('".paa"', texture_group)
        animation_group_start = source.index('if ext in {".paseqc"')
        animation_group = source[animation_group_start : source.index('return "Animation / Scene"', animation_group_start)]
        self.assertIn('".paa"', animation_group)

    def test_archive_browser_defaults_to_flat_view(self) -> None:
        constants_source = CONSTANTS.read_text(encoding="utf-8")
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8"),
                SETTINGS_PERSISTENCE.read_text(encoding="utf-8"),
            )
        )
        self.assertIn('ARCHIVE_BROWSER_VIEW_MODE = "flat"', constants_source)
        self.assertIn('self._add_combo_choice(self.archive_browser_view_mode_combo, "Flat", "flat")', source)
        self.assertIn('self._set_combo_by_value(self.archive_browser_view_mode_combo, ARCHIVE_BROWSER_VIEW_MODE)', source)
        self.assertNotIn('view_mode_value = "folders" if self._read_bool("archive/tree_view", True) else "flat"', source)

    def test_archive_controls_sidebar_keeps_readable_width(self) -> None:
        source = "\n".join(
            (
                (ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "ui" / "shell" / "log_controller.py").read_text(encoding="utf-8"),
                ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8"),
                MAIN_WINDOW.read_text(encoding="utf-8"),
            )
        )
        self.assertIn("def _archive_controls_sidebar_bounds(self) -> Tuple[int, int, int]:", source)
        self.assertIn("screen_width, _screen_height = available_layout_size_for(self)", source)
        self.assertIn("elif screen_width <= 1920:", source)
        self.assertIn("readable_values = (340, 390, 460)", source)
        self.assertIn('archive_controls_group.setObjectName("ArchiveControlsPanel")', source)
        self.assertIn("archive_controls_font.setPointSize(max(8, archive_controls_font.pointSize() - 1))", source)
        self.assertIn("archive_controls_min, _archive_controls_pref, archive_controls_max = self._archive_controls_sidebar_bounds()", source)
        self.assertIn("self.archive_extension_picker_button.setEnabled(not busy)", source)

    def test_archive_browser_rebalances_for_compact_screens(self) -> None:
        source = "\n".join(
            (
                (ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8"),
                MAIN_WINDOW.read_text(encoding="utf-8"),
            )
        )
        research_source = RESEARCH_TAB.read_text(encoding="utf-8")
        research_layout_source = RESEARCH_LAYOUT.read_text(encoding="utf-8")
        research_tree_helpers_source = RESEARCH_TREE_HELPERS.read_text(encoding="utf-8")
        text_search_source = TEXT_SEARCH_TAB.read_text(encoding="utf-8")
        widgets_source = WIDGETS.read_text(encoding="utf-8")
        layout_source = (ROOT / "cdmw" / "ui" / "layout_utils.py").read_text(encoding="utf-8")
        helper_source = widgets_source + "\n" + layout_source
        self.assertIn("def available_screen_size_for(widget: Optional[QWidget] = None) -> Tuple[int, int]:", helper_source)
        self.assertIn("def available_layout_size_for(widget: Optional[QWidget] = None) -> Tuple[int, int]:", helper_source)
        self.assertIn("def available_screen_width_for(widget: Optional[QWidget] = None) -> int:", helper_source)
        self.assertIn("def responsive_screen_compact_scale(widget: Optional[QWidget] = None) -> float:", helper_source)
        self.assertIn("width, height = available_layout_size_for(widget)", helper_source)
        self.assertIn("elif height <= 1080:", helper_source)
        self.assertIn("elif height <= 1200:", helper_source)
        self.assertIn("scale = ui_scale_for(widget) * responsive_screen_compact_scale(widget)", helper_source)
        self.assertIn("def build_bounded_splitter_sizes(", helper_source)
        self.assertIn("def _apply_responsive_width_policies(self) -> None:", source)
        self.assertIn("self.archive_files_group.setMaximumWidth(16777215)", source)
        self.assertNotIn("normalized[1] > _files_max", source)
        self.assertIn("def _apply_archive_preview_content_responsive_sizes(self) -> None:", source)
        self.assertIn("not self.isMaximized()", source)
        self.assertIn('window_handle.screenChanged.connect(', source)
        self.assertIn('getattr(self, "_applying_responsive_layout", False)', source)
        self.assertIn("def _apply_responsive_resize_adjustments(self) -> None:", source)
        self.assertIn("restore_saved_splitters=False", source)
        self.assertIn("schedule_column_autofit=False", source)
        self.assertIn("adjust_window_geometry=False", source)
        self.assertIn("def _screen_signature_for_responsive_layout(self) -> Tuple[int, int, float]:", source)
        self.assertIn("def _handle_responsive_screen_changed(self, _screen: object = None) -> None:", source)
        self.assertIn("if signature == getattr(self, \"_responsive_last_screen_signature\", (0, 0, 0.0)):", source)
        self.assertIn("self._responsive_metrics_dirty = True", source)
        self.assertIn("responsive_resize_elapsed_ms=elapsed_ms", source)
        self.assertIn("def resizeEvent(self, event: object) -> None:", source)
        self.assertIn("self.right_panel_stack.setMaximumWidth(16777215)", research_source)
        self.assertIn("build_bounded_splitter_sizes(total_width, [72, 28], [420, details_min], [None, None])", research_layout_source)
        self.assertIn("QTimer.singleShot(0, self.auto_fit_columns)", research_source)
        self.assertIn("saved_total = sum(", research_tree_helpers_source)
        self.assertIn("def resizeEvent(self, event: object) -> None:", research_source)
        self.assertIn("def resizeEvent(self, event: object) -> None:", text_search_source)
        self.assertIn('has_persistent_tree_column_widths(self.settings, "text_search/results"', text_search_source)
        self.assertIn("if saved_total >= viewport_width - 24:", text_search_source)

    def test_research_archive_files_supports_flat_and_folder_views(self) -> None:
        source = "\n".join(
            (
                RESEARCH_TAB.read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "ui" / "research" / "tab_side_panel_builders.py").read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "ui" / "research" / "archive_picker_controller.py").read_text(encoding="utf-8"),
            )
        )
        self.assertIn("self.archive_picker_view_combo = QComboBox()", source)
        self.assertIn('self.archive_picker_view_combo.addItem("Flat files", "flat")', source)
        self.assertIn('self.archive_picker_view_combo.addItem("Folders", "folders")', source)
        self.assertIn("self.archive_picker_view_combo.currentIndexChanged.connect(self._handle_archive_picker_view_changed)", source)
        self.assertIn("def _populate_archive_picker_tree(self) -> None:", source)
        self.assertIn("show_full_path=True", source)
        self.assertIn("self.archive_picker_flat_render_limit = 5000", source)

    def test_compact_screens_scale_controls_not_only_splitters(self) -> None:
        responsiveness_source = (ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8")
        source = responsiveness_source + "\n" + MAIN_WINDOW.read_text(encoding="utf-8")
        shell_theme_source = (ROOT / "cdmw" / "ui" / "shell" / "theme_controller.py").read_text(encoding="utf-8")
        theme_source = THEMES.read_text(encoding="utf-8")
        self.assertIn("def responsive_control_scale_for_resolution(screen_width: int, screen_height: int) -> float:", responsiveness_source)
        self.assertIn("def responsive_control_scale_for_width(screen_width: int) -> float:", responsiveness_source)
        self.assertIn("elif screen_height <= 1080:", responsiveness_source)
        self.assertIn("return min(width_scale, height_scale)", responsiveness_source)
        self.assertIn("screen_width, screen_height = available_layout_size_for(self)", source)
        self.assertIn("screen_height=screen_height", source)
        self.assertIn("scale = responsive_control_scale_for_resolution(screen_width, screen_height)", responsiveness_source)
        self.assertIn("screen_scale = responsive_control_scale_for_resolution(screen_width, screen_height)", responsiveness_source)
        self.assertNotIn("_responsive_control_scale_for_resolution(screen_width, screen_height)", responsiveness_source)
        self.assertIn("base_font_size = max(UI_FONT_SIZE_MIN", shell_theme_source)
        self.assertIn("effective_density_key = \"compact\" if screen_scale < 0.94 else density_key", shell_theme_source)
        self.assertIn("layout_scale=screen_scale", shell_theme_source)
        self.assertIn("def _apply_responsive_control_minimums(self) -> None:", source)
        self.assertIn('widget.setProperty("_cdmw_responsive_base_min_width", base_min_width)', source)
        self.assertIn("new_min_width = max(0, int(round(int(base_min_width) * scale)))", source)
        self.assertIn("widget.setMinimumWidth(new_min_width)", source)
        self.assertIn("use_fast_widths = bool(", source)
        self.assertIn('hasattr(self.archive_tree, "set_archive_state")', source)
        self.assertIn("content_width = 0 if use_fast_widths else self.archive_tree.sizeHintForColumn(column) + 28", source)
        self.assertIn("def _scale_density_metrics(metrics: Dict[str, int], scale: float) -> Dict[str, int]:", theme_source)
        self.assertIn("metrics = _scale_density_metrics(_density_metrics(density_key), layout_scale)", theme_source)

    def test_archive_status_panel_does_not_duplicate_preview_settings_line(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PREVIEW_SETTINGS.read_text(encoding="utf-8")
        )
        self.assertIn("self.archive_preview_settings_status_label.setVisible(False)", source)
        self.assertIn("# The same 3D preview state is already shown in Archive Preview diagnostics.", source)
        self.assertIn("label.clear()", source)
        self.assertNotIn("archive_status_group_layout.addWidget(self.archive_preview_settings_status_label)", source)

    def test_additional_qa_themes_are_available(self) -> None:
        source = THEMES.read_text(encoding="utf-8")
        for key, label in (
            ("midnight_ember", "Midnight Ember"),
            ("glacier", "Glacier"),
            ("black_gold", "Black Gold"),
            ("pine", "Pine"),
            ("violet_steel", "Violet Steel"),
        ):
            self.assertIn(f'"{key}"', source)
            self.assertIn(f'"label": "{label}"', source)
            self.assertIn('"preview_bg"', source)


if __name__ == "__main__":
    unittest.main()
