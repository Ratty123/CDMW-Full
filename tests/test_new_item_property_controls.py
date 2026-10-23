"""Real headless controls and native presentation preserve scalar intent exactly."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.rust_ui_actions import apply_action
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.ui.new_item.state import NewItemDraft, spec_from_draft, stats_summary
from cdmw.ui.new_item.tab import _workflow_step_for_issue
from cdmw.domain.new_item.rules import validate_spec
from tests.test_independent_item_properties import equipment_game
from tests.test_independent_items import setup_game


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def controls(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=1001295, internal_name='PropertyControls')
    panel = StatsPanel(controller)
    panel.rebuild()
    return controller, panel


def test_native_property_actions_support_full_u32_inheritance_and_reset(tmp_path, app, equipment_game):
    controller, panel = controls(tmp_path)
    try:
        document = PresentationDocument()
        document.snapshot(panel)
        for name, maximum in (('item_tier', 255), ('required_level', 0xffffffff), ('max_durability', 65535)):
            control = panel.property_controls[name]
            identifier = document.registry.identify(control)
            obj, node = document.registry.resolve(identifier, document.registry.current[identifier]['revision'])
            assert node['kind'] == 'number' and node['props']['maximum'] == maximum
            apply_action(document, obj, node, 'number', maximum)
            assert getattr(controller.draft, name) == maximum
        spec = spec_from_draft(controller.draft, controller.stat_grid())
        assert (spec.item_tier, spec.required_level, spec.max_durability) == (255, 0xffffffff, 65535)
        assert stats_summary(controller.draft, controller.stat_grid())[1]
        panel.property_controls['required_level'].setValue(17)
        assert controller.draft.required_level is None
        panel._reset()
        assert all(getattr(controller.draft, name) is None for name in panel.property_controls)
        assert [panel.property_controls[name].value() for name in panel.property_controls] == [3, 17, 430]
        controller.draft.item_tier = 8
        controller.draft.required_level = 4
        controller.draft.max_durability = 200
        controller.draft.reset_for_template(1001295)
        assert all(getattr(controller.draft, name) is None for name in panel.property_controls)
    finally:
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()


def test_unknown_durability_control_is_disabled_and_bad_properties_route_to_stats(tmp_path, app):
    controller, panel = controls(tmp_path)
    try:
        assert panel.property_controls['required_level'].isEnabled()
        assert not panel.property_controls['max_durability'].isEnabled()
        spec = spec_from_draft(controller.draft, controller.stat_grid())
        from dataclasses import replace
        issue = next(issue for issue in validate_spec(replace(spec, required_level=-1)) if issue.code == 'item_property.range')
        assert _workflow_step_for_issue(issue) == 3
    finally:
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()


def test_property_help_and_controls_have_real_translations_in_all_builtin_locales(tmp_path, app):
    import re
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.localization_catalogs_v2 import load_builtin_catalog
    from cdmw.ui.shell.about_documentation_en import CREATE_NEW_ITEM_SECTION

    help_text = re.search(r'<p>(Tier, Required level and Max durability.*?)</p>',
                          CREATE_NEW_ITEM_SECTION['html']).group(1)
    keys = ('Tier:', 'Required level:', 'Max durability:', 'item properties changed', help_text,
            'Raw game value. Returning to the template value restores inheritance. Disabled when the field layout is unknown; in-game effects are unverified.')
    assert len(BUILTIN_LANGUAGES) == 14
    for language in BUILTIN_LANGUAGES:
        translations = load_builtin_catalog(language.code)['translations']
        assert all(key in translations for key in keys)
        if language.code != 'en':
            assert all(translations[key] != key for key in keys)
    # Exercise the real formatter's recursive summary argument, beyond key parity.
    german = UiLocalizer(language_dir=tmp_path / 'languages', language_code='de')
    text, changed = stats_summary(NewItemDraft(item_tier=2), None, translate=german.translate_rendered)
    assert changed
    summary = german.translate_rendered(text)
    assert 'Gegenstandseigenschaften geändert' in summary
    assert german.translate_rendered(help_text) == load_builtin_catalog('de')['translations'][help_text]
