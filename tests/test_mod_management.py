"""Utilities wiring and the installed-item input delivered to the Rust viewport."""
import hashlib
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import STANDARD_SHADER
from cdmw.services.new_item_service import NewItemService
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import ItemPreviewFrame, build_item_preview_package
from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_new_item_provenance import current_files
from tests.test_new_item_service import PAC, PAC_XML, build_package, _read
from tests.test_pac_xml_standard_material import HEAD, TAIL, texture, wrapper
from tests.test_static_skin_weight_export import _skinned_pac


def pump(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert predicate()


def test_utilities_opens_installed_textured_model_without_a_studio_snapshot(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root = tmp_path / 'game'
    files = current_files()
    files[PAC], original = _skinned_pac()
    texture_path = 'character/texture/overlay_preview_colour.dds'
    stream = io.BytesIO()
    Image.new('RGBA', (4, 4), (20, 80, 220, 255)).save(stream, format='DDS')
    files[texture_path] = stream.getvalue()
    files[PAC_XML] = (HEAD + wrapper(original.submeshes[0].name, STANDARD_SHADER,
        texture('_baseColorTexture', '0', texture_path, 0)) + TAIL).encode('utf-8')
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(root, files)), read_entry=_read)
    choice = replace(shop_spec('TexturedOverlay'),
                     template_transform=tuple(ModelPlacement(offset=(.4, 0, 0)).matrix()))
    plan = service.plan(choice, snapshot)
    backups = Backups(tmp_path)
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    fingerprints = {path: hashlib.sha256(path.read_bytes()).digest()
                    for path in root.rglob('*') if path.is_file()}
    requested = []
    monkeypatch.setattr(ItemPreviewFrame, '_start_package', lambda _self, request, **_kw: requested.append(request))
    window = SimpleNamespace(app_context=SimpleNamespace(
        services=SimpleNamespace(require_archive_mutations=lambda: backups)))
    utility = ModManagementTab(window=window, get_package_root=lambda: str(root),
                               controller=NewItemStudioController(synchronous=True))
    try:
        assert utility.controller.snapshot is None
        utility.show()
        app.processEvents()
        dialog = utility.findChild(OverlayManagerDialog)
        assert dialog.table.rowCount() == 1 and requested
        assert utility.pages.currentWidget() is dialog and not dialog.isWindow()
        assert dialog.preview.isVisibleTo(dialog)
        assert not dialog.preview_empty.isVisibleTo(dialog)
        token, source = requested[-1]

        def prepare():
            model = source(threading.Event())
            package = build_item_preview_package(model, token=token, output_root=tmp_path / 'preview',
                                                stop_event=threading.Event(), cache_mode='balanced')
            return model, package

        with ThreadPoolExecutor(max_workers=1) as executor:
            model, package = executor.submit(prepare).result(timeout=30)
        np.testing.assert_allclose(as_parsed_mesh(model).submeshes[0].vertices,
                                   np.asarray(original.submeshes[0].vertices) + (.4, 0, 0), atol=2e-4)
        manifest = json.loads((package / 'manifest.json').read_text())
        assert manifest['textures'], 'The installed model must reach the viewport with its texture binding.'
        bound = next(value['file'] for value in manifest['textures'] if value['role'] == 'base_color')
        bound_path = package / bound['path']
        assert hashlib.sha256(bound_path.read_bytes()).hexdigest().upper() == bound['sha256']
        # This legacy DDS has linear channels; the viewport package stores sRGB.
        expected = [round(255 * (1.055 * (value / 255) ** (1 / 2.4) - .055)) for value in (20, 80, 220)]
        with Image.open(bound_path) as image:
            pixels = np.asarray(image.convert('RGBA')).reshape(-1, 4)
            np.testing.assert_allclose(pixels[:, :3], np.tile(expected, (len(pixels), 1)), atol=2)
            assert np.all(pixels[:, 3] == 255)
        dialog.refresh()
        refreshed_token = requested[-1][0]
        assert refreshed_token != token
        utility.hide()
        utility.show()
        app.processEvents()
        assert requested[-1][0] not in (token, refreshed_token), 'Reopening must not reuse an older installed package.'
        assert utility.controller.snapshot is None
        assert {path: hashlib.sha256(path.read_bytes()).digest() for path in fingerprints} == fingerprints
    finally:
        utility.request_shutdown()
        pump(app, lambda: not utility.iter_shutdown_workers())
        utility.deleteLater()


