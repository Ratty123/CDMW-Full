import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
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


def test_item_columns_sort_numerically_resize_and_preserve_selection_on_refresh(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, tmp_path, Backups(tmp_path))
    bridge = NewItemPresentationBridge(page)
    rows = [('installed', 'Zulu', 9, 'Installed'),
            ('reserved', 'Alpha', 100, 'Removed / reserved'),
            ('virtual', 'Bastion', 10, 'Virtual profile')]
    page.show()
    try:
        page._loaded(rows)
        def values(column):
            return [page.items.topLevelItem(i).text(column) for i in range(3)]

        assert values(0) == ['Alpha', 'Bastion', 'Zulu']
        for column, expected in ((0, ['Alpha', 'Bastion', 'Zulu']),
                                 (1, ['9', '10', '100']),
                                 (2, ['Installed', 'Removed / reserved', 'Virtual profile'])):
            _send(bridge, page.items, 'sort', {'column': column, 'descending': False})
            assert values(column) == expected
            _send(bridge, page.items, 'sort', {'column': column, 'descending': True})
            assert values(column) == expected[::-1]

        _send(bridge, page.items, 'select', {'path': [2], 'column': 0})
        assert page.remove_button.isEnabled()
        assert page.items.currentItem().data(0, Qt.UserRole) == 'installed'
        for column, width in enumerate((330, 180, 240)):
            _send(bridge, page.items, 'resize_column', {'column': column, 'width': width})
        page._loaded(rows[::-1])
        assert page.items.currentItem().data(0, Qt.UserRole) == 'installed'
        assert page.remove_button.isEnabled()
        assert values(2) == ['Virtual profile', 'Removed / reserved', 'Installed']
        assert [page.items.columnWidth(i) for i in range(3)] == [330, 180, 240]
        bridge.snapshot()
        props = bridge.document.registry.current[bridge.document.registry.identify(page.items)]['props']
        assert props['sortable']
        assert all(col['resizable'] and not col['stretch'] for col in props['columns'])
        _send(bridge, page.items, 'select', {'path': [1], 'column': 0})
        assert page.items.currentItem().data(0, Qt.UserRole) == 'reserved'
        assert page.remove_button.isEnabled() and not page.rebuild_button.isEnabled()
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


@pytest.mark.parametrize('disabled', [False, True])
def test_field_only_package_can_be_reviewed_rebuilt_and_removed_without_a_dummy_id(tmp_path, disabled):
    from tests.test_independent_item_fields import field_package
    from cdmw.services.independent_item_install import prepare_install, load_registry
    from cdmw.services.independent_item_package import package_bytes
    app = QApplication.instance() or QApplication([])
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    package = field_package(snapshot)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, root, backups)
    bridge = NewItemPresentationBridge(page)
    try:
        page.refresh()
        assert page.items.topLevelItem(0).text(1) == ''
        _send(bridge, page.items, 'select', {'path': [0], 'column': 0})
        assert page.rebuild_button.isEnabled() and page.remove_button.isEnabled()
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.rebuild_button, 'activate')
            assert load_registry(root)['items'][package.identity]['values'] == {}
            if disabled:
                from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
                layer = load_registry(root)['items'][package.identity]['layer']
                backups.apply(prepare_overlay_enabled(root, layer, False))
                page.refresh()
                assert page.remove_button.isEnabled() and not page.rebuild_button.isEnabled()
            _send(bridge, page.remove_button, 'activate')
        assert inventory(root)[0][3] == 'Removed / reserved'
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


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


