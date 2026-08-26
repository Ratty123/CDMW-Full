"""Shell QApplication startup preparation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QApplication

from cdmw.app.startup_smoke import gui_startup_smoke_requested, write_gui_startup_smoke_result
from cdmw.constants import APP_NAME, APP_ORGANIZATION, DEFAULT_UI_THEME
from cdmw.services.bundled_helper_availability import bundled_helper_resolution_snapshot
from cdmw.services.settings_service import create_settings
from cdmw.ui.app_icon import load_app_icon
from cdmw.ui.combo_popup_limiter import ensure_app_combo_popup_limiter
from cdmw.ui.shell.icon_controller import AppWindowIconEventFilter
from cdmw.ui.shell.compact.config import active_shell_theme_key
from cdmw.ui.shell.responsiveness_controller import AutoTreeColumnWidthEventFilter
from cdmw.ui.shell.theme_controller import apply_app_theme, apply_window_data_fonts, apply_window_ui_fonts
from cdmw.ui.themes import UI_THEME_SCHEMES
from cdmw.ui.wheel_guard import ensure_app_wheel_guard


@dataclass(slots=True)
class ShellApplicationStartup:
    settings: QSettings
    theme_key: str
    app_window_icon_filter: Optional[AppWindowIconEventFilter]
    tree_column_width_filter: QObject


def read_shell_startup_theme_key(settings: QSettings) -> str:
    theme_key = active_shell_theme_key(settings)
    return theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME


def prepare_shell_application(
    app: QApplication, *, settings_file_path: Path | None = None
) -> ShellApplicationStartup:
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    ensure_app_wheel_guard(app)
    ensure_app_combo_popup_limiter(app)

    startup_settings = (
        create_settings(settings_file_path=settings_file_path)
        if settings_file_path is not None
        else create_settings()
    )
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


def _verify_mesh_editor_startup_smoke_target(window: object, app: QApplication) -> None:
    from cdmw.ui.mesh_editor.startup_smoke import verify_mesh_editor_startup_smoke_target

    verify_mesh_editor_startup_smoke_target(window, app)


def _verify_mesh_builder_startup_smoke_target(window: object, app: QApplication) -> None:
    from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
        verify_mesh_builder_startup_smoke_target,
    )

    verify_mesh_builder_startup_smoke_target(window, app)


def _verify_mesh_archive_textures_startup_smoke_target(
    window: object,
    app: QApplication,
) -> dict[str, object]:
    from tools.mesh_harness.packaged_mesh_texture_smoke import (
        verify_packaged_mesh_texture_smoke_target,
    )

    return verify_packaged_mesh_texture_smoke_target(window, app)


def finish_gui_startup_smoke_if_requested(window: object, app: QApplication) -> bool:
    if not gui_startup_smoke_requested():
        return False
    target = os.environ.get("CDMW_GUI_STARTUP_SMOKE_TARGET", "").strip().lower()
    if target == "mesh_archive_textures":
        # A hidden Win32 top-level window never receives the first D3D11 paint,
        # which made the packaged texture gate test a permanently suppressed
        # swap chain rather than the executable users run. Keep the real window
        # lifecycle and dimensions, but place its surface outside the desktop.
        window.move(-32_000, -32_000)
    window._release_startup_splash()
    app.processEvents()
    if target == "mesh_archive_textures":
        # Explicitly establish the shown state after the splash releases.
        # The off-screen window remains a genuine shown HWND, so WinForms and
        # D3D11 receive the same show, embed, resize and paint messages as the
        # packaged GUI without appearing on the user's desktop.
        window.showNormal()
        window.move(-32_000, -32_000)
        app.processEvents()
    evidence: dict[str, object] | None = None
    try:
        if target == "mesh_editor":
            _verify_mesh_editor_startup_smoke_target(window, app)
        elif target == "mesh_builder":
            _verify_mesh_builder_startup_smoke_target(window, app)
        elif target == "mesh_archive_textures":
            evidence = _verify_mesh_archive_textures_startup_smoke_target(window, app)
        elif target:
            raise RuntimeError(f"Unknown GUI startup smoke target: {target}")
    except Exception as exc:
        # Startup-smoke failures are machine-readable test results, not GUI
        # crashes. Let the external verifier report the preserved diagnostic
        # path instead of making a frozen executable show PyInstaller's
        # unhandled-exception dialog over an unattended run.
        write_gui_startup_smoke_result(
            ok=False,
            stage="target_verification",
            target=target,
            detail=f"{type(exc).__name__}: {exc}",
            bundled_helpers=bundled_helper_resolution_snapshot(),
        )
        window._finalize_close()
        return True
    write_gui_startup_smoke_result(
        ok=True,
        stage="post_construction",
        target=target,
        bundled_helpers=bundled_helper_resolution_snapshot(),
        evidence=evidence,
    )
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
