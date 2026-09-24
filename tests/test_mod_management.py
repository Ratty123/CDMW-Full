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
        utility.overlay_removal_button.click()
        app.processEvents()
        dialog = utility.findChild(OverlayManagerDialog)
        assert dialog.table.rowCount() == 1 and requested
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
        dialog.reject()
        utility.overlay_removal_button.click()
        app.processEvents()
        assert requested[-1][0] not in (token, refreshed_token), 'Reopening must not reuse an older installed package.'
        assert utility.controller.snapshot is None
        assert {path: hashlib.sha256(path.read_bytes()).digest() for path in fingerprints} == fingerprints
    finally:
        for dialog in utility.findChildren(OverlayManagerDialog):
            if not dialog._closed:
                dialog.reject()
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
