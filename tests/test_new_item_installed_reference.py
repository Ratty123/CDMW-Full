"""Installed assets are an independently owned preview, never an item input."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.new_item.spec import ModelSource
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, unpack_recipe, package_metadata
from cdmw.services.new_item_planning import ModelFiles
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import load_model_import_source
from cdmw.ui.new_item.state import NewItemDraft
from tests.test_independent_items import imported_game
from tests.test_new_item_service import TEMPLATE, PAC_XML, imported_pac
from tests.test_new_item_character_preview import _mesh


def _source(tmp_path, name='FAF_reference_only'):
    file = tmp_path / (name + '.obj')
    file.write_text(f'o {name}\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
    source = load_model_import_source(file)
    source.dmm_source_revision = SimpleNamespace(validate=lambda _stop=None: None)
    return source


def _until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError('Reference worker did not finish')
        time.sleep(.005)


def test_reference_is_visible_in_preview_but_absent_from_recipe_and_exports(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, snapshot = imported_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=TEMPLATE, internal_name='OwnItem', display_names={'eng': 'Own Item'})
    controller.independent_mode = True
    source = _source(tmp_path)
    monkeypatch.setattr('cdmw.ui.new_item.installed_model_import.load_installed_model', lambda *a, **k: source)
    # Use an owned imported mesh in the output, independently of the fitting asset.
    controller.draft.model_source = ModelSource.IMPORTED
    controller.model_result = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
    before_spec, before_revision = controller.current_spec(), controller._draft_revision
    try:
        assert controller.start_installed_reference(object())
        assert controller.installed_reference is source and controller.model_import is None
        assert controller.current_spec() == before_spec and controller._draft_revision == before_revision
        assert source not in controller.variant_plan_inputs()[2]
        # Exercise the ordinary progressive preview and its resource lease.
        controller.model_result = None
        mesh = _mesh('owned_template')
        monkeypatch.setattr(controller, '_template_preview_build', lambda: (('template',), lambda _stop: mesh))
        monkeypatch.setattr(controller, '_template_geometry_build', lambda: (('template',), lambda _stop: mesh))
        token, preview = controller.item_preview_source(editable_template=True, include_installed_reference=True)
        lease = preview.acquire_usage()
        assert lease is not None and source._active_usage_count == 1
        scene = preview.geometry(threading.Event())
        assert scene.model is mesh and scene.character is source.baked_preview_mesh()
        assert preview.materials(threading.Event()).character is source.baked_preview_mesh()
        plain_token, plain = controller.item_preview_source(editable_template=True)
        assert plain_token != token and plain.geometry(threading.Event()).character is None
        lease.release()
        assert source._active_usage_count == 0
        own = _source(tmp_path, 'own_import')
        own.dmm_source_revision = None
        controller.model_import = own
        _, composite = controller.item_preview_source(include_installed_reference=True)
        usage = composite.acquire_usage()
        assert source._active_usage_count == own._active_usage_count == 1
        scene = composite.geometry(threading.Event())
        assert scene.template is None and scene.model is own.baked_scene_mesh()
        assert scene.character is source.baked_preview_mesh()
        usage.release()
        own.retire()
        assert composite.acquire_usage() is None and source._active_usage_count == 0
        controller.model_import = None
        own.cleanup()
        controller.model_result = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
        assert controller.start_plan() and controller.plan is not None
        package = read_package(package_bytes(from_plan(controller.plan, 'a' * 32)))
        continued, model, variants, *_ = unpack_recipe(package)
        assert continued.model_source is ModelSource.IMPORTED
        models = ([model] if model else []) + list(variants.values())
        assert models and all(value.pac_data == imported_pac(100) for value in models)
        assert 'FAF_reference_only' not in repr(package_metadata(package))
        assert all(b'FAF_reference_only' not in data for data in package.blobs.values())
        assert all('FAF_reference_only' not in path for path in controller.plan.loose_files)
        output = tmp_path/'dmm'
        service.export_loose(controller.plan, output, manager='DMM')
        controller.clear_installed_reference()
        assert controller.installed_reference is None and controller.current_spec() == before_spec
    finally:
        controller.request_shutdown()
        _until(lambda: not controller.iter_shutdown_workers())
        controller.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('end', ('cancel', 'shutdown', 'stale'))
def test_pending_reference_cleans_late_result_and_preserves_authored_item(tmp_path, monkeypatch, end):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    controller.snapshot = object()
    controller.draft.template_key = TEMPLATE
    previous = _source(tmp_path, 'previous')
    result = _source(tmp_path, 'new_reference')
    controller.installed_reference = previous
    started, release = threading.Event(), threading.Event()
    def load(*_args, **_kwargs):
        started.set()
        assert release.wait(4)
        return result  # Even a decoder that returns after cancellation is retired.
    monkeypatch.setattr('cdmw.ui.new_item.installed_model_import.load_installed_model', load)
    published = []
    controller.installed_reference_changed.connect(lambda value: published.append(value))
    try:
        assert controller.start_installed_reference(object())
        _until(started.is_set)
        if end == 'cancel': controller.cancel_operation('installed_reference')
        if end == 'shutdown': controller.request_shutdown()
        if end == 'stale': controller.draft.template_key += 1
        release.set()
        _until(lambda: not controller.iter_shutdown_workers())
        assert result not in published and result._retired
        assert controller.installed_reference is (None if end == 'shutdown' else previous)
        assert controller.model_import is None and controller.model_result is None
    finally:
        release.set()
        controller.request_shutdown()
        _until(lambda: not controller.iter_shutdown_workers())
        controller.deleteLater()
        app.processEvents()
