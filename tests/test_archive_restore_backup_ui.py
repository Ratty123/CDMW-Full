"""Restore Backup..., the one game write left in the interface, through the real Browse Archives button.

The shell's own MainWindow is built offscreen with a private profile. The game is an
owned archive written into the test's folder, and its backup is made by the same
service an older CDMW used. Only the folder dialog and the question are answered.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.app.app_folder import SYSTEM_TEMP_ENV
from cdmw.app.events import AppEventBus
from cdmw.core import archive_patching
from cdmw.services.archive_mutation_service import ArchiveMutationService
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser import patch_actions
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tests.test_archive_patch_preflight import _write_test_archive


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    monkeypatch.setattr(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", tmp_path / "backups")
    # Where an older CDMW kept its backups; never the machine's own temp folder here.
    (tmp_path / "system-temp").mkdir()
    monkeypatch.setenv(SYSTEM_TEMP_ENV, str(tmp_path / "system-temp"))
    settings = create_settings(settings_file_path=tmp_path / "restore.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    monkeypatch.setattr(window.archive, "scan_archives", lambda *args, **kwargs: None)
    monkeypatch.setattr(patch_actions.QMessageBox, "information", lambda *args, **kwargs: None)
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


def _older_cdmw_backup(tmp_path):
    entry = _write_test_archive(tmp_path / "game")
    files = (tmp_path / "game" / "meta" / "0.papgt", entry.pamt_path, entry.paz_file)
    originals = {path: path.read_bytes() for path in files}
    backup_dir = ArchiveMutationService().backup_files(files, description="Made by an older CDMW")
    entry.paz_file.write_bytes(b"what an older CDMW patched in")
    return entry, originals, backup_dir


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_restore_backup_asks_and_puts_back_what_an_older_cdmw_changed(app, window, tmp_path, monkeypatch, answer):
    entry, originals, backup_dir = _older_cdmw_backup(tmp_path)
    asked = []
    monkeypatch.setattr(patch_actions.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(backup_dir))
    monkeypatch.setattr(patch_actions.QMessageBox, "question",
                        lambda *args, **kwargs: asked.append(args[2]) or answer)
    window.archive.archive_package_root_edit.setText(str(tmp_path / "game"))
    button = window.archive.archive_restore_patch_backup_button
    assert button.text() == "Restore Backup..."
    button.click()
    app.processEvents()
    assert asked and str(backup_dir) in asked[0]
    if answer == QMessageBox.StandardButton.Yes:
        _wait(app, lambda: entry.paz_file.read_bytes() == originals[entry.paz_file])
        assert {path: path.read_bytes() for path in originals} == originals
    else:
        for _ in range(20):
            app.processEvents()
            time.sleep(0.01)
        assert entry.paz_file.read_bytes() == b"what an older CDMW patched in"


def test_restore_backup_refuses_a_backup_made_for_another_game_folder(app, window, tmp_path, monkeypatch):
    """Decision 41: with CDMW pointed at another game folder, nothing is asked or written."""
    entry, originals, backup_dir = _older_cdmw_backup(tmp_path)
    (tmp_path / "other-game").mkdir()
    window.archive.archive_package_root_edit.setText(str(tmp_path / "other-game"))
    warned, asked = [], []
    monkeypatch.setattr(patch_actions.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(backup_dir))
    monkeypatch.setattr(patch_actions.QMessageBox, "question", lambda *args, **kwargs: asked.append(args) or None)
    monkeypatch.setattr(patch_actions.QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2]))
    window.archive.archive_restore_patch_backup_button.click()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    assert not asked
    assert warned and "game folder the backup was made for" in warned[0]
    assert str(tmp_path / "game") in warned[0]
    assert entry.paz_file.read_bytes() == b"what an older CDMW patched in"
