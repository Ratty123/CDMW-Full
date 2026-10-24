import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
import threading

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.workers.new_item_authoring_index import authoring_index_task
from tests.test_independent_item_definition import definition_game, TEMPLATE
from tests.test_independent_item_settings import extended_game
from tests.test_new_item_settings_editor import editor_fixture, native_edit


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def select_field(editor, section, field):
    editor.section.setCurrentIndex(editor.section.findData(section))
    editor.field.setCurrentIndex(editor.field.findData(field))
    editor.override.setChecked(True)


def model_path(editor, path):
    index = editor._nodes[path].index()
    rows = []
    while index.isValid():
        rows.insert(0, index.row()); index = index.parent()
    return rows


def test_six_definition_groups_are_editable_through_native_presentation(tmp_path, app, definition_game):
    controller, panel, settings = editor_fixture(tmp_path)
    editor = settings.definition
    panel.views.setCurrentWidget(settings)
    settings.pages.setCurrentWidget(editor)
    document = PresentationDocument()
    def cell(path, value):
        native_edit(document, panel, editor.tree, 'cell', {'path': model_path(editor, path), 'column': 1, 'text': value})
        app.processEvents()
    try:
        editor.load.click()
        assert editor.index is not None and editor.index.localizations
        select_field(editor, 'text', 'knowledge_obtain_type'); cell((), '255')
        assert controller.current_spec().definition_settings.fields['knowledge_obtain_type'] == 255
        editor.override_description.setChecked(True)
        english = next(row for row in range(editor.translations.rowCount()) if editor.translations.item(row, 0).text() == 'eng')
        native_edit(document, panel, editor.translations, 'cell', {'path': [english], 'column': 2, 'text': 'Owned secondary'})
        assert controller.current_spec().definition_settings.secondary_description['texts']['eng'] == 'Owned secondary'
        select_field(editor, 'links', 'bundles'); cell((0, 'minimum'), '18,446,744,073,709,551,615')
        editor.tree.setCurrentIndex(editor._nodes[()].index()); editor.add.click()
        assert len(controller.draft.definition_settings.fields['bundles']) == 2
        select_field(editor, 'flags', 'dyeable')
        native_edit(document, panel, editor.tree, 'check_cell', {'path': [0], 'column': 1, 'check': 0})
        app.processEvents()
        assert controller.draft.definition_settings.fields['dyeable'] is False
        select_field(editor, 'equipment', 'sharpness'); cell(('maximum', 0, 'value'), '-9,223,372,036,854,775,808')
        assert controller.draft.definition_settings.fields['sharpness']['maximum'][0]['value'] == -(1 << 63)
        cell(('parameters', 0, 'value'), '256')
        assert controller.draft.definition_settings.fields['sharpness']['parameters'][0]['value'] == 255
        assert 'Invalid' in editor.message.text()
        select_field(editor, 'presentation', 'pattern_descriptions')
        editor.tree.setCurrentIndex(editor._nodes[(0, 'parameters', 0, 'text_key')].index())
        assert editor.picker.count() > 0
        selected = editor.picker.currentData(); editor.use.click()
        parameter = controller.draft.definition_settings.fields['pattern_descriptions'][0]['parameters'][0]
        assert {key: parameter[key] for key in ('category', 'key', 'text_key')} == editor.index.localizations[selected]
        select_field(editor, 'world', 'respawn_value'); cell((), '18,446,744,073,709,551,615')
        assert controller.draft.definition_settings.fields['respawn_value'] == (1 << 64) - 1
        cell((), str(1 << 64))
        assert controller.draft.definition_settings.fields['respawn_value'] == (1 << 64) - 1
        select_field(editor, 'world', 'faction'); cell(('costs', 0, 'count'), str(1 << 63))
        assert controller.current_spec().definition_settings.fields['faction']['costs'][0]['count'] == 1 << 63
        select_field(editor, 'world', 'sealable_items'); cell((0, 'target_type'), '2'); cell((0, 'target'), 'An owned tag')
        assert controller.draft.definition_settings.fields['sealable_items'][0]['target'] == 'An owned tag'
        cell((0, 'target_type'), '5')
        assert controller.draft.definition_settings.fields['sealable_items'][0]['target'] is None
        editor.clear_description.click()
        assert controller.draft.definition_settings.secondary_description == {'source_item': None, 'texts': {}}
        editor.override_description.setChecked(False)
        assert controller.draft.definition_settings.secondary_description is None
        panel._reset()
        assert controller.draft.definition_settings is None
        select_field(editor, 'flags', 'dyeable')
        controller.set_template(1005300)
        assert controller.draft.definition_settings is None
        controller.snapshot = None; panel.rebuild()
        assert not editor.isEnabled() and editor.model.rowCount() == 0
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_nested_batch_removal_clears_only_selected_entries_and_keeps_view(tmp_path, app, definition_game):
    controller, panel, settings = editor_fixture(tmp_path)
    editor = settings.definition
    try:
        select_field(editor, 'equipment', 'occupied_slots')
        parent = editor._nodes[(0, 'indexes')].index().siblingAtColumn(0)
        editor.tree.setExpanded(parent, True)
        for number in (0, 1):
            editor.tree.selectionModel().select(editor._nodes[(0, 'indexes', number)].index(),
                QItemSelectionModel.Select | QItemSelectionModel.Rows)
        editor.remove.click()
        assert controller.draft.definition_settings.fields['occupied_slots'] == [{'name_hash': 123456, 'indexes': []}]
        assert editor.tree.isExpanded(editor._nodes[(0, 'indexes')].index().siblingAtColumn(0))
        select_field(editor, 'presentation', 'pattern_descriptions')
        selection = editor.tree.selectionModel()
        for path in ((0,), (0, 'parameters', 0)):
            selection.select(editor._nodes[path].index(), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        editor.remove.click()
        assert controller.draft.definition_settings.fields['pattern_descriptions'] == []
        editor.override.setChecked(False)
        assert 'pattern_descriptions' not in controller.draft.definition_settings.fields
        editor.reset.click()
        assert controller.draft.definition_settings is None
        select_field(editor, 'world', 'respawn_value')
        # Qt must finish setData before a model reset, and a queued refresh must
        # read the current draft rather than resurrect an edit after Reset.
        editor.model.setData(editor._nodes[()].index(), '123', Qt.EditRole)
        assert controller.draft.definition_settings.fields['respawn_value'] == 123
        assert editor._refresh.isActive()
        editor.reset.click(); app.processEvents()
        assert controller.draft.definition_settings is None and not editor._refresh.isActive()
        select_field(editor, 'equipment', 'sharpness')
        editor.model.setData(editor._nodes[('limit',)].index(), '42', Qt.EditRole)
        editor.model.setData(editor._nodes[('craft_tool',)].index(), '0', Qt.EditRole)
        assert controller.draft.definition_settings.fields['sharpness']['limit'] == 42
        assert controller.draft.definition_settings.fields['sharpness']['craft_tool'] == 0
        app.processEvents()
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_definition_catalogue_cancellation_never_publishes_a_partial_index(tmp_path, definition_game, monkeypatch):
    from tests.test_independent_items import setup_game
    import cdmw.services.new_item_definition as service
    _, snapshot, _ = setup_game(tmp_path)
    stop = threading.Event(); original = service.read_definition_fields
    def cancel_after_one(raw):
        result = original(raw); stop.set(); return result
    monkeypatch.setattr(service, 'read_definition_fields', cancel_after_one)
    with pytest.raises(RunCancelled): authoring_index_task('item-definition', snapshot)(lambda *_: None, stop)
    assert 'item-definition' not in snapshot._authoring_indexes


def test_late_definition_catalogue_cannot_reach_replaced_snapshot(tmp_path, app, definition_game, monkeypatch):
    controller, panel, settings = editor_fixture(tmp_path)
    callbacks = []
    try:
        def capture(_kind, _task, done, _failed):
            callbacks.append(done); return True
        monkeypatch.setattr(controller, '_run', capture)
        controller.start_authoring_index('item-definition')
        controller.snapshot = replace(controller.snapshot, _authoring_indexes={})
        callbacks[0](object())
        assert settings.definition.index is None
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()
