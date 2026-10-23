import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
import threading

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.item_settings import ItemSettings
from cdmw.services.new_item_settings import load_settings_index
from cdmw.services.new_item_template_search import search_template_options, USABLE_ITEMS_CATEGORY
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_settings_editor import ItemSettingsEditor, whole_number
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.ui.new_item.rust_ui_actions import apply_action
from cdmw.ui.new_item.state import NewItemDraft
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.workers.new_item_authoring_index import authoring_index_task
from tests.test_independent_item_settings import extended_game
from tests.test_independent_items import setup_game


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def editor_fixture(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=1001295, internal_name='Settings', display_names={'eng': 'Settings'})
    panel = StatsPanel(controller)
    panel.rebuild()
    return controller, panel, panel.item_settings


def native_edit(document, editor, widget, action, value=None):
    document.snapshot(editor)
    identifier = document.registry.identify(widget)
    node = document.registry.current[identifier]
    obj, node = document.registry.resolve(identifier, node['revision'])
    apply_action(document, obj, node, action, value)


def test_real_controls_store_exact_amounts_false_empty_and_template_inheritance(tmp_path, app, extended_game):
    controller, panel, editor = editor_fixture(tmp_path)
    try:
        assert editor.pages.isEnabled()
        editor.load.click()
        assert editor.index is not None and editor.index.actions
        editor.policies['discardable'].setCurrentIndex(editor.policies['discardable'].findData(False))
        assert controller.draft.item_settings.discardable is False
        editor.override_repairs.setChecked(True)
        editor.repair_item.setCurrentIndex(editor.repair_item.findData(1))
        editor.add_repair.click()
        editor.repairs.item(0, 3).setText(str((1 << 64) - 1))
        assert controller.draft.item_settings.repairs[0].resource_count == (1 << 64) - 1
        editor.override_actions.setChecked(True)
        editor.use_action.setCurrentIndex(editor.use_action.findData(1000031))
        editor.add_action.click()
        assert controller.draft.item_settings.use_actions == (1000031,)
        editor.reward.setCurrentIndex(editor.reward.findData(880000))
        assert controller.draft.item_settings.extraction_reward == 880000
        editor.pages.setCurrentIndex(3)
        document = PresentationDocument()
        native_edit(document, editor, editor.cooldowns[1], 'text', '18,446,744,073,709,551,615')
        native_edit(document, editor, editor.cooldowns[1], 'finish_edit')
        assert controller.draft.item_settings.cooldowns == (0, (1 << 64) - 1, 0)
        native_edit(document, editor, editor.maximum_charges[2], 'text', str(0xffffffff))
        native_edit(document, editor, editor.maximum_charges[2], 'finish_edit')
        assert controller.draft.item_settings.maximum_charges == (0, 0, 0xffffffff)
        index = next(index for index, row in enumerate(editor._quantities) if (row.kind, row.level) == ('stat', 0))
        editor.amounts.item(index, 4).setText(str(-(1 << 63)))
        assert controller.draft.item_settings.quantities[0].value == -(1 << 63)
        assert controller.current_spec().item_settings == controller.draft.item_settings
        editor.amounts.item(index, 4).setText('1.5')
        assert controller.draft.item_settings.quantities[0].value == -(1 << 63)
        assert editor.amounts.item(index, 4).text() == str(-(1 << 63))
        editor.reset.click()
        assert controller.draft.item_settings is None
        assert editor.policies['discardable'].currentData() is None
    finally:
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()


def test_usable_template_is_discoverable_and_selection_preserves_its_actions(tmp_path, app, extended_game):
    controller, panel, editor = editor_fixture(tmp_path)
    try:
        catalogue = controller.snapshot.template_search_catalogue()
        assert not any(row[0] == 1005300 for row in search_template_options(catalogue, limit=None))
        assert [row[0] for row in search_template_options(catalogue, group_key=USABLE_ITEMS_CATEGORY)] == [1005300]
        controller.set_template(1005300)
        assert controller.draft.template_key == 1005300
        assert controller.draft.item_settings == ItemSettings(use_actions=(1000031,))
        assert not controller.snapshot._contexts[1005300].template.equip_type_name
        assert editor.pages.isEnabled()
        editor.policies['important_item'].setCurrentIndex(editor.policies['important_item'].findData(True))
        editor.reset.click()
        assert controller.draft.item_settings == ItemSettings(use_actions=(1000031,))
        editor.policies['important_item'].setCurrentIndex(editor.policies['important_item'].findData(True))
        panel._reset()
        assert controller.draft.item_settings == ItemSettings(use_actions=(1000031,))
    finally:
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('value,expected', (
    ('18.446.744.073.709.551.615', (1 << 64) - 1),
    ('18\u202f446\u202f744\u202f073\u202f709\u202f551\u202f615', (1 << 64) - 1),
    ('-9,223,372,036,854,775,808', -(1 << 63)), ('00000000000000000001', 1),
))
def test_grouped_integer_entry_never_uses_float_or_loses_precision(value, expected):
    assert whole_number(value, -(1 << 63), (1 << 64) - 1) == expected


@pytest.mark.parametrize('value', ('1.5', '1e18', '12,34', str(1 << 64), 'True', '9' * 65))
def test_invalid_integer_input_refuses(value):
    with pytest.raises(ValueError):whole_number(value, 0, (1 << 64) - 1)


def test_catalogue_cancellation_does_not_publish_a_partial_index(tmp_path, extended_game, monkeypatch):
    _, snapshot, _ = setup_game(tmp_path)
    import cdmw.services.new_item_settings as service
    stop = threading.Event()
    original = service.read_item_use_layout
    def cancel_after_one(raw):
        result = original(raw)
        stop.set()
        return result
    monkeypatch.setattr(service, 'read_item_use_layout', cancel_after_one)
    with pytest.raises(RunCancelled):authoring_index_task('item-settings', snapshot)(lambda *_: None, stop)
    assert 'item-settings' not in snapshot._authoring_indexes


def test_late_item_settings_catalogue_cannot_reach_a_replaced_snapshot(tmp_path, app, extended_game, monkeypatch):
    controller, panel, editor = editor_fixture(tmp_path)
    callbacks = []
    try:
        def capture(_kind, _task, done, _failed):
            callbacks.append(done)
            return True
        monkeypatch.setattr(controller, '_run', capture)
        controller.start_authoring_index('item-settings')
        controller.snapshot = replace(controller.snapshot, _authoring_indexes={})
        callbacks[0](object())
        assert editor.index is None
    finally:
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()
