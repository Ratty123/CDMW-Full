import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.domain.new_item.independent import IndependentItemInstallPlan
from cdmw.services.independent_item_package import write_package
from cdmw.services.independent_item_install import inventory
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.independent_items_page import IndependentItemsPage
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from tests.test_independent_items import authored, setup_game
from tests.test_archive_overlay_manager import Backups
from tests.test_mod_management import pump
from tests.test_new_item_rust_ui import _send


def test_reviewed_import_and_removal_use_shared_transaction_via_rust(tmp_path):
    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    target = tmp_path / 'item.cditem'
    write_package(package, target)
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, root, Backups(tmp_path))
    bridge = NewItemPresentationBridge(page)
    page.show()
    app.processEvents()
    try:
        with patch('cdmw.ui.new_item.independent_items_page.QFileDialog.getOpenFileNames', return_value=([str(target)], '')), \
                patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.import_button, 'activate')
            assert len(inventory(root)) == 1
            assert page.items.topLevelItemCount() == 1
            page.items.setCurrentItem(page.items.topLevelItem(0))
            _send(bridge, page.remove_button, 'activate')
        assert inventory(root)[0][3] == 'Removed / reserved'
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_close_discards_prepared_install_and_never_queues_apply(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = IndependentItemsPage(controller, tmp_path, Backups(tmp_path))
    entered, release = threading.Event(), threading.Event()
    delivered = []
    def task(log, stop):
        entered.set()
        assert release.wait(5)
        return IndependentItemInstallPlan(None, (), ())
    try:
        assert page._run(task, delivered.append)
        pump(app, entered.is_set)
        page.request_shutdown()
        release.set()
        pump(app, lambda: not controller.busy)
        assert not delivered and page._queued is None
    finally:
        release.set()
        controller.shutdown()
        page.close()


def test_changing_game_folder_during_review_discards_the_old_install(tmp_path):
    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    target = tmp_path / 'item.cditem'
    write_package(package, target)
    controller = NewItemStudioController(synchronous=True)
    backups = Backups(tmp_path)
    page = IndependentItemsPage(controller, root, backups)
    def changed_root(_box):
        page.set_game_root(tmp_path / 'different-game')
        return QMessageBox.StandardButton.Yes
    try:
        with patch('cdmw.ui.new_item.independent_items_page.QFileDialog.getOpenFileNames', return_value=([str(target)], '')), \
                patch.object(QMessageBox, 'exec', changed_root):
            page._import()
        app.processEvents()
        assert backups.count == 0 and page._queued is None and not inventory(root)
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()
