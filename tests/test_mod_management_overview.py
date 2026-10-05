"""Mod Management overview, embedded conversion and stale-read boundaries."""
import hashlib
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
from cdmw.models import RunCancelled
from cdmw.services.archive_overlay_manager import InstalledOverlay
from cdmw.services.overlay_inventory_details import mounted_archive_status, external_overlay_summary, MountedArchive
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.tools.mod_management import ModManagementTab
from cdmw.ui.tools.mod_management_overview import ModManagementOverview
from tests.test_mod_management import pump
from tests.test_mod_package_retrofit_async import _ToolOwner
from tests.test_new_item_rust_ui import _send


def test_grouped_overview_projects_existing_controls_and_preserves_every_route():
    from PySide6.QtWidgets import QGroupBox, QLabel

    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab()
    bridge = NewItemPresentationBridge(tab)
    try:
        groups = tab.overview.findChildren(QGroupBox)
        assert [(group.title(), [button.objectName() for button in group.findChildren(type(tab.choose_game))])
                for group in groups] == [
            ('Install && manage', ['mod_management_open_independent', 'mod_management_open_installed']),
            ('Package tools', ['mod_management_open_repackage', 'mod_management_open_merge']),
            ('Maintenance', ['mod_management_open_updates', 'mod_management_open_recovery']),
        ]
        assert all(label.objectName() != 'HintLabel' for label in tab.overview.findChildren(QLabel))
        assert all(button.toolTip() for button in tab.overview.actions.values())
        tab.overview._loaded((tab.overview._generation, ''), (
            MountedArchive('0037', False, True, False),
            MountedArchive('dmmgen', False, False, False),
            MountedArchive('0008', True, False, True),
        ))

        def nodes(node):
            yield node
            for child in node['children']:
                yield from nodes(child)

        state = bridge.snapshot()
        projected = {node['name']: node for node in nodes(state['root'])}
        assert state['root']['name'] == 'mod_management_workspace'
        assert not state['unsupported']
        assert projected['mod_management_group_installs']['label'] == 'Install & manage'
        assert projected['mod_management_archives']['props']['folder_states'] == {'0037': 'found'}
        assert projected['mod_management_status']['props']['management_warning'] is False
        _send(bridge, tab.overview.show_missing, 'toggle', True)
        assert tab.overview.mounts.topLevelItemCount() == 2
        assert tab.overview.mounts.topLevelItem(1).text(1) == 'Unknown'
        assert tab.overview.mounts.topLevelItem(1).text(2) == 'Stale reference'
        _send(bridge, tab.overview.show_game, 'toggle', True)
        assert tab.overview.mounts.topLevelItemCount() == 3
        for key, button in tab.overview.actions.items():
            _send(bridge, button, 'activate')
            assert tab.pages.currentWidget() is tab._page_by_key[key]
            _send(bridge, tab.pages, 'tab', 0)
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_mounted_status_reports_missing_mods_and_named_external_groups_without_writes(tmp_path):
    (tmp_path / 'meta').mkdir()
    records = [PapgtDirectory(name, PAPGT_DEFAULT_FLAGS, 0) for name in ('0009', '0036', 'dmmgen', 'dmmsa')]
    path = tmp_path / 'meta/0.papgt'
    original = serialize_papgt(records)
    path.write_bytes(original)
    for name in ('0009', 'dmmgen'):
        (tmp_path / name).mkdir()
        (tmp_path / name / '0.pamt').write_bytes(b'presence only')
    rows = mounted_archive_status(tmp_path)
    assert [(r.name, r.game, r.present) for r in rows] == [
        ('0009', True, True), ('0036', False, False), ('dmmgen', False, True), ('dmmsa', False, False)]
    summary = external_overlay_summary(tmp_path)
    assert 'dmmgen' in summary and '0036' not in summary and 'dmmsa' not in summary
    assert path.read_bytes() == original
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        mounted_archive_status(tmp_path, stop_event=stop)


