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


def test_guided_picker_filters_parts_reports_import_failure_and_refreshes(studio, installed, monkeypatch):
    from PySide6.QtCore import Qt
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    _, tab, _bridge = studio
    install, mods, path, _ = installed
    head = 'character/model/1_pc/9_pgm/head/head_sub/zk_head.pac'
    write(mods, 'fit/0009/' + head, b'head')
    editor = tab.model_panel.installed_models
    assert not hasattr(tab.template_panel, 'installed_models')
    assert tab.template_panel.wearers.parentWidget() is tab.template_panel.preview_group
    assert tab.model_panel.reference_group.parentWidget() is tab.model_panel.preview_controls.parentWidget()
    monkeypatch.setattr(tab.model_panel, 'refresh_preview', lambda: None)
    monkeypatch.setattr(tab.controller, 'template_primary_entry', lambda: SimpleNamespace(path=path))
    # The fixture template is a sword; installed character models are a reference for worn gear.
    assert tab.model_panel.reference_group.isHidden() and tab.model_panel.body_details.isHidden()
    monkeypatch.setattr(tab.controller, 'template_is_worn', lambda: True)
    tab.model_panel._refresh_body_visibility()
    assert not tab.model_panel.reference_group.isHidden() and not tab.model_panel.body_details.isHidden()
    editor._settings = SimpleNamespace(setValue=lambda *_: None)
    editor._saved = str(install)
    tab.show_step(2)
    bridge = NewItemPresentationBridge(tab, dialogs=lambda: (editor,) if not editor.isHidden() else ())
    _send(bridge, tab.model_panel.installed_model_button, 'activate')
    assert editor.library.install == install
    assert editor.collection.currentData() == 'fit'
    assert editor.category.currentData() == 'chest'
    assert editor.models.topLevelItemCount() == 1
    assert editor._selected_path() is None and not editor.load_button.isEnabled()
    item = editor.models.topLevelItem(0)
    editor.models.setCurrentItem(item)
    assert editor.load_button.isEnabled()
    captured = []
    monkeypatch.setattr(tab.controller, 'start_installed_reference', lambda request: captured.append(request) or True)
    before = tab.controller.model_import
    _send(bridge, editor.load_button, 'activate')
    request = captured[0]
    assert request.path == path and editor._loading
    tab.controller.installed_reference_failed.emit('Missing required texture: eyes.dds___')
    assert not editor._loading and editor.isVisible()
    assert 'unchanged' in editor.feedback.text() and 'eyes.dds___' in editor.error_details.toPlainText()
    assert editor.error_details.isHidden() and not editor.details_button.isHidden()
    _send(bridge, editor.details_button, 'activate')
    assert not editor.error_details.isHidden() and editor.error_details.isReadOnly()
    assert tab.controller.model_import is before
    _send(bridge, editor.category, 'choose', editor.category.findData('head'))
    editor.models.setCurrentItem(editor.models.topLevelItem(0))
    assert not editor.load_button.isEnabled() and 'different part' in editor.guidance.text()
    tab.controller.installed_reference = SimpleNamespace(dmm_source_revision=request.library.revision)
    monkeypatch.setattr(tab.controller, '_cleanup_model_source', lambda _: None)
    invalidated = []
    tab.controller.plan_invalidated.connect(lambda: invalidated.append(True))
    write(mods, 'fit/0009/' + path.replace('zz_test', 'zz_new'), b'new mesh')
    _send(bridge, editor.refresh_button, 'activate')
    assert not invalidated and tab.controller.installed_reference is None and len(editor._paths) == 3
    _send(bridge, editor.filter, 'text', 'zz_new')
    assert editor.models.topLevelItemCount() == 1
    assert 'zz_new' in editor.models.topLevelItem(0).data(0, Qt.UserRole)
    assert request.library.identity != editor.library.identity
    editor.reject()


def test_success_shows_reference_and_close_cancels_only_owned_reference(studio, monkeypatch):
    _, tab, _ = studio
    editor = tab.model_panel.installed_models
    tab.show_step(2)
    editor._open = True
    editor._loading = True
    editor._import_ready(object())
    assert tab.model_panel.view_mode.currentData() == 'side_by_side'
    assert tab.model_panel.show_installed_reference.isChecked()
    assert not editor._open and not editor._loading
    cancelled = []
    monkeypatch.setattr(tab.controller, 'cancel_operation', lambda lane: cancelled.append(lane))
    editor._closed()
    assert not cancelled
    editor._open = editor._loading = True
    editor._closed()
    assert cancelled == ['installed_reference'] and not editor._open
    editor._import_ready(object())  # A late result must not reopen/accept a closed picker.
    assert not editor._open


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
        editor.open()
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
                assert editor.windowTitle() == localizer.translate('Installed character models (local test)')
                assert editor.load_button.text() == localizer.translate('Show fitting reference')
                editor._filter()
                assert editor.status.text() == localizer.translate('No models match this part. Try another installed mod, part or search.')
                if language.code != 'en':
                    assert editor.windowTitle() != 'Installed character models (local test)'
            finally:
                editor.deleteLater()
                app.processEvents()
    finally:
        controller.request_shutdown()
        app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, previous)
