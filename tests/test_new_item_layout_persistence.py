"""Native actions round-trip through the retained workflow into the user cfg."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QSplitter, QVBoxLayout, QLabel

from cdmw.services.new_item_rust_protocol import PresentationProtocolError
from cdmw.ui.layout_persistence import native_dialog_layout
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from tests.test_new_item_rust_ui import _send, studio
from tests.test_ui_layout_persistence import layouts, settle


def test_all_new_item_workspaces_restore_native_split_gestures(studio, layouts):
    fixture, tab, bridge = studio
    policy, settings = layouts
    expected = {}
    tab.show_step(0)
    assert _send(bridge, tab.template_panel.matches, "resize_column", {"column": 0, "width": 347})["type"] == "ack"
    # These steps lazily construct Template, Identity, Model, Stats and Output.
    for step in (0, 1, 2, 3, 6):
        tab.show_step(step)
        settle()
        for split in tab.pages.currentWidget().findChildren(QSplitter):
            if not split.isVisibleTo(tab):
                continue
            values = [900 - 150 * i for i in range(split.count())]
            assert _send(bridge, split, "split", values)["type"] == "ack"
            expected[policy._splitter_key(split)] = values
    assert len(expected) >= 5
    policy.flush()
    policy.settings = QSettings(settings.fileName(), QSettings.IniFormat)
    restarted = fixture._tab()
    restarted.prefill_template(tab.controller.draft.template_key)
    restarted.resize(1440, 960)
    restarted.show()
    restarted_bridge = NewItemPresentationBridge(restarted)
    for step in (0, 1, 2, 3, 6):
        restarted.show_step(step)
        settle()
        restarted_bridge.snapshot()
        if step == 0:
            assert restarted.template_panel.matches.header().sectionSize(0) == 347
        for split in restarted.pages.currentWidget().findChildren(QSplitter):
            if not split.isVisibleTo(restarted):
                continue
            node = restarted_bridge.document.registry.current[restarted_bridge.document.registry.identify(split)]
            assert node["props"]["user_sized"]
            assert node["props"]["sizes"] == expected[policy._splitter_key(split)]


def test_native_dialog_drag_is_saved_without_changing_the_item(studio, layouts):
    _fixture, tab, _bridge = studio
    dialog = QDialog(tab)
    dialog.setObjectName("layout-test-dialog")
    QVBoxLayout(dialog).addWidget(QLabel("Dialog body"))
    dialog.show()
    bridge = NewItemPresentationBridge(tab, dialogs=lambda: [dialog])
    revision = tab.controller._draft_revision
    try:
        assert _send(bridge, dialog, "resize_dialog", [40, 60, 740, 500])["type"] == "ack"
        assert native_dialog_layout(dialog) == [40, 60, 740, 500]
        assert tab.controller._draft_revision == revision
        bridge.snapshot()
        node = bridge.document.registry.current[bridge.document.registry.identify(dialog)]
        assert node["props"]["saved_rect"] == [40, 60, 740, 500]
        with pytest.raises(PresentationProtocolError):
            _send(bridge, dialog, "resize_dialog", [0, 0, -1, 500])
        assert native_dialog_layout(dialog) == [40, 60, 740, 500]
    finally:
        dialog.close()
        dialog.deleteLater()
