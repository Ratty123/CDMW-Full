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


def test_conflict_scan_and_reviewed_merge_are_accessible_through_rust_bridge(tmp_path):
    from tests.test_independent_item_compatibility import mount_mod, table_change
    from cdmw.services.independent_item_install import prepare_install
    from cdmw.services.independent_item_package import package_bytes
    from tests.test_archive_overlay_manager import snapshot_of
    from tests.test_new_item_service import OTHER
    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    mount_mod(root, tmp_path / 'foreign', table_change(stock), first=True)
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, root, backups)
    bridge = NewItemPresentationBridge(page)
    page.show()
    app.processEvents()
    try:
        _send(bridge, page.scan_button, 'activate')
        assert page._comparison.compatible and 'foreign' in page.comparison.toPlainText()
        assert page.compose_button.isEnabled()
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.compose_button, 'activate')
        assert snapshot_of(root).rows[OTHER].max_stack_count == stock.rows[OTHER].max_stack_count + 1
        page.set_game_root(tmp_path / 'another-game')
        assert not page.compose_button.isEnabled() and not page.comparison.toPlainText()
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_stale_background_comparison_cannot_enable_merge_for_new_root(tmp_path):
    from cdmw.services.independent_item_compatibility import IndependentCompatibilityReport
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = IndependentItemsPage(controller, tmp_path, Backups(tmp_path))
    entered, release = threading.Event(), threading.Event()
    stops = []
    def scan(root, **kwargs):
        stops.append(kwargs['stop_event'])
        entered.set()
        assert release.wait(5)
        return IndependentCompatibilityReport(tmp_path, ())
    try:
        with patch('cdmw.services.independent_item_compatibility.scan_independent_conflicts', scan):
            page._scan()
            pump(app, entered.is_set)
            page.set_game_root(tmp_path / 'changed')
            assert stops[0].is_set()
            release.set()
            pump(app, lambda: not controller.busy)
        assert page._comparison is None and not page.compose_button.isEnabled()
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_comparison_report_translates_without_changing_mod_or_resource_names(tmp_path):
    from cdmw.services.independent_item_compatibility import CompatibilityFinding, IndependentCompatibilityReport
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, tmp_path, Backups(tmp_path))
    path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    detail = 'CDMW can preserve the external data and add the installed items in one shared output.'
    source = IndependentCompatibilityReport(tmp_path, (
        CompatibilityFinding('Merge available', ('Save',), path, detail),)).text()
    localizer = UiLocalizer(language_dir=tmp_path / 'languages', language_code='de')
    try:
        page._comparison_writer.set_text(source)
        localizer.activate_runtime_tracking(page, application=app)
        localizer.apply(page)
        translated = page.comparison.toPlainText()
        assert detail not in translated and 'Merge available' not in translated
        assert path in translated and 'Save' in translated
        assert 'This compares file data' not in translated
        assert page.scan_button.text() != 'Scan installed mods'
        localizer.load_language('en')
        localizer.apply_registered_roots()
        assert page.comparison.toPlainText() == source
    finally:
        localizer.shutdown()
        page.request_shutdown()
        controller.shutdown()
        page.close()
