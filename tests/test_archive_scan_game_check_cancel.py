"""The game version check is the first phase of an archive update: it shows as busy,
Refresh reads Cancel during it, and Cancel or closing the window stops it."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        settings = create_settings(settings_file_path=Path(temp_dir) / "cdmw-test.cfg")
        settings.setValue("ui/shell_variant", "legacy")
        context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                             event_bus=AppEventBus())
        shown = MainWindow(app_context=context)
        shown.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        shown.show()
        _APP.processEvents()
        shown.archive.archive_package_root_edit.setText(str(Path(temp_dir) / "game"))
        try:
            yield shown
        finally:
            shown._finalize_close()
            shown.deleteLater()
            _APP.processEvents()


def _start_held_refresh(window):
    """Refresh with the executable hash held: its task never runs."""

    archive = window.archive
    with patch("cdmw.ui.archive_browser.scan_lifecycle.QThreadPool") as pool:
        archive.scan_archives(force_refresh=True, activate_archive_tab=False)
    start = pool.globalInstance.return_value.start
    start.assert_called_once()
    return start.call_args.args[0]


def test_refresh_reads_cancel_while_the_game_version_is_checked(window):
    archive = window.archive
    task = _start_held_refresh(window)
    assert archive.archive_remote_query_pending
    assert archive.archive_game_fingerprint_task is task
    button = archive.archive_refresh_scan_button
    assert button.text() == "Cancel" and button.isEnabled()
    assert not archive.archive_scan_button.isEnabled()
    assert not archive.archive_package_root_edit.isEnabled()
    # The review bridge reads the same: busy, checking the game version, Cancel shown.
    from cdmw.automation import review_commands

    state = review_commands.job_state(window, {"job": "scan"})
    assert state["busy"] and state["checking_game_version"] and state["cancel_button"]["text"] == "Cancel"


def test_cancel_during_the_game_check_stops_it_and_restores_refresh(window):
    archive = window.archive
    task = _start_held_refresh(window)
    bridge = archive.archive_remote_bridge
    with patch.object(bridge, "open_archive") as open_archive:
        archive.archive_refresh_scan_button.click()
        assert task.stop_event.is_set()
        assert not archive.archive_remote_query_pending
        assert archive.archive_game_fingerprint_task is None
        assert archive.archive_refresh_scan_button.text() == "Refresh"
        assert archive.archive_scan_button.isEnabled()
        # A hash that finishes after the cancel opens nothing.
        task.signals.completed.emit(task.generation, ({}, (), False))
        _APP.processEvents()
        open_archive.assert_not_called()


def test_a_root_change_during_the_game_check_restores_refresh(window):
    archive = window.archive
    task = _start_held_refresh(window)
    archive.archive_package_root_edit.setText(str(Path(task.root).parent / "other"))
    assert task.stop_event.is_set()
    assert not archive.archive_remote_query_pending
    assert archive.archive_game_fingerprint_task is None
    assert archive.archive_refresh_scan_button.text() == "Refresh"


def test_closing_the_window_during_the_game_check_stops_it(window, tmp_path, monkeypatch):
    import cdmw.app.app_folder as app_folder
    from cdmw.automation import review_commands

    monkeypatch.setattr(app_folder, "cdmw_folder", lambda: tmp_path.resolve())
    log = review_commands._record_close_events(window, tmp_path / "close.jsonl")
    task = _start_held_refresh(window)
    window._finalize_close()
    assert task.stop_event.is_set()
    # The review's close hook sees the real window's close phases.
    assert "close_finalize" in log.read_text(encoding="utf-8")
