"""Input through the real Studio bridge for Effects, Distribution and overlays."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

from cdmw.services.archive_overlay_manager import InstalledOverlay
from cdmw.services.new_item_rust_protocol import PresentationProtocolError
from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from tests.test_new_item_rust_ui import studio, _input, _send


def test_effects_first_and_combined_experimental_editors_share_the_page(studio):
    _, tab, bridge = studio
    tab.show_step(4)
    panel = tab.perks_panel
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == [
        'Effects', 'Experimental Features (Perks, Sockets, Bonuses)']
    assert panel.tabs.currentWidget() is panel.effects_page
    assert panel.effects_workspace.library_toggle.isChecked()
    assert panel.effects_workspace.library_panel.isVisibleTo(panel)
    _send(bridge, panel.tabs, 'tab', 1)
    for widget in (panel.own_perks, panel.socket_editor.customize, panel.bonus_editor.customize):
        assert widget.isVisibleTo(tab)
    _send(bridge, panel.own_perks, 'toggle', True)
    _send(bridge, panel.socket_editor.customize, 'toggle', True)
    _send(bridge, panel.socket_editor.count, 'number', 4)
    assert len(tab.controller.draft.socket_slots) == 4
    cost = panel.socket_editor.costs.cellWidget(3, 2)
    _send(bridge, cost, 'text', '4200')
    assert tab.controller.draft.socket_slots[3].amount == 4200
    _send(bridge, panel.tabs, 'tab', 0)
    assert panel.effects_workspace.library_panel.isVisibleTo(panel)


def test_tab_corner_refresh_does_not_invalidate_navigation_but_tab_changes_do(studio):
    _, tab, bridge = studio
    tab.show_step(4)
    panel = tab.perks_panel
    action = _input(bridge, panel.tabs, 'tab', 1)
    panel.effects_workspace.selected_effect_label.setText('Changed preview label')
    bridge.dispatch(action)
    assert panel.tabs.currentWidget() is panel.perks_page
    action = _input(bridge, panel.tabs, 'tab', 0)
    panel.tabs.setTabEnabled(0, False)
    with pytest.raises(PresentationProtocolError, match='changed'):
        bridge.dispatch(action)


def test_rejected_input_is_logged_to_activity(studio):
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
    _, tab, bridge = studio
    tab.show_step(1)
    action = _input(bridge, tab.identity_panel.display_name, 'text', 'Old edit')
    tab.identity_panel.display_name.setText('New value')
    host = SimpleNamespace(_rust_mode=True, _closed=False, _stopping=False,
                           _bridge=bridge, workflow=tab, _send=Mock(), _publish_state=Mock())
    RustNewItemStudioTab._dispatch_input(host, action)
    assert host._send.call_args.args[0]['type'] == 'rejected'
    assert 'This control changed' in tab.log.toPlainText()
    assert tab.identity_panel.display_name.text() == 'New value'


def test_playback_projects_one_compact_row_for_rust_to_wrap_at_its_own_width():
    from PySide6.QtWidgets import QWidget
    from cdmw.ui.new_item.effect_playback import EffectPlaybackControls
    from cdmw.ui.new_item.rust_ui_document import PresentationDocument
    app = QApplication.instance() or QApplication([])
    placement = QWidget()
    placement.host = SimpleNamespace(set_effect_preview_controls=Mock())
    controls = EffectPlaybackControls(placement)
    controls._reflow(400)
    node = PresentationDocument().widget(controls, force=True)
    assert node['kind'] == 'row'
    assert len(node['children']) == 6
    assert not any(child['props']['grow_x'] for child in node['children'])
    placement.deleteLater()


def test_guided_effect_toolbar_and_disclosures_project_and_dispatch(studio, monkeypatch):
    from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
    from tests.test_effect_placement_dialog import _Host
    _, tab, bridge = studio
    tab.show_step(4)
    QApplication.processEvents()
    monkeypatch.setattr(EffectPlacementWorkspace, '_start_package', lambda self, **kwargs: None)
    workspace = tab.perks_panel.effects_workspace
    workspace._host_factory = _Host
    workspace._rebuild_preview()
    QApplication.processEvents()
    placement = workspace.placement
    assert placement is not None
    toolbar = bridge.document.widget(placement.guided_toolbar_panel, force=True)['children'][0]
    assert toolbar['kind'] == 'row'
    controls = toolbar['children']
    assert len(controls) == len(placement._guided_toolbar_buttons) + 7
    for node in controls[:8]:
        assert node['label'] == ''
        assert node['tooltip']
        assert node['props']['image']
    assert controls[-1]['label'] == 'Show gizmo'
    assert placement.preview_options_toggle.isChecked()
    assert placement.preview_options.isVisibleTo(tab)
    _send(bridge, placement.placement_toggle, 'toggle', False)
    assert placement.placement_controls.isHidden()
    _send(bridge, placement.placement_toggle, 'toggle', True)
    assert placement.placement_controls.isVisibleTo(tab)
    bonus = tab.perks_panel.bonus_editor
    columns = bridge.document.widget(bonus.values, force=True)['props']['columns']
    assert columns[0]['stretch']
    assert not columns[1]['stretch']


def test_distribution_tables_expand_and_edits_reach_the_same_draft(studio, tmp_path):
    from tests.test_new_item_acquisition_authoring import acquisition_game
    _, tab, bridge = studio
    _, snapshot = acquisition_game(tmp_path)
    tab.controller.snapshot = snapshot
    tab.controller.set_template(tab.controller.draft.template_key)
    tab.show_step(5)
    panel = tab.placement_panel
    assert not isinstance(tab.pages.currentWidget(), QScrollArea)
    assert panel.routes_view.tabText(1) == 'Recipes (experimental)'
    assert panel.routes_view.tabText(2) == 'Loot and rewards (experimental)'
    _send(bridge, panel.routes_view, 'tab', 1)
    editor = panel.recipes
    _send(bridge, editor.load, 'activate')
    _send(bridge, editor.customize, 'toggle', True)
    _send(bridge, editor.inputs, 'cell', {'path': [1], 'column': 2, 'text': '9'})
    assert tab.controller.draft.recipes[0].inputs[1].quantity == 9
    assert editor.inputs.height() > 200
    node = bridge.document.widget(editor.inputs, force=True)
    assert node['props']['total'] == 2
    assert editor.inputs.maximumHeight() > 10000
    _send(bridge, panel.routes_view, 'tab', 2)
    _send(bridge, panel.rewards.add, 'activate')
    assert tab.controller.draft.reward_acquisitions[0].consumer_item_key == 777001
    _send(bridge, panel.rewards.routes, 'select', {'path': [0], 'column': 0})
    _send(bridge, panel.rewards.remove, 'activate')
    assert not tab.controller.draft.reward_acquisitions


def test_overlay_selection_enables_review_and_drives_independent_installed_preview(studio, monkeypatch):
    _, tab, _ = studio
    monkeypatch.setattr(OverlayManagerDialog, 'refresh', lambda self: None)
    dialog = OverlayManagerDialog(tab.controller, 'owned-unused-root', None, tab)
    shown = Mock()
    monkeypatch.setattr(dialog.preview, 'show', shown)
    dialog.open()
    entries = (
        InstalledOverlay('a', 'First', (100, 101), '9000', 3, 1, compatibility_status='same'),
        InstalledOverlay('b', 'Second', (200,), '9000', 3, 2, compatibility_status='same'),
    )
    dialog._loaded(entries)
    bridge = NewItemPresentationBridge(tab, dialogs=lambda: (dialog,))
    try:
        _send(bridge, dialog.table, 'select', {'path': [1], 'column': 0})
        assert dialog.remove_button.isEnabled()
        assert dialog._selected_entry() is entries[1]
        columns = bridge.document.widget(dialog.table, force=True)['props']['columns']
        assert [column['text'] for column in columns if not column['hidden']] == [
            'Overlay', 'Items', 'Installed', 'Game check']
        assert 'Folder: 9000' in dialog.table.item(1, 0).toolTip()
        assert shown.call_args.kwargs['framing_key'] == ('b', 200)
        prepare = Mock()
        monkeypatch.setattr(dialog, '_run', prepare)
        _send(bridge, dialog.remove_button, 'activate')
        assert prepare.call_args.args[1] == dialog._review_removal
        _send(bridge, dialog.table, 'select', {'path': [0], 'column': 0})
        _send(bridge, dialog.preview_item, 'choose', 1)
        assert shown.call_args.kwargs['framing_key'] == ('a', 101)
        dialog.table.clearSelection()
        assert not dialog.remove_button.isEnabled()
        dialog._loaded((replace(entries[0], compatibility_status='unmounted'),))
        assert not dialog.remove_button.isEnabled()
        assert 'no longer mounted' in dialog.remove_button.toolTip()
        assert shown.call_args.args[0] is None
    finally:
        dialog.reject()
        QApplication.processEvents()
