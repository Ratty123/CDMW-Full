from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell.app_startup import (
    ShellApplicationStartup,
    finish_gui_startup_smoke_if_requested,
    prepare_shell_application,
    prepare_shell_main_window,
    read_shell_startup_theme_key,
    run_shell_event_loop,
)
from cdmw.ui.themes import UI_THEME_SCHEMES


class _SettingsStub:
    def __init__(self, value: object) -> None:
        self._value = value

    def value(self, key: str, default: object = None) -> object:
        return self._value if key == "appearance/theme" else default


class _AppStub:
    def __init__(self, *, exit_code: int = 0) -> None:
        self.process_events_called = False
        self.exit_code = exit_code

    def windowIcon(self) -> QIcon:
        return QIcon()

    def processEvents(self) -> None:
        self.process_events_called = True

    def exec(self) -> int:
        return self.exit_code


class _WindowStub:
    def __init__(self) -> None:
        self._app_window_icon_filter: object | None = None
        self.attached_splash: object | None = None
        self.hold_main_window = False
        self.released = False
        self.finalized = False

    def setWindowIcon(self, icon: QIcon) -> None:
        return

    def attach_startup_splash(self, splash: object, *, hold_main_window: bool = False) -> None:
        self.attached_splash = splash
        self.hold_main_window = hold_main_window

    def _release_startup_splash(self) -> None:
        self.released = True

    def _finalize_close(self) -> None:
        self.finalized = True


class ShellAppStartupTests(unittest.TestCase):
    def test_read_shell_startup_theme_key_validates_saved_theme(self) -> None:
        theme_key = next(iter(UI_THEME_SCHEMES))

        self.assertEqual(theme_key, read_shell_startup_theme_key(_SettingsStub(theme_key)))  # type: ignore[arg-type]
        self.assertIn(read_shell_startup_theme_key(_SettingsStub("missing-theme")), UI_THEME_SCHEMES)  # type: ignore[arg-type]

    def test_prepare_shell_application_configures_qapplication(self) -> None:
        app = QApplication.instance() or QApplication([])

        startup = prepare_shell_application(app)

        self.assertIsInstance(startup, ShellApplicationStartup)
        self.assertIn(startup.theme_key, UI_THEME_SCHEMES)
        self.assertTrue(app.organizationName())
        self.assertTrue(app.applicationName())
        self.assertIsNotNone(startup.tree_column_width_filter)

    def test_prepare_shell_main_window_attaches_splash_and_records_event(self) -> None:
        window = _WindowStub()
        app = _AppStub()
        splash = object()
        icon_filter = object()
        events: list[str] = []

        with (
            patch("cdmw.ui.shell.app_startup.apply_window_ui_fonts") as apply_ui_fonts,
            patch("cdmw.ui.shell.app_startup.apply_window_data_fonts") as apply_fonts,
        ):
            prepare_shell_main_window(window, app, splash, icon_filter, events.append)  # type: ignore[arg-type]

        self.assertIs(window._app_window_icon_filter, icon_filter)
        self.assertEqual(["main_window_constructed"], events)
        self.assertIs(window.attached_splash, splash)
        self.assertTrue(window.hold_main_window)
        apply_ui_fonts.assert_called_once_with(window, app)
        apply_fonts.assert_called_once_with(window)

    def test_finish_gui_startup_smoke_only_when_requested(self) -> None:
        window = _WindowStub()
        app = _AppStub()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CDMW_GUI_STARTUP_SMOKE", None)
            self.assertFalse(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
            self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        self.assertTrue(window.released)
        self.assertTrue(app.process_events_called)
        self.assertTrue(window.finalized)

    def test_run_shell_event_loop_reports_nonzero_exit(self) -> None:
        reports: list[tuple[tuple[object, ...], dict[str, object]]] = []

        exit_code = run_shell_event_loop(
            _AppStub(exit_code=7),  # type: ignore[arg-type]
            lambda *args, **kwargs: reports.append((args, kwargs)),
        )

        self.assertEqual(7, exit_code)
        self.assertEqual("nonzero_gui_exit", reports[0][0][0])
        self.assertIn("Exit code: 7", reports[0][0][2])
        self.assertTrue(reports[0][1]["force"])

    def test_run_shell_event_loop_ignores_zero_exit(self) -> None:
        reports: list[tuple[tuple[object, ...], dict[str, object]]] = []

        exit_code = run_shell_event_loop(
            _AppStub(exit_code=0),  # type: ignore[arg-type]
            lambda *args, **kwargs: reports.append((args, kwargs)),
        )

        self.assertEqual(0, exit_code)
        self.assertEqual([], reports)


if __name__ == "__main__":
    unittest.main()
