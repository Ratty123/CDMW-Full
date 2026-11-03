"""Installed-model controls run through the actual resident presentation bridge."""
from types import SimpleNamespace
import threading
import time

from PySide6.QtWidgets import QApplication

from cdmw.services.dmm_character_mods import scan_character_library
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.installed_character_models import InstalledCharacterModels
from tests.test_dmm_character_mods import installed, write
from tests.test_new_item_rust_ui import studio, _send


def test_scan_filter_load_and_update_use_installed_files_through_rust(studio, installed, monkeypatch):
    _, tab, bridge = studio
    install, mods, path, _ = installed
    editor = tab.template_panel.installed_models
    editor._settings = SimpleNamespace(setValue=lambda *_: None)
    editor._saved = str(install)
    tab.show_step(0)
    _send(bridge, editor.refresh_button, 'activate')
    assert editor.library.install == install
    _send(bridge, editor.collection, 'choose', editor.collection.findData('fit'))
    assert editor.models.currentData() == path
    assert '1.0.9' in editor.collection.currentText()
    captured = []
    monkeypatch.setattr(tab.controller, 'start_model_import', lambda file, **kwargs: captured.append((file, kwargs)))
    _send(bridge, editor.load_button, 'activate')
    request = captured[0][1]['installed_model']
    assert request.path == path and request.library.mod('fit').folder == mods / 'fit'
    owner = SimpleNamespace(dmm_source_revision=request.library.revision)
    monkeypatch.setattr(tab.controller, 'variant_plan_inputs', lambda: ({}, {}, (owner,)))
    invalidated = []
    tab.controller.plan_invalidated.connect(lambda: invalidated.append(True))
    write(mods, 'fit/0009/' + path.replace('zz_test', 'zz_new'), b'new mesh')
    _send(bridge, editor.refresh_button, 'activate')
    assert invalidated and len(editor._paths) == 2
    _send(bridge, editor.filter, 'text', 'zz_new')
    assert editor.models.count() == 1 and 'zz_new' in editor.models.currentData()
    assert request.library.identity != editor.library.identity


def _until(predicate):
    deadline = time.monotonic() + 4
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError('Lookup did not finish')
        time.sleep(.005)


def test_closed_scan_is_cancelled_without_late_widget_updates(installed, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = scan_character_library(str(installed[0]))
    started, stopped = threading.Event(), threading.Event()
    def scan(_saved, *, stop_event):
        started.set()
        if stop_event.wait(2):
            stopped.set()
        return library
    monkeypatch.setattr('cdmw.ui.new_item.installed_character_models.scan_character_library', scan)
    controller = NewItemStudioController()
    editor = InstalledCharacterModels(controller)
    editor._settings = SimpleNamespace(setValue=lambda *_: None)
    try:
        _until(started.is_set)
        controller.request_shutdown()
        _until(stopped.is_set)
        _until(lambda: not controller.iter_shutdown_workers())
        assert editor.library is None
    finally:
        controller.request_shutdown()
        _until(lambda: not controller.iter_shutdown_workers())
        editor.deleteLater()
        app.processEvents()


def test_installed_model_controls_translate_in_all_builtin_languages(tmp_path):
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.services.active_ui_translation import ACTIVE_UI_LOCALIZER_PROPERTY
    from cdmw.ui.localization import UiLocalizer

    app = QApplication.instance() or QApplication([])
    previous = app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    controller = NewItemStudioController(synchronous=True)
    try:
        for language in BUILTIN_LANGUAGES:
            localizer = UiLocalizer(language_dir=tmp_path/'languages', language_code=language.code)
            app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, localizer)
            editor = InstalledCharacterModels(controller)
            try:
                localizer.apply(editor)
                assert editor.title() == localizer.translate('Installed character models (local test)')
                assert editor.load_button.text() == localizer.translate('Load selected model')
                editor._filter()
                assert editor.status.text() == localizer.translate('{count} models found. Refine the search to see more than the first 80.').format(count=0)
                if language.code != 'en':
                    assert editor.title() != 'Installed character models (local test)'
            finally:
                editor.deleteLater()
                app.processEvents()
    finally:
        controller.request_shutdown()
        app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, previous)