@pytest.mark.parametrize('decision', ['delete', 'cancel', 'changed_root', 'close'])
def test_removed_identity_can_be_deleted_after_review_through_rust(tmp_path, decision):
    from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
    from cdmw.services.independent_item_package import package_bytes
    from tests.test_independent_item_regressions import files_in
    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    backups.apply(prepare_remove(package.identity, root))
    before = files_in(root)
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, root, backups)
    bridge = NewItemPresentationBridge(page)
    page.show()
    page.refresh()
    def review(box):
        assert package.title in box.text() and str(root) in box.detailedText()
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.No)
        if decision == 'changed_root':
            page.set_game_root(tmp_path / 'other-game')
        elif decision == 'close':
            page.request_shutdown()
        return QMessageBox.StandardButton.No if decision == 'cancel' else QMessageBox.StandardButton.Yes
    try:
        _send(bridge, page.items, 'select', {'path': [0], 'column': 0})
        assert page.remove_button.isEnabled() and not page.rebuild_button.isEnabled()
        with patch.object(QMessageBox, 'exec', review), \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.remove_button, 'activate')
        app.processEvents()
        if decision == 'delete':
            assert package.identity not in load_registry(root)['items']
            assert page.items.topLevelItemCount() == 0 and not page.remove_button.isEnabled()
            assert backups.count == 3
        else:
            assert files_in(root) == before and backups.count == 2
        assert page._queued is None
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_mod_management_reports_identity_deletion_without_an_installation_dialog(tmp_path):
    from types import SimpleNamespace
    from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
    from cdmw.services.independent_item_package import package_bytes
    from cdmw.ui.new_item.panels_output import install_result_report
    from cdmw.ui.tools.mod_management import ModManagementTab
    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    backups.apply(prepare_remove(package.identity, root))
    controller = NewItemStudioController(synchronous=True)
    window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: backups)))
    tab = ModManagementTab(window=window, controller=controller, get_package_root=lambda: str(root))
    page = tab.independent_page
    bridge = NewItemPresentationBridge(tab)
    results = []
    controller.install_finished.connect(results.append)
    try:
        tab.open_page('independent')
        _send(bridge, page.items, 'select', {'path': [0], 'column': 0})
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, 'information') as information, \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.remove_button, 'activate')
        information.assert_not_called()
        assert len(results) == 1 and package.identity not in load_registry(root)['items']
        assert str(results[0].backup_dir) in tab.log.toPlainText()
        title, message = install_result_report(results[0])
        assert title == 'Delete saved identity' and package.title in message
        assert str(results[0].backup_dir) in message
        assert page.items.topLevelItemCount() == 0
    finally:
        tab.request_shutdown()
        controller.shutdown()
        tab.close()


@pytest.mark.parametrize('decision', ['apply', 'cancel', 'changed_root'])
def test_rebuild_selected_item_uses_review_and_retains_ids_through_rust_bridge(tmp_path, decision):
    from cdmw.services.independent_item_install import load_registry, prepare_install
    from cdmw.services.independent_item_package import package_bytes
    from tests.test_independent_item_regressions import files_in

    app = QApplication.instance() or QApplication([])
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    prior = load_registry(root)['items'][package.identity]
    before = files_in(root)
    controller = NewItemStudioController(synchronous=True)
    page = IndependentItemsPage(controller, root, backups)
    bridge = NewItemPresentationBridge(page)
    page.show()
    page._loaded(inventory(root))
    page.items.setCurrentItem(page.items.topLevelItem(0))

    def review(_box):
        if decision == 'changed_root':
            page.set_game_root(tmp_path / 'other-game')
        return QMessageBox.StandardButton.No if decision == 'cancel' else QMessageBox.StandardButton.Yes

    try:
        assert page.rebuild_button.isEnabled()
        with patch.object(QMessageBox, 'exec', review), \
                patch('cdmw.services.new_item_service.game_is_running', return_value=False):
            _send(bridge, page.rebuild_button, 'activate')
        app.processEvents()
        current = load_registry(root)['items'][package.identity]
        if decision == 'apply':
            assert current['layer'] != prior['layer']
            assert current['values'] == prior['values'] and current['binding_hash'] == prior['binding_hash']
            assert backups.count == 2
        else:
            assert files_in(root) == before and backups.count == 1
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
    bridge = NewItemPresentationBridge(page.shared_page)
    page.show()
    page.shared_page.show()
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
