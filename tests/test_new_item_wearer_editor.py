"""The assembled Template page exposes wearer edits through the Rust bridge."""
from copy import deepcopy

import pytest

from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.services.new_item_rust_protocol import PresentationProtocolError
from cdmw.ui.new_item.state import NewItemDraft
from tests.test_new_item_rust_ui import studio, _send
from tests.test_new_item_service import TEMPLATE
from tests.test_new_item_wearers import wearer_game, KLIFF


def test_visible_template_control_adds_restores_and_resets_without_enabling_ambiguous_items(studio, wearer_game):
    _fixture, tab, bridge = studio
    _service, snapshot = wearer_game
    controller = tab.controller
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=TEMPLATE, internal_name='Wearer', display_names={'eng': 'Wearer'})
    controller.invalidate_plan()
    tab.show_step(0)
    editor = tab.template_panel.wearers
    bridge.snapshot()
    assert bridge.document.registry.identify(editor.choices['kliff']) in bridge.document.registry.current
    assert editor.choices['damiane'].isChecked() and not editor.choices['damiane'].isEnabled()
    assert controller.draft.behavior_settings is None
    with pytest.raises(PresentationProtocolError):
        _send(bridge, editor.choices['damiane'], 'toggle', False)
    controller.plan = object()
    _send(bridge, editor.choices['kliff'], 'toggle', True)
    assert controller.plan is None
    settings = controller.current_spec().behavior_settings
    assert settings.fields['prefabs'][0]['tribe_genders'][-1] == KLIFF
    _send(bridge, editor.choices['kliff'], 'toggle', False)
    assert controller.draft.behavior_settings is None
    # Restoring a saved/continued draft must reflect its existing override.
    controller.draft.behavior_settings = settings
    controller.invalidate_plan()
    assert editor.choices['kliff'].isChecked()
    controller.set_template(None)
    assert controller.draft.behavior_settings is None
    assert all(not check.isEnabled() for check in editor.choices.values())
    controller.draft.template_key = TEMPLATE
    original = snapshot.rows[TEMPLATE]
    prefabs = read_behavior_fields(original.raw)['prefabs']
    prefabs.insert(1, deepcopy(prefabs[0]))
    snapshot.rows[TEMPLATE] = parse_iteminfo_row(set_behavior_fields(original.raw, {'prefabs': prefabs}), structured=True)
    controller.invalidate_plan()
    assert all(not check.isEnabled() for check in editor.choices.values())
    assert 'one wearable model' in editor.status.text()
    # A full selector list must reject the edit visibly, leaving the draft intact.
    prefabs = read_behavior_fields(original.raw)['prefabs']
    prefabs[0]['tribe_genders'] = prefabs[0]['tribe_genders'] + list(range(1000, 1253))
    snapshot.rows[TEMPLATE] = parse_iteminfo_row(set_behavior_fields(original.raw, {'prefabs': prefabs}), structured=True)
    controller.invalidate_plan()
    _send(bridge, editor.choices['kliff'], 'toggle', True)
    assert controller.draft.behavior_settings is None
    assert not editor.choices['kliff'].isChecked()
    assert 'cannot be changed safely' in editor.status.text()


def test_wearer_control_translates_in_every_builtin_language(tmp_path, wearer_game):
    from PySide6.QtWidgets import QApplication
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.services.active_ui_translation import ACTIVE_UI_LOCALIZER_PROPERTY
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.wearer_editor import WearerEditor

    app = QApplication.instance() or QApplication([])
    previous = app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    service, snapshot = wearer_game
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=TEMPLATE)
    try:
        for language in BUILTIN_LANGUAGES:
            localizer = UiLocalizer(language_dir=tmp_path/'languages', language_code=language.code)
            app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, localizer)
            editor = WearerEditor(controller)
            try:
                localizer.apply(editor)
                assert editor.title() == localizer.translate('Wearable by')
                assert editor.choices['damiane'].isChecked()
                assert editor.status.text() == localizer.translate(
                    'Locked choices are already included by the template.')
                if language.code != 'en':
                    assert editor.title() != 'Wearable by'
                    assert not editor.note.text().startswith('Keeps the template')
            finally:
                editor.deleteLater()
                app.processEvents()
                localizer.shutdown()
    finally:
        controller.deleteLater()
        app.processEvents()
        app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, previous)
