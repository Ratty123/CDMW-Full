"""Clear Workflow Roots clears on the background runner, not the interface thread."""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell import workspace_controller
from cdmw.ui.shell.app_context import AppContext


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "clear.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    monkeypatch.setattr(window.archive, "scan_archives", lambda *args, **kwargs: None)
    yield window
    window._finalize_close()
    window.deleteLater()
    app.processEvents()


class _ConfirmingBox:
    """The confirmation box, answered with its first button (Clear Folders)."""

    Warning = QMessageBox.Warning
    AcceptRole = QMessageBox.AcceptRole
    Cancel = QMessageBox.Cancel

    def __init__(self, *_args):
        self.buttons = []

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None

    def addButton(self, *args):
        self.buttons.append(args)
        return len(self.buttons)

    def clickedButton(self):
        return 1


def _wait(app, condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def _filled(folder):
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "a.png").write_bytes(b"png")
    (folder / "b.dds").write_bytes(b"dds")
    return folder


def test_clear_workflow_roots_clears_off_the_interface_thread(app, window, tmp_path, monkeypatch):
    output, staging = _filled(tmp_path / "output"), _filled(tmp_path / "staging")
    window.textures.output_root_edit.setText(str(output))
    window.textures.png_root_edit.setText(str(staging))
    for edit in (window.textures.original_dds_edit, window.textures.dds_staging_root_edit,
                 window.textures.texture_editor_png_root_edit):
        edit.setText("")
    monkeypatch.setattr(workspace_controller, "QMessageBox", _ConfirmingBox)
    real_clear = workspace_controller.clear_directory_contents
    threads = []

    def clear(path):
        threads.append(threading.current_thread())
        return real_clear(path)

    monkeypatch.setattr(workspace_controller, "clear_directory_contents", clear)
    statuses = []
    real_status = window.set_status_message
    monkeypatch.setattr(window, "set_status_message",
                        lambda message, *args, **kwargs: (statuses.append(message), real_status(message, *args, **kwargs)))
    window.clear_workflow_roots()
    assert window.worker_thread is not None, "the clear did not go to the background runner"
    _wait(app, lambda: window.worker_thread is None and len(threads) == 2)
    assert all(thread is not threading.main_thread() for thread in threads)
    assert not any(output.iterdir()) and not any(staging.iterdir())
    _wait(app, lambda: "Cleared 2 configured workflow folder(s)." in statuses)


def _game_library(tmp_path):
    game = tmp_path / "library" / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"papgt")
    (game / "bin64").mkdir()
    (game / "bin64" / "CrimsonDesert.exe").write_bytes(b"MZ")
    return game


def _statuses(window, monkeypatch):
    statuses = []
    real_status = window.set_status_message
    monkeypatch.setattr(window, "set_status_message",
                        lambda message, *args, **kwargs: (statuses.append(message), real_status(message, *args, **kwargs)))
    return statuses


def test_a_refused_folder_is_reported_and_its_files_stay(app, window, tmp_path, monkeypatch):
    game = _game_library(tmp_path)
    window.textures.output_root_edit.setText(str(game.parent))
    for edit in (window.textures.original_dds_edit, window.textures.dds_staging_root_edit,
                 window.textures.png_root_edit, window.textures.texture_editor_png_root_edit):
        edit.setText("")
    monkeypatch.setattr(workspace_controller, "QMessageBox", _ConfirmingBox)
    statuses = _statuses(window, monkeypatch)
    window.clear_workflow_roots()
    _wait(app, lambda: window.worker_thread is None and any("was not cleared" in s for s in statuses))
    refusal = next(s for s in statuses if "was not cleared" in s)
    assert "holds a game installation" in refusal and "Already cleared" not in refusal
    assert (game / "bin64" / "CrimsonDesert.exe").is_file()
    assert not window._workflow_clear_active


def test_a_later_refusal_names_the_folders_already_cleared(app, window, tmp_path, monkeypatch):
    """Review of rr/parity-mods-3: the status names what was cleared before the refusal."""

    output, game = _filled(tmp_path / "output"), _game_library(tmp_path)
    window.textures.output_root_edit.setText(str(output))  # "Rebuilt textures", cleared first
    window.textures.png_root_edit.setText(str(game.parent))  # "Upscaled PNG staging", refused
    for edit in (window.textures.original_dds_edit, window.textures.dds_staging_root_edit,
                 window.textures.texture_editor_png_root_edit):
        edit.setText("")
    monkeypatch.setattr(workspace_controller, "QMessageBox", _ConfirmingBox)
    statuses = _statuses(window, monkeypatch)
    window.clear_workflow_roots()
    _wait(app, lambda: window.worker_thread is None and any("was not cleared" in s for s in statuses))
    refusal = next(s for s in statuses if "was not cleared" in s)
    assert refusal.startswith("Upscaled PNG staging was not cleared"), refusal
    assert "Already cleared: Rebuilt textures." in refusal
    assert not any(output.iterdir()) and (game / "bin64" / "CrimsonDesert.exe").is_file()


def test_the_clear_and_an_archive_export_wait_for_each_other(app, window, tmp_path, monkeypatch):
    """Review of rr/parity-mods-3: Browse's archive export runs in its own process and can
    write into the Original DDS root, and the clear runs in the background now."""

    from types import SimpleNamespace

    output = _filled(tmp_path / "output")
    window.textures.output_root_edit.setText(str(output))
    monkeypatch.setattr(workspace_controller, "QMessageBox", _ConfirmingBox)
    statuses = _statuses(window, monkeypatch)
    window.archive._archive_remote_export_request_id = "export-1"
    try:
        window.clear_workflow_roots()
    finally:
        window.archive._archive_remote_export_request_id = None
    assert window.worker_thread is None and any(output.iterdir())
    assert any("archive export is still writing" in s for s in statuses)
    # The other way: an export started while the clear runs is refused.
    monkeypatch.setattr(window.archive, "archive_remote_bridge", SimpleNamespace(current_session=object()),
                        raising=False)
    monkeypatch.setattr(window.archive, "archive_remote_actions_safe", True, raising=False)
    monkeypatch.setattr(window.archive, "_ensure_remote_archive_export_wiring", lambda: None)
    window._workflow_clear_active = True
    try:
        window.archive._run_remote_archive_export(SimpleNamespace(requested_count=1), description="DDS")
    finally:
        window._workflow_clear_active = False
    assert any("Workflow folders are being cleared" in s for s in statuses)