def test_shell_shutdown_tracks_and_cancels_utilities_preview(tmp_path, monkeypatch):
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.ui.shell.close_controller import iter_tab_shutdown_workers, request_tab_shutdowns

    app = QApplication.instance() or QApplication([])
    utility = ModManagementTab()
    monkeypatch.setattr(OverlayManagerDialog, 'refresh', lambda self: None)
    dialog = OverlayManagerDialog(utility.controller, tmp_path, None, utility)
    monkeypatch.setattr(dialog.preview, '_ensure_host', lambda: True)
    started, release = threading.Event(), threading.Event()
    cancelled = []

    def source(stop):
        started.set()
        assert release.wait(5)
        cancelled.append(stop.is_set())
        raise_if_cancelled(stop)

    owner = SimpleNamespace(mod_management_tab=utility)
    dialog.preview.show(source, token='utilities-shutdown')
    try:
        pump(app, started.is_set)
        assert any(name.startswith('mod_management_tab.') for name, _, _ in iter_tab_shutdown_workers(owner))
        request_tab_shutdowns(owner)
        release.set()
        pump(app, lambda: not tuple(iter_tab_shutdown_workers(owner)))
        assert cancelled == [True]
    finally:
        release.set()
        utility.request_shutdown()
        pump(app, lambda: not utility.iter_shutdown_workers())
        dialog.reject()
        utility.deleteLater()


def test_shared_controller_blocks_overlapping_operations_and_routes_completion_once(tmp_path, monkeypatch):
    from cdmw.services.archive_overlay_install import OverlayInstallResult
    from cdmw.services.archive_overlay_migration import MigrationResult
    from cdmw.ui.new_item.panels_output import OutputPanel

    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    utility = ModManagementTab(controller=controller)
    output = OutputPanel(controller)
    started, release = threading.Event(), threading.Event()
    notices = []
    errors = []
    monkeypatch.setattr('PySide6.QtWidgets.QMessageBox.information',
                        lambda owner, *args: notices.append(owner))
    result = OverlayInstallResult(tmp_path, 0, 1, 100, 0, None, ('model.pac',))

    def install(_log, _stop):
        started.set()
        assert release.wait(5)
        return result

    try:
        assert controller._run('install', install, controller.install_finished.emit, errors.append)
        pump(app, started.is_set)
        assert not utility.overlay_removal_button.isEnabled()
        assert not controller._run('overlay_manager', lambda *_: None, lambda *_: None, lambda *_: None)
        release.set()
        pump(app, lambda: not controller.busy)
        assert errors == []
        assert notices == [output]
        assert utility.overlay_removal_button.isEnabled()
        controller.install_finished.emit(MigrationResult(tmp_path, 1, (), None, 100))
        assert notices == [output, utility]
    finally:
        release.set()
        utility.request_shutdown()
        pump(app, lambda: not utility.iter_shutdown_workers())
        output.deleteLater()
        utility.deleteLater()
        controller.deleteLater()


