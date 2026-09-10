"""Real headless dialog wiring, cancellation, and stale-result rejection."""
import threading
import time
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication
import pytest

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog
from tests.test_mod_update import exported
from tests.test_mod_merge_dialog import drain


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_dialog_compares_and_writes_separate_package(app, tmp_path):
    _plan, _snapshot, _entries, folder = exported(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    dialog = ModUpdateDialog(controller, tmp_path / "game")
    try:
        dialog.folder.setText(str(folder))
        dialog.destination.setText(str(tmp_path / "updated"))
        dialog.scan_button.click()
        assert dialog._plan is not None, dialog.status.text()
        assert dialog.export_button.isEnabled(), dialog.review.toPlainText()
        assert "2.00.00" in dialog.review.toPlainText()
        dialog.export_button.click()
        assert (tmp_path / "updated/manifest.json").is_file(), dialog.status.text()
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        controller.deleteLater()


def test_close_cancels_without_waiting_and_drops_late_results(app, tmp_path, monkeypatch):
    from cdmw.ui.new_item import mod_update_dialog
    from cdmw.domain.cancellation import raise_if_cancelled
    started, cancelled = threading.Event(), threading.Event()
    def factory(*args, **kwargs):
        def task(log, stop):
            started.set()
            stop.wait(3)
            if stop.is_set():
                cancelled.set()
            raise_if_cancelled(stop)
        return task
    monkeypatch.setattr(mod_update_dialog, "mod_update_scan_task", factory)
    controller = NewItemStudioController()
    dialog = ModUpdateDialog(controller, tmp_path / "game")
    dialog.folder.setText(str(tmp_path / "mod"))
    dialog.scan_button.click()
    try:
        drain(app, started.is_set)
        start = time.monotonic()
        dialog.reject()
        assert time.monotonic() - start < 0.2
        drain(app, lambda: not controller.busy)
        assert cancelled.is_set()
    finally:
        controller.cancel_operation("mod_update")
        drain(app, lambda: not controller.busy)
        controller.deleteLater()


def test_selection_change_rejects_pending_comparison(app, tmp_path):
    controller = NewItemStudioController(synchronous=True)
    pending = []
    controller._run = lambda lane, task, done, failed: pending.append(done) or True
    dialog = ModUpdateDialog(controller, tmp_path / "game")
    try:
        dialog.folder.setText(str(tmp_path / "first"))
        dialog.scan_button.click()
        dialog.folder.setText(str(tmp_path / "second"))
        pending[0](SimpleNamespace(can_update=True))
        assert dialog._plan is None and not dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        controller.deleteLater()


@pytest.mark.parametrize("loaded", (False, True))
def test_update_opens_before_reading_archives_and_from_tools_without_a_draft(app, tmp_path, monkeypatch, loaded):
    from PySide6.QtCore import QCoreApplication, QEvent
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.ui.new_item.tab import NewItemStudioTab
    from tests.test_new_item_provenance import setup_game
    _service, _snapshot, entries = setup_game(tmp_path)
    monkeypatch.setattr(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None)
    controller = NewItemStudioController(synchronous=True)
    tab = NewItemStudioTab(controller=controller, get_package_root=lambda: str(tmp_path / "game"),
                           get_archive_entries=lambda: entries)
    try:
        if loaded:
            tab.start_snapshot()
            action = next(action for action in tab.output_panel.tools_menu.actions()
                          if action.text() == "Check mods for game updates...")
            assert action.isEnabled() and controller.plan is None
            action.trigger()
        else:
            assert controller.snapshot is None and controller.plan is None
            tab._update_button.click()
        dialog = tab.findChild(ModUpdateDialog)
        assert dialog is not None and dialog.game_root.text() == str(tmp_path / "game")
        assert dialog.source_kind.currentData() is False
        assert not dialog.export_button.isEnabled()
        dialog.reject()
    finally:
        tab.close()
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_overlay_list_shows_build_status_and_opens_installed_update(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from cdmw.services.archive_overlay_manager import InstalledOverlay
    from cdmw.ui.new_item import overlay_manager_dialog
    entry = InstalledOverlay("a", "Old overlay", (123,), "0036", 5, 0, game_build="2.00.00",
                             compatibility_status="changed")
    monkeypatch.setattr(overlay_manager_dialog, "list_installed_overlays", lambda *_args, **_kwargs: (entry,))
    controller = NewItemStudioController(synchronous=True)
    dialog = overlay_manager_dialog.OverlayManagerDialog(controller, str(tmp_path / "game"), None)
    try:
        dialog.refresh()
        assert dialog.table.item(0, 5).text() == "2.00.00"
        assert dialog.table.item(0, 6).text() == "Needs comparison"
        assert "Check game updates" in dialog.details.text()
        dialog.update_button.click()
        update = dialog.findChild(ModUpdateDialog)
        assert update is not None and update.source_kind.currentData() is True
        assert not update.folder.isEnabled()
        update.reject()
    finally:
        dialog.reject()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
