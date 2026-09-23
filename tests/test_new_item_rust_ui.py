"""Headless input-through-workflow checks for the optional Rust presentation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from PySide6.QtCore import QEvent, QProcess, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from cdmw.services.new_item_rust_protocol import (
    JsonLineReader, PROTOCOL, PresentationProtocolError, decode_message, encode_message,
)
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_document import PresentationDocument, theme_snapshot
import test_new_item_studio_tab as _support

TEMPLATE = _support.TEMPLATE


@pytest.fixture
def studio():
    _support.TabTests.setUpClass()
    fixture = _support.TabTests("runTest")
    fixture.setUp()
    tab = fixture._tab()
    tab.prefill_template(TEMPLATE)
    tab.resize(1440, 960)
    tab.show()
    QApplication.processEvents()
    try:
        yield fixture, tab, NewItemPresentationBridge(tab)
    finally:
        fixture.tearDown()


def _input(bridge, widget, action, value=None, *, revision=None):
    bridge.snapshot()
    identifier = bridge.document.registry.identify(widget)
    node = bridge.document.registry.current[identifier]
    return {"protocol": PROTOCOL, "type": "input", "session": bridge.session,
            "request": bridge._last_request + 1, "control": identifier,
            "revision": node["revision"] if revision is None else revision,
            "action": action, "value": value}


def _send(bridge, widget, action, value=None):
    result = bridge.dispatch(_input(bridge, widget, action, value))
    QApplication.processEvents()
    return result


def test_json_lines_preserve_split_unicode_and_reject_oversize_duplicate_and_nonfinite():
    reader = JsonLineReader()
    packet = encode_message({"type": "test", "text": "中文 – Ö"})
    messages = []
    for byte in packet:
        messages.extend(reader.feed(bytes([byte])))
    assert messages[0]["text"] == "中文 – Ö"
    with pytest.raises(PresentationProtocolError, match="limit"):
        JsonLineReader(limit=5).feed(b"123456")
    for suffix in ('"x": NaN', '"x": 1, "x": 2'):
        with pytest.raises(PresentationProtocolError):
            decode_message(('{"protocol":"' + PROTOCOL + '",' + suffix + '}').encode())


def test_identity_actions_reach_existing_draft_and_invalidate_plan(studio):
    _, tab, bridge = studio
    tab.show_step(1)
    _send(bridge, tab.identity_panel.identifiers_toggle, "activate")
    before = tab.controller._draft_revision
    _send(bridge, tab.identity_panel.internal_name, "text", "Bridge_Blade")
    _send(bridge, tab.identity_panel.display_name, "text", "Bridge blade")
    assert tab.controller.draft.internal_name == "Bridge_Blade"
    assert "Bridge blade" in tab.controller.draft.display_names.values()
    assert tab.controller._draft_revision > before
    assert not tab.controller.has_current_plan


def test_underlying_parts_controls_reach_draft_through_rust_bridge(studio):
    from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
    _, tab, bridge = studio
    tab.show_step(2)
    _send(bridge, tab.model_panel.inspector_tabs, "tab", 1)
    editor = tab.model_panel.body_visibility_editor
    _send(bridge, editor.keep_skin, "toggle", True)
    assert tab.controller.current_spec().body_visibility == BodyVisibilityChoice(keep_skin=True)
    _send(bridge, editor.keep_hair, "toggle", True)
    assert tab.controller.current_spec().body_visibility == BodyVisibilityChoice(True, True)
    _send(bridge, editor.keep_skin, "toggle", False)
    _send(bridge, editor.keep_hair, "toggle", False)
    assert not tab.controller.current_spec().body_visibility.wanted


def test_overlay_folder_projects_numeric_typing_and_preserves_auto(studio):
    _, tab, bridge = studio
    tab.show_step(6)
    field = tab.output_panel.overlay_directory
    field.show()
    node = bridge.document.widget(field, force=True)
    assert node["props"]["text"] == ""
    assert node["props"]["placeholder"] == "Auto"
    assert node["props"]["digits_only"] is True
    # The real validator accepts each partial edit, including leading zeros.
    from cdmw.ui.new_item.rust_ui_actions import _set_text
    for value in ("0", "00", "003", "0036", "", "9", "99", "999", "9999", ""):
        _set_text(field, value)
        assert field.text() == value
    with pytest.raises(PresentationProtocolError, match="validator"):
        _set_text(field, "oops")


def test_same_controls_produce_same_spec_and_planned_bytes(studio):
    fixture, rust, bridge = studio
    classic = fixture._tab()
    classic.prefill_template(TEMPLATE)
    classic.show_step(1)
    rust.show_step(1)
    _send(bridge, rust.identity_panel.identifiers_toggle, "activate")
    classic.identity_panel.internal_name.setText("Equivalent_Blade")
    classic.identity_panel.display_name.setText("Equivalent blade")
    _send(bridge, rust.identity_panel.internal_name, "text", "Equivalent_Blade")
    _send(bridge, rust.identity_panel.display_name, "text", "Equivalent blade")
    assert rust.controller.current_spec() == classic.controller.current_spec()
    assert classic.controller.start_plan()
    rust.show_step(6)
    _send(bridge, rust.output_panel.build_button, "activate")
    assert classic.controller.has_current_plan and rust.controller.has_current_plan
    assert dict(rust.controller.plan.loose_files) == dict(classic.controller.plan.loose_files)
    assert [(entry.path, entry.payload_data) for entry in rust.controller.plan.additions] == [
        (entry.path, entry.payload_data) for entry in classic.controller.plan.additions]


def test_stats_cell_edit_uses_existing_validation_and_preserves_zero(studio):
    _, tab, bridge = studio
    tab.show_step(3)
    panel = tab._stats_panel
    _send(bridge, panel.table, "cell", {"path": [0], "column": 0, "text": "0"})
    assert tab.controller.draft.grid_values[(0, 0)] == 0
    bridge.snapshot()
    node = bridge.document.registry.current[bridge.document.registry.identify(panel.table)]
    assert node["props"]["rows"][0]["cells"][0]["text"] == "0"


def test_stats_and_prices_fill_the_workspace_and_keep_both_tables_editable(studio):
    _, tab, bridge = studio
    tab.show_step(3)
    panel = tab.stats_panel
    heights = []
    for height in (720, 1080):
        tab.resize(1440, height)
        for _ in range(3):
            QApplication.processEvents()
        for table in (panel.table, panel.price_table):
            assert table.height() > tab.pages.height() * 0.5
            assert table.visualItemRect(table.item(0, 0)).intersects(table.viewport().rect())
        heights.append((panel.table.height(), panel.price_table.height()))
    assert all(after > before + 250 for before, after in zip(*heights))
    _send(bridge, panel.table, "cell", {"path": [0], "column": 0, "text": "12345"})
    price_key = panel._grid.price_items[0][0]
    _send(bridge, panel.price_table, "cell", {"path": [0], "column": 1, "text": "0"})
    assert tab.controller.draft.grid_values[(0, 0)] == 12345
    assert tab.controller.draft.price_values[price_key] == 0
    bridge.snapshot()
    registry = bridge.document.registry
    assert registry.current[registry.identify(panel.views)]["kind"] == "column"
    assert registry.current[registry.identify(panel.tables_splitter)]["kind"] == "split"
    for table in (panel.table, panel.price_table):
        node = registry.current[registry.identify(table)]
        assert node["stretch"] == 1
        assert node["props"]["rows"]
    assert not any(node["label"] == "Recipes…" for node in registry.current.values())
    tab.resize(1280, 720)
    panel.advanced_toggle.setChecked(True)
    for _ in range(3):
        QApplication.processEvents()
    assert tab.pages.currentWidget().horizontalScrollBar().maximum() == 0
    assert panel.table.viewport().height() >= panel.table.rowHeight(0)
    assert panel.price_table.viewport().height() >= panel.price_table.rowHeight(0)
    bridge.snapshot()
    assert registry.current[registry.identify(panel.advanced_scroll)]["kind"] == "scroll"


def test_outdated_disabled_hidden_and_wrong_session_inputs_are_rejected(studio):
    _, tab, bridge = studio
    tab.show_step(1)
    target = tab.identity_panel.display_name
    old = _input(bridge, target, "text", "Old queued edit")
    target.setText("Newer value")
    with pytest.raises(PresentationProtocolError, match="changed"):
        bridge.dispatch(old)
    disabled = _input(bridge, target, "text", "Disabled edit")
    target.setEnabled(False)
    with pytest.raises(PresentationProtocolError):
        bridge.dispatch(disabled)
    target.setEnabled(True)
    hidden = _input(bridge, target, "text", "Hidden edit")
    tab.show_step(0)
    with pytest.raises(PresentationProtocolError, match="no longer"):
        bridge.dispatch(hidden)
    tab.show_step(1)
    wrong = _input(bridge, target, "text", "Foreign edit")
    wrong["session"] = "another-session"
    with pytest.raises(PresentationProtocolError, match="session"):
        bridge.dispatch(wrong)
    assert target.text() == "Newer value"


def test_visible_workflow_and_corner_controls_are_projected(studio):
    _, tab, bridge = studio
    for step in range(7):
        tab.show_step(step)
        QApplication.processEvents()
        state = bridge.snapshot()
        assert not state["unsupported"], state["unsupported"]
        assert bridge.document.registry.identify(tab.steps) in bridge.document.registry.current
        assert bridge.document.registry.identify(tab.back_button) in bridge.document.registry.current
        assert (bridge.document.registry.identify(tab.continue_button) in bridge.document.registry.current) == (not tab.continue_button.isHidden())
    tab.show_step(4)
    QApplication.processEvents()
    bridge.snapshot()
    assert bridge.document.registry.identify(tab._perks_panel.effects_workspace.library_toggle) in bridge.document.registry.current


def test_numeric_zero_and_model_replacement_are_preserved_and_revisioned():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    table = QTableWidget(1, 1)
    item = QTableWidgetItem()
    item.setData(Qt.DisplayRole, 0)
    table.setItem(0, 0, item)
    layout.addWidget(table)
    root.show()
    app.processEvents()
    document = PresentationDocument()
    try:
        document.snapshot(root)
        identifier = document.registry.identify(table)
        old = document.registry.current[identifier]
        assert old["props"]["rows"][0]["cells"][0]["text"] == "0"
        table.setItem(0, 0, QTableWidgetItem("Replacement"))
        document.snapshot(root)
        assert document.registry.current[identifier]["revision"] > old["revision"]
    finally:
        root.close()
        root.deleteLater()


def test_switching_presentation_preserves_the_same_live_workflow(studio):
    _, tab, _ = studio
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab

    with patch.object(RustNewItemStudioTab, "_start_prepare"):
        experimental = RustNewItemStudioTab(workflow=tab)
        try:
            tab.controller.draft.internal_name = "Keep_This_Draft"
            original = tab.controller.draft
            experimental.use_rust()
            assert tab.testAttribute(Qt.WA_DontShowOnScreen)
            experimental.use_classic()
            assert not tab.testAttribute(Qt.WA_DontShowOnScreen)
            assert experimental.workflow is tab
            assert experimental.controller.draft is original
            assert original.internal_name == "Keep_This_Draft"
        finally:
            # Return fixture ownership before the experimental container is destroyed.
            tab.setParent(None)
            experimental.request_shutdown()
            experimental.deleteLater()


@pytest.mark.parametrize("rust", [False, True], ids=["classic", "rust"])
def test_shell_model_loading_uses_compact_status_bar_and_keeps_cancel(studio, rust):
    from PySide6.QtWidgets import QLabel, QProgressBar
    from shiboken6 import isValid

    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
    from cdmw.ui.shell.compact.status_strip import CompactBottomStatusStrip
    from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin

    fixture, _, _ = studio
    workflow = fixture._tab()
    strip = CompactBottomStatusStrip(QLabel("Ready"), QProgressBar(), QLabel("Cache: Healthy"))
    owner = SimpleNamespace(
        compact_workspace=SimpleNamespace(status_strip=strip),
        app_context=SimpleNamespace(services=SimpleNamespace(new_items=None)),
        set_status_message=Mock(),
        textures=SimpleNamespace(_show_archive_browser_from_texture_editor=Mock()),
    )
    key = "new_item_rust_studio" if rust else "new_item_studio"
    constructor = "cdmw.ui.new_item.rust_ui_tab.NewItemStudioTab" if rust else "cdmw.ui.new_item.NewItemStudioTab"
    factory = (ShellToolTabsMixin._create_new_item_rust_studio_tab if rust
               else ShellToolTabsMixin._create_new_item_studio_tab)
    root = QWidget()
    layout = QVBoxLayout(root)

    def settle():
        QApplication.processEvents()
        QApplication.processEvents()

    with patch(constructor, return_value=workflow), \
            patch.object(workflow.controller, "persist_issued_identities"), \
            patch.object(RustNewItemStudioTab, "_start_prepare"):
        presentation = factory(owner)
        assert not workflow._panels_built
        workflow.prefill_template(TEMPLATE)
        workflow.show_step(2)
        panel = workflow.model_panel
        banner = panel.operation_banner
        layout.addWidget(presentation, 1)
        layout.addWidget(strip)
        strip.set_active_tool(key)
        root.resize(1280, 720)
        root.show()
        try:
            panel.preview.status_changed.emit("Full textures loaded.")
            settle()
            assert strip.isAncestorOf(banner)
            assert panel.model_icon_column.layout().indexOf(banner) == -1
            inspector_height = panel.model_icon_scroll.height()
            strip_height = strip.height()
            assert strip_height == 42
            assert banner.parentWidget().isHidden()

            controller = workflow.controller
            controller._lane = "model_import"
            controller.busy_changed.emit(True)
            detail = "Preparing imported model textures and materials " * 8
            controller.operation_progress.emit("model_import", 3, 8, detail)
            settle()
            assert banner.isVisible()
            assert panel.operation_spinner._timer.isActive()
            assert (panel.busy_bar.maximum(), panel.busy_bar.value()) == (8, 3)
            assert not panel.operation_label.wordWrap()
            assert panel.operation_label.toolTip() == detail
            assert panel.operation_label.width() > 40
            assert banner.parentWidget().x() > strip.cache_label.geometry().right()
            assert panel.cancel_operation_button.isVisible()
            assert panel.model_icon_scroll.height() == inspector_height
            assert strip.height() == strip_height
            assert strip.ready_label.text() == "Ready"
            assert strip.cache_label.text() == "Cache: Healthy"
            bridge = NewItemPresentationBridge(workflow)
            bridge.snapshot()
            assert bridge.document.registry.identify(banner) not in bridge.document.registry.current
            if rust:
                presentation.use_classic()
                presentation.use_rust()
                assert strip.isAncestorOf(banner)
                assert banner.isVisible()

            with patch.object(controller, "cancel_operation", return_value=True) as cancel:
                panel.cancel_operation_button.click()
                cancel.assert_called_once_with("model_import")
                assert not panel.cancel_operation_button.isEnabled()
                assert panel.operation_label.toolTip() == "Cancelling…"
            controller._lane = ""
            controller.busy_changed.emit(False)
            panel.preview.status_changed.emit("Fast textures are visible; loading full textures…")
            settle()
            assert banner.isVisible()
            assert not panel.cancel_operation_button.isVisible()
            assert panel.operation_label.toolTip() == "Fast textures are visible; loading full textures…"
            strip.set_active_tool("archive")
            assert not banner.isVisible()
            strip.set_active_tool(key)
            assert banner.isVisible()
            panel.preview.status_changed.emit("Full textures loaded.")
            settle()
            assert banner.parentWidget().isHidden()
            assert not panel.operation_spinner._timer.isActive()
        finally:
            root.hide()
            presentation.request_shutdown()
            workflow.close()
            workflow.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert not isValid(banner)
            root.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_prewarm_publishes_hidden_state_then_idles_and_does_not_restart(studio):
    _, tab, _ = studio
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab

    with patch.object(RustNewItemStudioTab, "_start_prepare") as prepare:
        experimental = RustNewItemStudioTab(workflow=tab)
        messages = []
        experimental._send = messages.append
        try:
            experimental.prewarm()
            assert prepare.call_count == 1
            experimental._bridge = NewItemPresentationBridge(tab)
            experimental._ready = True
            experimental._timer.start()
            experimental._publish_state()
            assert messages[-1]["type"] == "state"
            experimental._handle_message({"type": "state_received",
                "session": experimental._bridge.session, "generation": experimental._sent_generation})
            assert not experimental._prewarming
            assert not experimental._timer.isActive()
            assert not tab.isVisible()
            experimental.prewarm()
            experimental.show()
            QApplication.processEvents()
            assert prepare.call_count == 1
            assert experimental._timer.isActive()
            experimental.request_shutdown()
            experimental.prewarm()
            assert prepare.call_count == 1
            assert not experimental._timer.isActive()
        finally:
            experimental.request_shutdown()
            tab.setParent(None)
            experimental.deleteLater()


def test_prewarm_failure_is_retained_without_a_background_error_notification(studio):
    _, tab, _ = studio
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab

    with patch.object(RustNewItemStudioTab, "_start_prepare"):
        experimental = RustNewItemStudioTab(workflow=tab)
        errors = []
        experimental.status_message_requested.connect(lambda *args: errors.append(args))
        try:
            experimental.prewarm()
            experimental._fail("Owned startup failure")
            assert experimental._host._status_label.text() == "Owned startup failure"
            assert not errors
            assert not experimental._prewarming
            assert not experimental._timer.isActive()
        finally:
            experimental.request_shutdown()
            tab.setParent(None)
            experimental.deleteLater()


def test_stalled_renderer_recovers_without_waiting_on_its_window(studio):
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab

    _, tab, _ = studio
    process = Mock(spec=QProcess)
    process.state.return_value = QProcess.Running
    process.bytesToWrite.return_value = 0
    api = SimpleNamespace(
        IsWindow=lambda _hwnd: True,
        ShowWindow=Mock(side_effect=AssertionError("Synchronous hide waits on the stalled renderer")),
        ShowWindowAsync=Mock(return_value=True),
        SetFocus=Mock(side_effect=AssertionError("The error page must not focus the stalled child")),
    )
    with patch.object(RustNewItemStudioTab, "_start_prepare"), \
            patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        experimental = RustNewItemStudioTab(workflow=tab)
        try:
            experimental.use_rust()
            experimental._bridge = NewItemPresentationBridge(tab)
            experimental._process = process
            experimental._ready = True
            experimental._host._child_hwnd = 123
            experimental._sent_generation = 2
            experimental._received_generation = 1
            experimental._state_delivery = SimpleNamespace(isValid=lambda: True, elapsed=lambda: 10001)
            draft = tab.controller.draft
            experimental._timer.start()

            experimental._publish_state()

            api.ShowWindow.assert_not_called()
            assert api.ShowWindowAsync.call_args.args[1] == 0
            assert "stopped acknowledging" in experimental._host._status_label.text()
            assert not experimental._ready
            assert not experimental._timer.isActive()
            assert experimental._stop_deadline.isActive()
            assert decode_message(process.write.call_args.args[0])["type"] == "shutdown"
            experimental._host.event(QEvent(QEvent.Type.FocusIn))
            api.SetFocus.assert_not_called()
            beats = []
            QTimer.singleShot(0, lambda: beats.append(True))
            QApplication.processEvents()
            assert beats == [True]

            experimental._stop_deadline.timeout.emit()
            process.kill.assert_called_once()
            process.state.return_value = QProcess.NotRunning
            experimental._process_finished()
            experimental.use_classic()
            assert experimental.controller.draft is draft
            assert experimental._pages.currentWidget() is experimental._classic_page
            assert experimental._host.child_hwnd == 0
            assert experimental._process is None
        finally:
            experimental._host._child_hwnd = 0
            experimental._process = None
            experimental.request_shutdown()
            tab.setParent(None)
            experimental.deleteLater()


@pytest.mark.parametrize("font_pixels", [11, 13, 22])
def test_theme_snapshot_retains_small_fonts_and_active_button_states(font_pixels):
    from cdmw.ui.theme_schemes import UI_THEME_SCHEMES
    from cdmw.ui.themes import build_app_palette

    app = QApplication.instance() or QApplication([])
    previous_theme = app.property("_cdmw_theme_key")
    widget = QWidget()
    font = QFont(widget.font())
    font.setPixelSize(font_pixels)
    widget.setFont(font)
    try:
        for key, palette in UI_THEME_SCHEMES.items():
            app.setProperty("_cdmw_theme_key", key)
            widget.setPalette(build_app_palette(key))
            theme = theme_snapshot(widget)
            assert theme["font_pixels"] == font_pixels
            assert theme["background"] == palette["window"]
            for name in ("button", "button_hover", "button_pressed", "button_border"):
                assert theme[name] == palette[name]
    finally:
        app.setProperty("_cdmw_theme_key", previous_theme)
        widget.deleteLater()


def test_list_widget_and_readonly_table_preserve_selection_and_edit_contract():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    choices = QListWidget()
    choices.addItems(["First", "Second", "Third"])
    choices.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    layout.addWidget(choices)
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("Review only"))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(table)
    root.show()
    app.processEvents()
    bridge = NewItemPresentationBridge(root)
    try:
        _send(bridge, choices, "select", {"path": [0], "mode": "click"})
        _send(bridge, choices, "select", {"path": [2], "mode": "range"})
        assert [item.text() for item in choices.selectedItems()] == ["First", "Second", "Third"]
        _send(bridge, choices, "key", {"key": "Home"})
        assert choices.currentRow() == 0
        _send(bridge, choices, "key", {"key": "Down"})
        assert choices.currentRow() == 1
        state = bridge.snapshot()
        assert not state["unsupported"]
        node = bridge.document.registry.current[bridge.document.registry.identify(table)]
        assert not node["props"]["rows"][0]["cells"][0]["editable"]
        with pytest.raises(PresentationProtocolError, match="read-only"):
            _send(bridge, table, "cell", {"path": [0], "column": 0, "text": "Changed"})
        assert table.item(0, 0).text() == "Review only"
    finally:
        root.close()
        root.deleteLater()


def test_modal_confirmation_is_projected_and_returns_original_no_result(studio):
    _, workflow, _ = studio
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    dialogs = PresentationDialogs(workflow, workflow)
    dialogs.active = True
    bridge = NewItemPresentationBridge(workflow, dialogs=dialogs.dialogs, native_modal=dialogs.native_modal)
    problems = []

    def decline():
        try:
            dialog = dialogs.dialogs()[-1]
            assert isinstance(dialog, QMessageBox)
            assert dialog.testAttribute(Qt.WA_DontShowOnScreen)
            assert QApplication.activeModalWidget() is None
            assert not bridge.snapshot()["unsupported"]
            with pytest.raises(PresentationProtocolError, match="active dialog"):
                _send(bridge, workflow.continue_button, "activate")
            _send(bridge, dialog.button(QMessageBox.No), "activate")
        except BaseException as error:
            problems.append(error)
            for dialog in dialogs.dialogs():
                dialog.reject()

    # Exercise the actual nested exec loop used by install confirmation. There
    # is no mutation service in this test and no real archive is touched.
    QTimer.singleShot(0, decline)
    try:
        result = QMessageBox.question(workflow, "Owned fixture confirmation", "Apply this owned fixture?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        assert not problems, problems
        assert result == QMessageBox.No
        assert not dialogs.dialogs()
    finally:
        dialogs.close()


def test_dialog_operation_row_stays_with_close_and_help_is_on_the_control(studio):
    _, workflow, _ = studio
    from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
    dialog = ModMergeDialog(workflow.controller, parent=workflow)
    try:
        dialog.show()
        QApplication.processEvents()
        bridge = NewItemPresentationBridge(workflow, dialogs=lambda: (dialog,))
        state = bridge.snapshot()
        assert not state["unsupported"]

        def action_rows(node):
            if node["props"].get("dialog_actions"):
                yield node
                return
            for child in node["children"]:
                yield from action_rows(child)

        rows = list(action_rows(state["dialogs"][0]))
        assert len(rows) == 1 and rows[0]["kind"] == "row"

        def buttons(node):
            if node["kind"] == "button":
                yield node["label"]
            for child in node["children"]:
                yield from buttons(child)

        assert set(buttons(rows[0])) == {"Check compatibility", "Write merged mod", "Close"}
        assert "Independent changes" in dialog.scan_button.toolTip()
    finally:
        dialog.close()
        QApplication.processEvents()


def test_persistent_workspaces_share_allocations_and_refuse_concurrent_plans(studio):
    fixture, first, _ = studio
    second = fixture._tab()
    second.prefill_template(TEMPLATE)
    first.identity_panel.internal_name.setText("First_Parallel_Item")
    second.identity_panel.internal_name.setText("Second_Parallel_Item")
    first.identity_panel.display_name.setText("First parallel item")
    second.identity_panel.display_name.setText("Second parallel item")
    settings = {}

    class Settings:
        def value(self, name, fallback=""):
            return settings.get(name, fallback)
        def setValue(self, name, value):
            settings[name] = value

    with patch.object(type(first.controller), "_settings", lambda _: Settings()):
        first.controller.persist_issued_identities()
        second.controller.persist_issued_identities()
        first.controller.remember_issued_identity(1990012, "first_stem")
        assert 1990012 in second.controller.issued_keys
        second.controller.remember_issued_identity(1990013, "second_stem")
        assert {"first_stem", "second_stem"} <= first.controller.issued_stems
        before = second.controller._draft_revision
        first.controller._thread, first.controller._lane = object(), "plan"
        try:
            assert not second.controller.start_plan()
            assert second.controller._draft_revision == before
        finally:
            first.controller._thread, first.controller._lane = None, ""
        assert first.controller.start_plan(), first.controller.validate()
        assert second.controller.start_plan(), second.controller.validate()
        assert first.controller.plan.spec.item_key != second.controller.plan.spec.item_key


def test_busy_spinner_and_rich_status_keep_native_semantics(studio):
    _, tab, bridge = studio
    from cdmw.ui.new_item.panels_model import _BusySpinner
    from cdmw.ui.new_item.rust_ui_document import rich_spans
    spinner = _BusySpinner()
    try:
        document = PresentationDocument()
        assert document.widget(spinner, force=True)["kind"] == "progress"
        spans = rich_spans('<span style="color:#dd2200">Blocked</span> <b>Review</b>')
        assert any(span.get("color") == "#dd2200" for span in spans)
        assert any(span.get("bold") for span in spans)
    finally:
        spinner.deleteLater()


def test_horizontal_search_stretch_does_not_consume_table_height(studio):
    _, tab, bridge = studio
    bridge.snapshot()
    identifier = bridge.document.registry.identify(tab.template_panel.filter_edit)
    node = bridge.document.registry.current[identifier]
    assert node["props"]["grow_x"]
    assert not node.get("stretch", 0)
    header = tab.template_panel.matches.header()
    assert header.sectionSize(0) > header.sectionSize(1)


def test_native_preview_status_uses_one_stable_portal(studio):
    _, tab, bridge = studio
    preview = tab.model_panel.preview
    assert preview._ensure_host()
    host = preview.host
    before = bridge.document.widget(host, force=True)
    assert before["kind"] == "viewport"
    assert not before["children"]
    assert bridge.document.portals[before["id"]] is host
    host._status_panel.hide()
    host._resident_banner.show()
    after = bridge.document.widget(host, force=True)
    assert after == before


def test_template_deliberate_selection_uses_existing_immediate_click_handler(studio):
    _, tab, bridge = studio
    panel = tab.template_panel
    _send(bridge, panel.filter_edit, "text", "")
    target = next(row for row in range(panel.matches.topLevelItemCount())
                  if panel.matches.topLevelItem(row).data(0, Qt.UserRole) == _support.OTHER)
    taken = []
    with patch.object(tab.controller, "set_template", taken.append):
        _send(bridge, panel.matches, "select", {"path": [target], "column": 0, "mode": "click"})
    assert taken == [_support.OTHER]
    assert not panel._pick_timer.isActive()


def test_perk_add_and_remove_route_through_the_same_double_click_and_button_handlers(studio):
    _, tab, bridge = studio
    tab.show_step(4)
    panel = tab.perks_panel
    _send(bridge, panel.tabs, "tab", 0)
    _send(bridge, panel.own_perks, "toggle", True)
    _send(bridge, panel.perk_filter, "text", "Swift")
    before = tuple(tab.controller.draft.socket_items or ())
    _send(bridge, panel.perk_results, "select", {"path": [0], "column": 0, "mode": "double"})
    assert tuple(tab.controller.draft.socket_items or ()) == (*before, 1002812)
    _send(bridge, panel.chosen, "select", {"path": [panel.chosen.count() - 1], "mode": "click"})
    _send(bridge, panel.remove_button, "activate")
    assert tuple(tab.controller.draft.socket_items or ()) == before


def test_context_menu_returns_the_original_selected_action(studio):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    _, workflow, _ = studio
    dialogs = PresentationDialogs(workflow, workflow)
    dialogs.active = True
    bridge = NewItemPresentationBridge(workflow, dialogs=dialogs.dialogs)
    menu = QMenu(workflow)
    selected = menu.addAction("Owned selection")
    problems = []

    def choose():
        try:
            assert menu in dialogs.dialogs()
            assert QApplication.activePopupWidget() is None
            assert not bridge.snapshot()["unsupported"]
            _send(bridge, selected, "activate")
        except BaseException as error:
            problems.append(error)
            menu.close()

    QTimer.singleShot(0, choose)
    try:
        result = menu.exec(QPoint(0, 0))
        assert not problems, problems
        assert result is selected
    finally:
        dialogs.close()
        menu.deleteLater()


def test_template_paging_keeps_results_until_the_last_loaded_page(studio):
    from cdmw.ui.new_item.panels_template import _MATCH_PAGE_SIZE
    _, workflow, bridge = studio
    panel = workflow.template_panel
    panel._preferred_match_key = -1
    panel._requested_row_count = 300
    panel._show_matches([(TEMPLATE, f"fixture_{index:04}", f"Fixture {index}", "OneHandSword")
                         for index in range(900)])
    QApplication.processEvents()
    search = panel.filter_edit.text()
    bridge.snapshot()
    identifier = bridge.document.registry.identify(panel.matches)

    def props():
        bridge.snapshot()
        return bridge.document.registry.current[identifier]["props"]

    assert (props()["offset"], props()["end"], props()["total"]) == (0, 128, 300)
    _send(bridge, panel.matches, "range", {"offset": 128})
    assert (props()["offset"], props()["end"], props()["total"]) == (128, 256, 300)
    _send(bridge, panel.matches, "range", {"offset": 256, "end": True})
    total = 300 + _MATCH_PAGE_SIZE
    assert (props()["offset"], props()["end"], props()["total"]) == (256, min(384, total), total)
    assert panel.filter_edit.text() == search
    assert panel.matches.topLevelItem(256).text(0) == "fixture_0256"
    assert workflow.controller.draft.template_key == TEMPLATE


def test_expanded_tree_budget_preserves_paging_for_later_branches():
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
    app = QApplication.instance() or QApplication([])
    tree = QTreeWidget()
    for i in range(200):
        branch = QTreeWidgetItem(tree, [f"Branch {i}"])
        if i == 0:
            for j in range(200):
                QTreeWidgetItem(branch, [f"Child {j}"])
    tree.topLevelItem(0).setExpanded(True)
    tree.show()
    app.processEvents()
    bridge = NewItemPresentationBridge(tree)
    try:
        bridge.snapshot()
        identifier = bridge.document.registry.identify(tree)
        props = bridge.document.registry.current[identifier]["props"]
        assert props["end"] == 1
        assert len(props["rows"][0]["nested"]["rows"]) == 127
        _send(bridge, tree, "range", {"offset": 127, "parent": [0]})
        bridge.snapshot()
        props = bridge.document.registry.current[identifier]["props"]
        assert props["rows"][0]["nested"]["rows"][0]["path"] == [0, 127]
        _send(bridge, tree, "range", {"offset": 1})
        bridge.snapshot()
        props = bridge.document.registry.current[identifier]["props"]
        assert props["rows"][0]["path"] == [1]
        assert len(props["rows"]) == 128
    finally:
        tree.close()
        tree.deleteLater()


def test_splitter_and_header_resize_and_large_description_keep_original_values():
    from PySide6.QtWidgets import QHeaderView, QPlainTextEdit, QSplitter
    app = QApplication.instance() or QApplication([])
    root = QSplitter(Qt.Horizontal)
    text = QPlainTextEdit()
    table = QTableWidget(1, 2)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    root.addWidget(text)
    root.addWidget(table)
    root.resize(1000, 600)
    root.show()
    app.processEvents()
    bridge = NewItemPresentationBridge(root)
    try:
        _send(bridge, root, "split", [600, 400])
        assert 1.4 < root.sizes()[0] / root.sizes()[1] < 1.6
        _send(bridge, table, "resize_column", {"column": 1, "width": 237})
        assert table.columnWidth(1) == 237
        description = "中文 item description\n" * 5000
        _send(bridge, text, "text", description)
        assert text.toPlainText() == description
        assert not bridge.snapshot()["unsupported"]
    finally:
        root.close()
        root.deleteLater()


def test_icon_crop_uses_source_pixels_and_the_original_accept_reset_handlers(studio):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QDialog
    from cdmw.ui.archive_browser.static_replacement_icon_selection import AlignmentIconSelectionDialog
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    _,workflow,_ = studio
    dialogs = PresentationDialogs(workflow,workflow)
    dialogs.active = True
    bridge = NewItemPresentationBridge(workflow,dialogs=dialogs.dialogs)
    image = QImage(800,600,QImage.Format_RGBA8888)
    image.fill(Qt.blue)
    dialog = AlignmentIconSelectionDialog(image,workflow)
    try:
        dialog.show()
        QApplication.processEvents()
        assert not bridge.snapshot()["unsupported"]
        _send(bridge,dialog.selector,"crop",[100,80,400,300])
        assert dialog.selected_source_rect() == (100,80,400,300)
        with pytest.raises(PresentationProtocolError,match="inside"):
            _send(bridge,dialog.selector,"crop",[700,500,400,300])
        _send(bridge,dialog.reset_button,"activate")
        assert dialog.selected_source_rect() == (0,0,800,600)
        _send(bridge,dialog.selector,"crop",[100,80,400,300])
        _send(bridge,dialog.use_selection_button,"activate")
        assert dialog.result() == QDialog.Accepted
        assert dialog.selected_source_rect() == (100,80,400,300)
    finally:
        dialogs.close()
        dialog.deleteLater()


def test_retired_preview_barrier_accepts_a_late_callback_after_process_deletion():
    from types import SimpleNamespace
    from PySide6.QtCore import QObject, QProcess
    from shiboken6 import delete, isValid
    from cdmw.workers.new_item_cleanup_worker import preview_process_barrier
    app = QApplication.instance() or QApplication([])
    class QueuedSignal:
        def __init__(self): self.callbacks = []
        def connect(self, callback): self.callbacks.append(callback)
    class Process(QObject):
        def __init__(self):
            super().__init__()
            self.finished = QueuedSignal()
            self.errorOccurred = QueuedSignal()
        def state(self):
            assert isValid(self), "A queued callback read a deleted process"
            return QProcess.Running
    process = Process()
    queued = process.finished.callbacks
    ready = preview_process_barrier(SimpleNamespace(findChildren=lambda _: [process]))
    assert not ready.is_set()
    delete(process)
    assert ready.is_set()
    queued[0](0, QProcess.NormalExit)
    assert ready.is_set()


def test_custom_dialog_button_labels_use_the_active_language_without_changing_handlers(tmp_path):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance() or QApplication([])
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="de")
    app.setProperty("_cdmw_ui_localizer", localizer)
    dialog = QDialog()
    box = QDialogButtonBox(dialog)
    button = box.addButton("Use Selection", QDialogButtonBox.AcceptRole)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    QVBoxLayout(dialog).addWidget(box)
    dialog.show()
    try:
        bridge = NewItemPresentationBridge(dialog)
        bridge.snapshot()
        node = bridge.document.registry.current[bridge.document.registry.identify(button)]
        assert node["label"] == "Auswahl verwenden"
        assert button.text() == "Use Selection"
        _send(bridge, button, "activate")
        assert clicked == [True]
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        dialog.close()
        dialog.deleteLater()


def test_preview_portal_scales_clips_and_restores_the_original_layout():
    from types import SimpleNamespace
    from PySide6.QtCore import QRect
    from cdmw.ui.new_item.rust_ui_portals import PreviewPortals
    app = QApplication.instance() or QApplication([])
    class ScaledHost(QWidget):
        def devicePixelRatioF(self): return 2.0
    host = ScaledHost()
    host.resize(800, 600)
    original = QWidget()
    layout = QVBoxLayout(original)
    layout.addWidget(QPushButton("Before"))
    viewport = QWidget()
    viewport.setMinimumSize(40, 30)
    layout.addWidget(viewport)
    layout.addWidget(QPushButton("After"))
    portals = PreviewPortals(host)
    document = SimpleNamespace(portals={"viewport": viewport})
    message = {"pixels_per_point": 3.0, "portals": [
        {"id":"viewport", "rect":[20,30,100,80], "clip":[40,30,40,60]}]}
    try:
        portals.update(document, message)
        assert viewport.parentWidget() is host
        assert viewport.geometry() == QRect(30,45,150,120)
        assert viewport.mask().boundingRect() == QRect(30,0,60,90)
        message["portals"][0]["occlusions"] = [[50, 40, 10, 20]]
        portals.update(document, message)
        from PySide6.QtCore import QPoint
        assert not viewport.mask().contains(QPoint(50, 25))
        assert viewport.mask().contains(QPoint(35, 25))
        message["portals"][0]["occlusions"] = [[0, 0, 800, 600]]
        portals.update(document, message)
        assert viewport.isHidden()  # An empty Qt mask would otherwise expose it all.
        message["portals"][0]["occlusions"] = []
        portals.update(document, message)
        assert not viewport.isHidden()
        assert viewport.mask().contains(QPoint(50, 25))
        placeholder = layout.itemAt(1).widget()
        assert placeholder.minimumSize() == viewport.minimumSize()
        projection = PresentationDocument()
        assert projection.widget(placeholder)["id"] == projection.registry.identify(viewport)
        portals.update(document, {"pixels_per_point":3.0,"portals":[]})
        assert viewport.isHidden()
        portals.restore()
        assert viewport.parentWidget() is original and layout.indexOf(viewport) == 1
        assert viewport.mask().isEmpty()
        with pytest.raises(PresentationProtocolError,match="scale"):
            portals.update(document,{"pixels_per_point":float("nan"),"portals":[]})
    finally:
        portals.restore()
        host.deleteLater()
        original.deleteLater()