def test_rust_workspace_navigation_filter_and_scoped_activity(tmp_path, monkeypatch):
    from cdmw.services.archive_overlay_manager import InstalledOverlay
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    from tests.test_new_item_rust_ui import _send
    from PySide6.QtWidgets import QWidget
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ItemPreviewFrame, '_start_package', lambda *_args, **_kwargs: None)
    tab = ModManagementTab(controller=NewItemStudioController(synchronous=True))
    visible = QWidget()
    dialogs = PresentationDialogs(tab, visible)
    dialogs.active = True
    bridge = NewItemPresentationBridge(tab, dialogs=dialogs.dialogs)
    tab.show()
    app.processEvents()
    try:
        tab.inventory._loaded((InstalledOverlay('a', 'Alpha', (101,), '0041', 2, 1),
                               InstalledOverlay('b', 'Beta', (202,), '0041', 3, 1)))
        assert not bridge.snapshot()['unsupported']
        assert not dialogs.dialogs(), 'Inline pages must never become Rust modal dialogs.'
        _send(bridge, tab.inventory.search, 'text', 'Beta')
        assert tab.inventory.table.isRowHidden(0)
        assert tab.inventory._selected_entry().id == 'b'
        _send(bridge, tab.inventory.search, 'text', 'no matches')
        assert tab.inventory._selected_entry() is None
        assert not tab.inventory.preview_retry.isEnabled()
        _send(bridge, tab.inventory.search, 'text', '')
        assert tab.inventory._selected_entry().id == 'a'
        for index, page in enumerate((tab.inventory, tab.merge_page, tab.update_page)):
            _send(bridge, tab.pages, 'tab', index)
            assert tab.pages.currentWidget() is page
            assert not bridge.snapshot()['unsupported']
            assert not dialogs.dialogs()
        tab.controller.log_message.emit('Planning a different New Item')
        assert 'Planning a different New Item' not in tab.log.toPlainText()
        tab.inventory._preview_status('The preview could not be built: missing model')
        assert 'missing model' in tab.inventory.preview_status.text()
        assert 'missing model' in tab.log.toPlainText()
    finally:
        dialogs.close()
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        visible.deleteLater()


def test_installed_preview_worker_delivers_package_and_waits_for_host_ready(tmp_path, monkeypatch):
    from tests.test_new_item_item_preview import ItemPreviewFrameTests
    # Use the real overlay resolver, package worker and UI-thread delivery.
    app = QApplication.instance() or QApplication([])
    root = tmp_path / 'game'
    files = current_files()
    files[PAC], _ = _skinned_pac()
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(root, files)), read_entry=_read)
    plan = service.plan(replace(shop_spec('PreviewDelivery'), recipes=()), snapshot)
    backups = Backups(tmp_path)
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    FakeHost = ItemPreviewFrameTests._fake_host_class()
    owner_threads = []
    preparing_messages = []
    class Host(FakeHost):
        def show_preparation_status(self, message):
            preparing_messages.append(message)

        def load_package(self, path, **kwargs):
            from PySide6.QtCore import QThread
            owner_threads.append(QThread.currentThread() is app.thread())
            assert (path / 'manifest.json').is_file()
            return True
    monkeypatch.setattr('cdmw.ui.new_item.item_preview.default_host_factory', Host)
    tab = ModManagementTab(get_package_root=lambda: str(root),
                           preview_context={'output_root': tmp_path / 'previews'})
    try:
        tab.show()
        pump(app, lambda: bool(owner_threads))
        preview = tab.inventory.preview
        assert owner_threads == [True]
        assert preparing_messages == ['Preparing the selected model and textures…']
        assert not preview.is_ready, 'Preparing a package is not renderer acknowledgement.'
        preview.host.controller.state_changed.emit('ready', '')
        assert preview.is_ready
        assert tab.inventory.preview_status.text() == 'Full textures loaded.'
        previous = preview._loaded_token
        tab.inventory.preview_retry.click()
        pump(app, lambda: preview._loaded_token != previous)
        assert all(owner_threads)
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()


def test_inline_disable_last_overlay_can_be_enabled_again(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from tests.test_new_item_provenance import setup_game
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    plan = service.plan(replace(shop_spec('Toggle'), recipes=()), snapshot)
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    monkeypatch.setattr(ItemPreviewFrame, '_start_package', lambda *_args, **_kw: None)
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.Yes)
    window = SimpleNamespace(app_context=SimpleNamespace(
        services=SimpleNamespace(require_archive_mutations=lambda: backups)))
    tab = ModManagementTab(window=window, get_package_root=lambda: str(root),
                           controller=NewItemStudioController(synchronous=True))
    try:
        tab.show()
        app.processEvents()
        inventory = tab.inventory
        assert inventory.toggle_button.isEnabled()
        inventory.toggle_button.click()
        assert inventory._selected_entry().enabled is False
        assert inventory.toggle_button.text() == 'Enable…' and inventory.toggle_button.isEnabled()
        assert not inventory._selected_entry().issue
        inventory.toggle_button.click()
        assert inventory._selected_entry().enabled is True
        assert inventory.toggle_button.isEnabled()
        assert 'Enabled Toggle' in tab.log.toPlainText()
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
