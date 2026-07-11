from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_clean_import(script: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_shell_startup_does_not_import_broad_widget_or_preview_stacks() -> None:
    _run_clean_import(
        "import sys; import cdmw.ui.shell.app_startup; "
        "forbidden = ('cdmw.ui.widgets', 'cdmw.ui.native_preview', "
        "'cdmw.rendering.model_preview', 'cdmw.services.preview_rendering'); "
        "assert not [name for name in sys.modules if name.startswith(forbidden)]"
    )


def test_wheel_guard_facade_exports_are_cached_and_keep_owner_identity() -> None:
    _run_clean_import(
        "import sys; import cdmw.ui.widgets as facade; "
        "assert 'cdmw.ui.wheel_guard' not in sys.modules; "
        "from cdmw.ui.widgets import NonIntrusiveWheelGuard, ensure_app_wheel_guard; "
        "import cdmw.ui.wheel_guard as owner; "
        "assert NonIntrusiveWheelGuard is owner.NonIntrusiveWheelGuard; "
        "assert ensure_app_wheel_guard is owner.ensure_app_wheel_guard; "
        "assert facade.__dict__['NonIntrusiveWheelGuard'] is owner.NonIntrusiveWheelGuard; "
        "assert facade.__dict__['ensure_app_wheel_guard'] is owner.ensure_app_wheel_guard"
    )
    _run_clean_import(
        "import cdmw.ui.wheel_guard as owner; import cdmw.ui.widgets as facade; "
        "assert facade.NonIntrusiveWheelGuard is owner.NonIntrusiveWheelGuard; "
        "assert facade.ensure_app_wheel_guard is owner.ensure_app_wheel_guard"
    )


def test_wheel_guard_consumes_wheel_events_for_value_controls() -> None:
    _run_clean_import(
        "import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
        "from PySide6.QtCore import QEvent; from PySide6.QtWidgets import QApplication, QComboBox; "
        "from cdmw.ui.wheel_guard import NonIntrusiveWheelGuard; "
        "app = QApplication.instance() or QApplication([]); combo = QComboBox(); "
        "event = type('Event', (), {'type': lambda self: QEvent.Type.Wheel, "
        "'ignore': lambda self: setattr(self, 'ignored', True), 'ignored': False})(); "
        "assert NonIntrusiveWheelGuard(app).eventFilter(combo, event); assert event.ignored"
    )


def test_shell_startup_uses_explicit_settings_path() -> None:
    _run_clean_import(
        "import os, tempfile; from pathlib import Path; from unittest.mock import patch; "
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
        "from PySide6.QtWidgets import QApplication; "
        "from cdmw.services.settings_service import create_settings; "
        "from cdmw.ui.shell.app_startup import prepare_shell_application; "
        "app = QApplication.instance() or QApplication([]); "
        "temp = tempfile.TemporaryDirectory(); path = Path(temp.name) / 'settings.ini'; "
        "scope = patch('cdmw.ui.shell.app_startup.create_settings', wraps=create_settings); "
        "mock = scope.start(); startup = prepare_shell_application(app, settings_file_path=path); "
        "scope.stop(); mock.assert_called_once_with(settings_file_path=path); "
        "assert Path(startup.settings.fileName()) == path"
    )
