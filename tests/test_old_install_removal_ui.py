"""Remove What an Older CDMW Installed..., through the shell's own window (decision 42).

The window is built offscreen with a private profile; Browse Archives' game
folder points at an owned game made in the test. Only the question and the
result message are answered.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import dataclasses
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from cdmw.app.app_folder import SYSTEM_TEMP_ENV
from cdmw.app.events import AppEventBus
from cdmw.core import archive_patching
from cdmw.core.papgt_format import parse_papgt
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser import old_install_removal as action_module
from cdmw.ui.commands.registry import Command, command_registry
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tests.test_old_install_removal import _fingerprint, _game


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    monkeypatch.setattr(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", tmp_path / "backups")
    (tmp_path / "system-temp").mkdir()
    monkeypatch.setenv(SYSTEM_TEMP_ENV, str(tmp_path / "system-temp"))
    monkeypatch.setattr("cdmw.services.old_install_removal.default_running_check", lambda: "")
    settings = create_settings(settings_file_path=tmp_path / "removal.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    monkeypatch.setattr(window.archive, "scan_archives", lambda *args, **kwargs: None)
    yield window
    window._finalize_close()
    window.deleteLater()
    app.processEvents()


def _wait(app, condition, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def _point_browse_at(window, root) -> None:
    edit = window.archive.archive_package_root_edit
    edit.blockSignals(True)
    edit.setText(str(root))
    edit.blockSignals(False)


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_the_command_asks_with_the_full_list_and_removes_only_on_yes(app, window, tmp_path, monkeypatch, answer):
    root = _game(tmp_path, overlay=True, virtual=True)
    before = _fingerprint(root)
    _point_browse_at(window, root)
    asked, told = [], []
    monkeypatch.setattr(action_module.QMessageBox, "question", lambda *args, **kwargs: asked.append(args[2]) or answer)
    monkeypatch.setattr(action_module.QMessageBox, "information", lambda *args, **kwargs: told.append(args[2]))
    monkeypatch.setattr(action_module.QMessageBox, "warning", lambda *args, **kwargs: told.append(args[2]))
    registry = command_registry()
    assert registry.reason(action_module.REMOVE_COMMAND_ID) == ""
    registry.run(action_module.REMOVE_COMMAND_ID)
    _wait(app, lambda: bool(asked))
    question = asked[0]
    for expected in ("Folder 0036", "Mount list entry 0036", "bin64/CDMWVirtualLoader.asi", "Wolf's Fang",
                     "winmm.dll", "save backups", "Restore Backup..."):
        assert expected in question
    if answer == QMessageBox.StandardButton.Yes:
        _wait(app, lambda: bool(told))
        assert "Removed" in told[-1] and "Backup:" in told[-1]
        assert not (root / "0036").exists() and not (root / "bin64/CDMWVirtualLoader.asi").exists()
        assert [item.name for item in parse_papgt((root / "meta/0.papgt").read_bytes())] == ["0009"]
    else:
        for _ in range(30):
            app.processEvents()
            time.sleep(0.01)
        assert _fingerprint(root) == before


def test_a_clean_game_says_nothing_was_found(app, window, tmp_path, monkeypatch):
    root = _game(tmp_path)
    _point_browse_at(window, root)
    told, asked = [], []
    monkeypatch.setattr(action_module.QMessageBox, "information", lambda *args, **kwargs: told.append(args[2]))
    monkeypatch.setattr(action_module.QMessageBox, "question", lambda *args, **kwargs: asked.append(args))
    command_registry().run(action_module.REMOVE_COMMAND_ID)
    _wait(app, lambda: bool(told))
    assert told[0].startswith("Nothing an older CDMW installed was found") and not asked


def test_without_a_game_folder_the_command_says_why(app, window):
    _point_browse_at(window, "")
    assert command_registry().reason(action_module.REMOVE_COMMAND_ID) == action_module.REASON_NO_GAME


def test_both_game_folder_routes_are_user_only_commands(app, window):
    registry = command_registry()
    for command_id in (action_module.REMOVE_COMMAND_ID, action_module.RESTORE_COMMAND_ID):
        command = registry.get(command_id)
        if "user_only" in {item.name for item in dataclasses.fields(Command)}:
            # Fails once the MCP branch's flag exists and a command lacks it.
            assert command.user_only is True, command_id
    assert registry.get(action_module.RESTORE_COMMAND_ID).label == "Restore Backup..."


def test_the_button_beside_restore_backup_runs_the_action_when_the_layout_has_it(app):
    started = []
    button = QPushButton()
    browser = SimpleNamespace(archive_remove_old_install_button=button, archive_package_root_edit=None, shell=None)
    action_module.install_old_install_removal(browser)
    browser.old_install_removal.start = lambda: started.append(True)
    # The connection was made to the bound method at install time; press it.
    button.clicked.disconnect()
    button.clicked.connect(browser.old_install_removal.start)
    button.click()
    assert started and button.text() == action_module.LABEL
    button.deleteLater()
