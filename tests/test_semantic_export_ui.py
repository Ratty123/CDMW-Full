"""Actual queued export/import and negotiated-format guidance on owned fixtures."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.services.independent_item_compatibility import scan_independent_conflicts
from cdmw.services.independent_item_install import load_registry, prepare_install
from cdmw.services.independent_item_package import package_bytes
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.independent_items_page import IndependentItemsPage
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_item_fields import field_package
from tests.test_independent_items import setup_game
from tests.test_mod_management import pump


def test_queued_semantic_export_and_reviewed_ui_import_use_real_reader(tmp_path):
    app = QApplication.instance() or QApplication([])
    _, snapshot, _ = setup_game(tmp_path / 'donor')
    setup_game(tmp_path / 'recipient')
    donor, recipient = tmp_path / 'donor/game', tmp_path / 'recipient/game'
    package = field_package(snapshot, value=1)
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], donor).preparation)
    controller = NewItemStudioController()
    page = IndependentItemsPage(controller, donor, backups)
    try:
        page._comparison = scan_independent_conflicts(donor)
        with patch('cdmw.ui.new_item.independent_items_page.QFileDialog.getExistingDirectory',
                   return_value=str(tmp_path)), \
             patch('cdmw.ui.new_item.independent_items_page.QInputDialog.getText',
                   return_value=('semantic-ui', True)):
            page._export_merge()
            pump(app, lambda: not controller.busy)
        exported = tmp_path / 'semantic-ui' / SEMANTIC_EXPORT_FILE
        bundle = read_semantic_export(exported)
        assert bundle is not None and len(bundle.packages) == 1
        assert 'Import cdmw-semantic.cditem through CDMW' in page.comparison.toPlainText()
        assert 'written' in page.status.text().lower()
        page.set_game_root(recipient)
        pump(app, lambda: not controller.busy)
        with patch('cdmw.ui.new_item.independent_items_page.QFileDialog.getOpenFileNames',
                   return_value=([str(exported)], '')), \
             patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
             patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            page._import()
            pump(app, lambda: not controller.busy and page._queued is None)
        assert package.identity in load_registry(recipient)['items']
        assert load_registry(recipient)['items'][package.identity]['values'] == {}
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()