def test_overview_reads_discard_old_root_and_close_results(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    overview = ModManagementOverview(controller)
    started, release = threading.Event(), threading.Event()
    def read(root, **_kwargs):
        if root == 'old':
            started.set()
            assert release.wait(5)
        return (MountedArchive(root, False, False, False),)
    monkeypatch.setattr('cdmw.ui.tools.mod_management_overview.mounted_archive_status', read)
    try:
        overview.show_missing.setChecked(True)
        overview.refresh('old')
        pump(app, started.is_set)
        overview.refresh('new')
        release.set()
        pump(app, lambda: overview.mounts.topLevelItemCount() == 1)
        assert overview.mounts.topLevelItem(0).text(0) == 'new'
        assert overview.status.text() == '1 stale mod reference'
        assert 'still references new' in overview.status.toolTip()
        overview.set_entries((InstalledOverlay('one', 'Item', (1,), 'new', 2, 0, health='missing'),))
        assert overview.counts['attention'].text() == '1'
        assert overview.mounts.topLevelItem(0).text(1) == 'CDMW'
        overview._loaded((0, 'old'), (MountedArchive('wrong', False, True, False),))
        assert overview.mounts.topLevelItem(0).text(0) == 'new'
        overview._loaded((overview._generation, 'new'), (MountedArchive('0008', True, False, False),))
        assert 'Required game archives are missing: 0008' in overview.status.text()
        overview.show_game.setChecked(True)
        assert overview.mounts.topLevelItem(0).text(0) == '0008'
        overview.request_shutdown()
        overview._loaded((overview._generation, 'new'), (MountedArchive('late', False, True, False),))
        assert overview.mounts.topLevelItem(0).text(0) == '0008'
    finally:
        release.set()
        overview.request_shutdown()
        controller.request_shutdown()
        pump(app, lambda: not controller.iter_shutdown_workers())
        overview.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_all_management_pages_keep_their_actions_and_editable_controls(tmp_path):
    app = QApplication.instance() or QApplication([])
    owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(repackage_owner=owner)
    bridge = NewItemPresentationBridge(tab)

    def walk(node):
        yield node
        for child in node['children']:
            yield from walk(child)

    try:
        for key in ('installed', 'independent', 'repackage', 'merge', 'updates', 'recovery'):
            tab.open_page(key)
            if key == 'installed':
                controls = [tab.inventory.search, tab.inventory.table, tab.inventory.inspector,
                            tab.inventory.toggle_button, tab.inventory.remove_button, tab.inventory.refresh_button,
                            tab.inventory.update_button, tab.inventory.preview_retry]
            elif key == 'independent':
                page = tab.independent_page
                controls = [page.items, page.import_button, page.remove_button, page.refresh_button,
                            page.export_profile_button, page.import_profile_button, page.scan_button,
                            page.scan_folder_button, page.compose_button, page.export_merge_button, page.comparison]
            elif key == 'repackage':
                page = tab.repackage_ui
                controls = [page.source_edit, page.output_edit, page.scan_button, page.table,
                            page.preview_button, page.convert_button, page.open_output_button, page.diff_preview]
            elif key in ('merge', 'updates'):
                page = tab._page_by_key[key]
                controls = [page.game_root, page.title, page.destination, page.scan_button, page.export_button, page.review]
            else:
                controls = [tab.inventory.rebuild_button, tab.inventory.start_fresh_button, tab.recovery]
            state = bridge.snapshot()
            assert not state['unsupported'], key
            projected = {node['id']: node for node in walk(state['root']) if 'id' in node}
            for widget in controls:
                identifier = bridge.document.registry.identify(widget)
                assert identifier in projected, (key, type(widget).__name__, widget.objectName())
                assert projected[identifier]['enabled'] == widget.isEnabled()
            assert len([node for node in projected.values() if node['kind'] == 'group']) >= 2, key
        _send(bridge, tab.recovery, 'activate')
        assert not tab.overlay_migration_button.isHidden()
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_rust_repackage_page_scans_converts_and_keeps_inline_results(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / 'source'
    payload = source / 'Example/character/model/example.pac'
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b'owned fixture payload')
    original = hashlib.sha256(payload.read_bytes()).digest()
    owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(repackage_owner=owner)
    bridge = NewItemPresentationBridge(tab)
    tab.show()
    try:
        _send(bridge, tab.overview.actions['repackage'], 'activate')
        ui = tab.repackage_ui
        assert ui is not None and not bridge.snapshot()['unsupported']
        _send(bridge, ui.source_edit, 'text', str(source))
        _send(bridge, ui.output_edit, 'text', str(tmp_path / 'converted'))
        _send(bridge, ui.scan_button, 'activate')
        pump(app, lambda: ui.table.rowCount() == 1 and ui.convert_button.isEnabled())
        assert not bridge.snapshot()['unsupported']
        _send(bridge, ui.preview_button, 'activate')
        assert 'Example' in ui.diff_preview.toPlainText()
        _send(bridge, ui.convert_button, 'activate')
        pump(app, lambda: 'Processed 1' in ui.status_label.text())
        assert 'Example' in ui.diff_preview.toPlainText()
        assert 'Processed 1' in tab.log.toPlainText()
        outputs = list((tmp_path / 'converted').rglob('example.pac'))
        assert len(outputs) == 1 and outputs[0].read_bytes() == payload.read_bytes()
        assert hashlib.sha256(payload.read_bytes()).digest() == original
        assert not bridge.snapshot()['unsupported']
        _send(bridge, tab.pages, 'tab', 0)
        _send(bridge, tab.overview.actions['repackage'], 'activate')
        assert tab.repackage_ui is ui and 'Example' in ui.diff_preview.toPlainText()
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        owner.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_embedded_repackage_cancel_retains_draining_worker_and_blocks_restart(tmp_path, monkeypatch):
    from cdmw.workers.mod_package_retrofit_workers import RetrofitConversionRequest
    app = QApplication.instance() or QApplication([])
    owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(repackage_owner=owner)
    started, release = threading.Event(), threading.Event()
    def convert(_request, *, stop_event, **_kwargs):
        started.set()
        assert release.wait(5)
        assert stop_event.is_set()
        raise RunCancelled('cancelled')
    monkeypatch.setattr('cdmw.workers.mod_package_retrofit_workers.convert_retrofit_request', convert)
    tab.show()
    tab.open_page('repackage')
    ui = tab.repackage_ui
    request = RetrofitConversionRequest(0, tmp_path / 'output', ())
    try:
        assert ui.task_controller.start_conversion(request)
        pump(app, started.is_set)
        bridge = NewItemPresentationBridge(tab)
        _send(bridge, ui.cancel_button, 'activate')
        assert 'Cancellation requested' in ui.status_label.text()
        assert tab.iter_shutdown_workers()
        assert not ui.convert_button.isEnabled()
        assert ui.task_controller.start_conversion(request) == 0
        started_at = time.monotonic()
        tab.request_shutdown()
        assert time.monotonic() - started_at < .1
        assert tab.iter_shutdown_workers(), 'Closing must retain ownership until the writer has stopped.'
        release.set()
        pump(app, lambda: not tab.iter_shutdown_workers())
        pump(app, lambda: not ui.task_controller._jobs)
        assert 'Stopped.' in ui.status_label.text()
    finally:
        release.set()
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        owner.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_localized_overview_and_late_repackage_keep_navigation_and_settings(tmp_path):
    from cdmw.domain.localization import BUILTIN_LANGUAGE_CODES
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance() or QApplication([])
    owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(repackage_owner=owner)
    localizer = UiLocalizer(language_dir=tmp_path / 'languages', language_code='de')
    owner.ui_localizer = localizer
    localizer.activate_runtime_tracking(tab, application=app)
    tab.show()
    app.processEvents()
    try:
        tab.open_page('repackage')
        ui = tab.repackage_ui
        ui.output_edit.setText(str(tmp_path / 'kept-output'))
        for code in BUILTIN_LANGUAGE_CODES:
            localizer.load_language(code)
            tab.open_page('overview')
            app.processEvents()
            localizer.apply_registered_roots()
            assert tab.choose_game.text() == localizer.translate('Change…')
            assert tab.overview.actions['installed'].text() == localizer.translate('Installed mods')
            assert tab.pages.tabText(tab.pages.indexOf(tab.repackage_page)) == localizer.translate('Repackage')
            tab.open_page('repackage')
            app.processEvents()
            localizer.apply_registered_roots()
            assert ui.scan_button.text() == localizer.translate('Scan')
            assert ui.output_edit.text() == str(tmp_path / 'kept-output')
            assert tab.pages.currentWidget() is tab.repackage_page
        assert not NewItemPresentationBridge(tab).snapshot()['unsupported']
    finally:
        localizer.shutdown()
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        owner.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_game_folder_choice_updates_all_game_pages_and_preserves_repackage(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    roots = [str(tmp_path / 'old-game')]
    owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(repackage_owner=owner, get_package_root=lambda: roots[-1],
                           set_package_root=roots.append)
    tab.show()
    tab.open_page('repackage')
    tab.repackage_ui.output_edit.setText(str(tmp_path / 'kept-output'))
    chosen = str(tmp_path / 'new-game')
    monkeypatch.setattr('cdmw.ui.tools.mod_management.QFileDialog.getExistingDirectory', lambda *_: chosen)
    try:
        bridge = NewItemPresentationBridge(tab)
        _send(bridge, tab.choose_game, 'activate')
        assert roots[-1] == chosen and tab.game_folder.text() == chosen
        assert tab.inventory.package_root == chosen
        assert tab.independent_page.package_root == chosen
        assert tab.merge_page.game_root.text() == chosen
        assert tab.update_page.game_root.text() == chosen
        assert tab.pages.currentWidget() is tab.repackage_page
        assert tab.repackage_ui.output_edit.text() == str(tmp_path / 'kept-output')
        tab.open_page('overview')
        generation = tab.overview._generation
        _send(bridge, tab.overview.refresh_button, 'activate')
        assert tab.overview._generation > generation
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        owner.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
