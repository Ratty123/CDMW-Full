"""Shell QApplication startup preparation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QApplication

from cdmw.constants import APP_NAME, APP_ORGANIZATION, DEFAULT_UI_THEME
from cdmw.services.settings_service import create_settings
from cdmw.ui.app_icon import load_app_icon
from cdmw.ui.shell.icon_controller import AppWindowIconEventFilter
from cdmw.ui.shell.responsiveness_controller import AutoTreeColumnWidthEventFilter
from cdmw.ui.shell.theme_controller import apply_app_theme, apply_window_data_fonts, apply_window_ui_fonts
from cdmw.ui.themes import UI_THEME_SCHEMES
from cdmw.ui.widgets import ensure_app_wheel_guard


@dataclass(slots=True)
class ShellApplicationStartup:
    settings: QSettings
    theme_key: str
    app_window_icon_filter: Optional[AppWindowIconEventFilter]
    tree_column_width_filter: QObject


def read_shell_startup_theme_key(settings: QSettings) -> str:
    theme_key = str(settings.value("appearance/theme", DEFAULT_UI_THEME))
    return theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME


def prepare_shell_application(app: QApplication) -> ShellApplicationStartup:
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    ensure_app_wheel_guard(app)

    startup_settings = create_settings()
    startup_theme = read_shell_startup_theme_key(startup_settings)
    app_icon, _icon_path = load_app_icon(startup_theme)
    app_window_icon_filter: Optional[AppWindowIconEventFilter] = None
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
        app_window_icon_filter = AppWindowIconEventFilter(app_icon, app)
        app.installEventFilter(app_window_icon_filter)

    tree_column_width_filter = AutoTreeColumnWidthEventFilter(app)
    app.installEventFilter(tree_column_width_filter)
    apply_app_theme(app, startup_settings, startup_theme)
    return ShellApplicationStartup(
        settings=startup_settings,
        theme_key=startup_theme,
        app_window_icon_filter=app_window_icon_filter,
        tree_column_width_filter=tree_column_width_filter,
    )


def prepare_shell_main_window(
    window: object,
    app: QApplication,
    startup_splash: object,
    app_window_icon_filter: Optional[AppWindowIconEventFilter],
    record_runtime_event: Callable[[str], object],
) -> None:
    window._app_window_icon_filter = app_window_icon_filter
    record_runtime_event("main_window_constructed")
    if not app.windowIcon().isNull():
        window.setWindowIcon(app.windowIcon())
    apply_window_ui_fonts(window, app)
    apply_window_data_fonts(window)
    window.attach_startup_splash(startup_splash, hold_main_window=True)


def finish_gui_startup_smoke_if_requested(window: object, app: QApplication) -> bool:
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE") != "1":
        return False
    window._release_startup_splash()
    app.processEvents()
    window._finalize_close()
    return True


def run_shell_event_loop(app: QApplication, write_crash_report: Callable[..., object]) -> int:
    exit_code = int(app.exec())
    if exit_code != 0:
        write_crash_report(
            "nonzero_gui_exit",
            "Qt event loop returned a non-zero exit code",
            f"Exit code: {exit_code}",
            force=True,
        )
    return exit_code


__all__ = [
    "ShellApplicationStartup",
    "finish_gui_startup_smoke_if_requested",
    "prepare_shell_application",
    "prepare_shell_main_window",
    "read_shell_startup_theme_key",
    "run_shell_event_loop",
]
