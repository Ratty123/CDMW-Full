"""The combined list preserves each route's actual install/launch authority."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.archive_overlay_manager import list_installed_overlays
from cdmw.services.independent_item_install import prepare_install, load_registry, inventory
from cdmw.services.mod_management_inventory import mod_sources, launch_installed_game
from cdmw.services.overlay_inventory_details import MountedArchive
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.test_archive_overlay_manager import Backups
from tests.test_mod_management import pump
from tests.test_new_item_rust_ui import _send
from tests.test_virtual_loader import packages, game_bytes


def rows(page):
    return {page.selection.topLevelItem(i).data(0, Qt.UserRole): page.selection.topLevelItem(i)
            for i in range(page.selection.topLevelItemCount())}


def load_installed(tab, root):
    tab.inventory._loaded(list_installed_overlays(root))
    page = tab.virtual_page
    page._source_lane.cancel()
    page._sources = mod_sources(root)
    page.refresh()
    pump(QApplication.instance(), lambda: page._status_current and not page._status_reading)
    page._buttons()
    return page


def test_one_list_labels_routes_without_duplicate_owned_archive_and_keeps_draft_order(tmp_path):
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 3)
    Backups(tmp_path).apply(prepare_install(files[:1], root).preparation)
    before = game_bytes(root)
    tab = ModManagementTab(get_package_root=lambda: str(root))
    try:
        assert [tab.pages.tabText(i) for i in range(tab.pages.count())] == ['Mods', 'Advanced']
        assert tab._current_page() is tab.virtual_page
        page = load_installed(tab, root)
        identities, mounts, can_launch = page._sources
        page._sources = identities, (*mounts, MountedArchive('external', False, True, False)), can_launch
        page._append_selection('item', files[1:])
        snapshot = rows(page)
        assert len(snapshot) == 4  # One installed item, two drafts, one external folder.
        installed = next(item for key, item in snapshot.items() if key[0] == 'installed')
        assert [installed.text(i) for i in range(1, 3)] == ['Item package', 'Game']
        assert installed.text(3).startswith('Enabled')
        assert snapshot[('external', 'external')].text(2) == 'External manager'
        assert all(item.text(3) == 'Pending changes' for key, item in snapshot.items() if key[0] == 'item')
        profile = page._profile()
        page.selection.sortItems(0, Qt.DescendingOrder)
        page.selection.sortItems(2, Qt.AscendingOrder)
        assert page._profile() == profile == VirtualProfile(files[1:])
        page.selection.setCurrentItem(installed)
        page._render_sources()
        assert rows(page)[installed.data(0, Qt.UserRole)] is installed
        assert installed.isSelected()
        bridge = NewItemPresentationBridge(tab)
        assert not bridge.snapshot()['unsupported']
        _send(bridge, page.search, 'text', 'external')
        assert not installed.isSelected() and installed.isHidden()
        assert page._profile() == profile and game_bytes(root) == before
    finally:
        tab.shutdown()
        tab.close()


def test_details_open_from_main_list_and_return_without_losing_selection(tmp_path, monkeypatch):
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ItemPreviewFrame, '_start_package', lambda *_args, **_kwargs: None)
    root, files = packages(tmp_path, 1)
    Backups(tmp_path).apply(prepare_install(files, root).preparation)
    tab = ModManagementTab(get_package_root=lambda: str(root))
    bridge = NewItemPresentationBridge(tab)
    try:
        page = load_installed(tab, root)
        item = next(item for key, item in rows(page).items() if key[0] == 'installed')
        page.selection.setCurrentItem(item)
        page.search.setText(item.text(0))
        _send(bridge, page.details_button, 'activate')
        assert tab.pages.currentWidget() is tab.mods_pages
        assert tab._current_page() is tab.inventory
        assert tab.inventory._selected_entry().id == item.data(0, Qt.UserRole)[1]
        state = bridge.snapshot()
        assert not state['unsupported']
        def identifiers(node):
            yield node.get('id')
            for child in node['children']:
                yield from identifiers(child)
        projected = set(identifiers(state['root']))
        assert bridge.document.registry.identify(tab.inventory.inspector) in projected
        assert bridge.document.registry.identify(tab.inventory.table) not in projected
        assert bridge.document.registry.identify(tab.inventory.search) not in projected
        _send(bridge, tab.back_to_mods, 'activate')
        assert tab._current_page() is page
        assert page.search.text() == item.text(0) and item.isSelected()
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        bridge.close()
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_item_removal_from_combined_list_uses_review_backup_and_retains_identity(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 2)
    (tmp_path / 'backups').mkdir()
    backups = Backups(tmp_path / 'backups')
    backups.apply(prepare_install(files, root).preparation)
    registry = load_registry(root)
    owned_before = {p: p.read_bytes() for p in (root / '0009').glob('*') if p.is_file()}
    window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: backups)))
    tab = ModManagementTab(window=window, get_package_root=lambda: str(root))
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    reviews = []
    def review(box):
        reviews.append(box.detailedText())
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'exec', review)
    monkeypatch.setattr(QMessageBox, 'information', lambda *_: None)
    try:
        page = load_installed(tab, root)
        item = next(item for key, item in rows(page).items() if key[0] == 'installed')
        removed_layer = item.data(0, Qt.UserRole)[1]
        identity = page._sources[0][removed_layer][0]
        page.selection.setCurrentItem(item)
        assert page.remove_selected.isEnabled()
        _send(NewItemPresentationBridge(tab), page.remove_selected, 'activate')
        pump(app, lambda: bool(reviews) and not tab.controller.busy and tab.independent_page._queued is None)
        assert str(root) in reviews[0] and 'Files to update:' in reviews[0]
        assert len(list_installed_overlays(root)) == 1 and backups.count == 2
        kept = load_registry(root)["items"][identity]
        assert kept['values'] == registry['items'][identity]['values']
        assert next(row[3] for row in inventory(root) if row[0] == identity) == 'Removed / reserved'
        assert all(path.read_bytes() == data for path, data in owned_before.items())
    finally:
        tab.shutdown()
        tab.close()


def test_external_and_mixed_selection_cannot_remove_an_install(tmp_path):
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 1)
    tab = ModManagementTab(get_package_root=lambda: str(root))
    try:
        page = tab.virtual_page
        page._sources = ({}, (MountedArchive('foreign', False, True, False),), False)
        page._append_selection('item', files)
        values = rows(page)
        external = values[('external', 'foreign')]
        page.selection.setCurrentItem(external)
        values[('item', str(files[0]))].setSelected(True)
        assert not page.remove_selected.isEnabled() and not page.toggle_installed.isEnabled()
        page._remove()
        assert len(rows(page)) == 2
    finally:
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize('change', ['root', 'close'])
def test_combined_inventory_cancels_and_discards_stale_reads(tmp_path, monkeypatch, change):
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    page = tab.virtual_page
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    def read(root, *, stop_event):
        entered.set()
        assert release.wait(5)
        if stop_event.is_set():
            cancelled.set()
        return {}, (MountedArchive('stale', False, True, False),), False
    monkeypatch.setattr('cdmw.services.mod_management_inventory.mod_sources', read)
    try:
        page.refresh_sources()
        pump(app, entered.is_set)
        if change == 'root':
            page.set_game_root(tmp_path / 'different')
        else:
            page.request_shutdown()
        release.set()
        pump(app, lambda: not tab.controller.iter_shutdown_workers())
        assert cancelled.is_set() and not rows(page)
    finally:
        release.set()
        tab.shutdown()
        tab.close()


def test_installed_only_launch_skips_virtual_setup_and_checks_current_profile(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, _files = packages(tmp_path, 1)
    (root / 'bin64').mkdir()
    (root / 'bin64/CrimsonDesert.exe').write_bytes(b'fixture')
    calls = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr('cdmw.services.mod_management_inventory.subprocess.Popen', calls)
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    tab = ModManagementTab(controller=NewItemStudioController(synchronous=True), get_package_root=lambda: str(root))
    try:
        page = tab.virtual_page
        page._sources = mod_sources(root)
        page._draft_loaded = True
        page.refresh()
        page._buttons()
        assert page.launch_button.isEnabled() and not page.apply_button.isEnabled()
        monkeypatch.setattr(page, '_ensure_runtime', lambda *_: pytest.fail('Ordinary launch must not require the virtual loader'))
        _send(NewItemPresentationBridge(tab), page.launch_button, 'activate')
        assert calls.call_args.args[0] == [str(root / 'bin64/CrimsonDesert.exe')]
        calls.reset_mock()
        monkeypatch.setattr('cdmw.services.virtual_loader_state.load_profile', lambda *_: {'generation': 'changed'})
        with pytest.raises(ValueError, match='saved profile changed'):
            launch_installed_game(root)
        assert not calls.called
    finally:
        tab.shutdown()
        tab.close()


def test_failed_apply_marks_draft_rows_and_keeps_saved_profile(tmp_path, monkeypatch):
    from tests.test_virtual_loader_saves import experimental_fixture
    root, files, _save = experimental_fixture(tmp_path, monkeypatch)
    before = (root / '.cdmw/virtual-loader/profile.json').read_bytes()
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab(controller=NewItemStudioController(synchronous=True), get_package_root=lambda: str(root))
    try:
        page = tab.virtual_page
        page.refresh()
        files[0].write_bytes(b'broken package')
        _send(NewItemPresentationBridge(tab), page.apply_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working)
        assert (root / '.cdmw/virtual-loader/profile.json').read_bytes() == before
        assert not page.launch_button.isEnabled() and page.apply_button.isEnabled()
        draft = next(item for key, item in rows(page).items() if key[0] == 'item')
        assert draft.text(3) == 'Needs review' and draft.toolTip(3)
        assert page.progress.isHidden()
    finally:
        tab.shutdown()
        tab.close()


def test_combined_list_toggle_routes_to_reviewed_install_owner(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 1)
    backups = Backups(tmp_path)
    backups.apply(prepare_install(files, root).preparation)
    before = load_registry(root)
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    reviews = []
    def accept(*args):
        reviews.append(args)
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'question', accept)
    window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: backups)))
    tab = ModManagementTab(window=window, controller=NewItemStudioController(synchronous=True), get_package_root=lambda: str(root))
    try:
        page = load_installed(tab, root)
        item = next(item for key, item in rows(page).items() if key[0] == 'installed')
        page.selection.setCurrentItem(item)
        bridge = NewItemPresentationBridge(tab)
        for enabled in (False, True):
            assert page.toggle_installed.isEnabled()
            _send(bridge, page.toggle_installed, 'activate')
            assert list_installed_overlays(root)[0].enabled is enabled
            assert page.selection.currentItem() is item
        assert len(reviews) == 2 and all(str(root) in review[2] for review in reviews)
        assert backups.count == 3 and load_registry(root) == before
    finally:
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize('blocker', ['cancel', 'running', 'transaction', 'missing'])
def test_ordinary_launch_guards_do_not_start_a_process(tmp_path, monkeypatch, blocker):
    from cdmw.models import RunCancelled
    root = tmp_path / 'game'
    (root / 'bin64').mkdir(parents=True)
    if blocker != 'missing':
        (root / 'bin64/CrimsonDesert.exe').write_bytes(b'fixture')
    if blocker == 'transaction':
        journal = root / '.cdmw/virtual-loader/transaction.json'
        journal.parent.mkdir(parents=True)
        journal.write_text('{}')
        with pytest.raises(ValueError, match='Recover the interrupted'):
            mod_sources(root)
    stop = threading.Event()
    if blocker == 'cancel':
        stop.set()
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: blocker == 'running')
    process = Mock()
    monkeypatch.setattr('cdmw.services.mod_management_inventory.subprocess.Popen', process)
    with pytest.raises((ValueError, RunCancelled)):
        launch_installed_game(root, stop_event=stop)
    assert not process.called


def test_combined_list_controls_and_rows_follow_all_builtin_languages(tmp_path):
    from cdmw.domain.localization import BUILTIN_LANGUAGE_CODES
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    page = tab.virtual_page
    page._append_selection('item', (tmp_path / 'Example.cditem',))
    localizer = UiLocalizer(language_dir=tmp_path / 'languages', language_code='en')
    localizer.activate_runtime_tracking(tab, application=app)
    def nodes(node):
        yield node
        for child in node['children']:
            yield from nodes(child)
    try:
        for code in BUILTIN_LANGUAGE_CODES:
            localizer.load_language(code)
            localizer.apply_registered_roots()
            page._buttons()
            localizer.apply_registered_roots()
            assert page.apply_button.text() == localizer.translate('Apply changes')
            assert page.selection.headerItem().text(2) == localizer.translate('Loads with')
            state = NewItemPresentationBridge(tab).snapshot()
            projected = {node['name']: node for node in nodes(state['root'])}
            cells = projected['virtual_loader_selection']['props']['rows'][0]['cells']
            assert cells[2]['text'] == localizer.translate('CDMW launch')
            assert cells[3]['text'] == localizer.translate('Pending changes')
            assert projected['virtual_loader_notice']['props']['text'] == localizer.translate('Experimental')
            assert not state['unsupported']
    finally:
        localizer.shutdown()
        tab.shutdown()
        tab.close()


def test_physical_install_changes_require_reapply_before_virtual_launch(tmp_path, monkeypatch):
    from tests.test_virtual_loader_saves import experimental_fixture
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab(controller=NewItemStudioController(synchronous=True), get_package_root=lambda: str(root))
    try:
        page = tab.virtual_page
        page.refresh()
        assert page.launch_button.isEnabled()
        tab.controller.install_finished.emit(SimpleNamespace(removed_overlay_id='changed-install'))
        pump(app, lambda: not tab.controller.busy and tab.independent_page._queued is None)
        page.refresh()
        assert not page.launch_button.isEnabled()
        assert next(item for key, item in rows(page).items() if key[0] == 'item').text(3) == 'Pending changes'
        _send(NewItemPresentationBridge(tab), page.apply_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working)
        assert page.launch_button.isEnabled() and not page._needs_apply
    finally:
        tab.shutdown()
        tab.close()
