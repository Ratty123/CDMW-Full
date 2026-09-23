"""Headless input-through-workflow checks for the optional Rust presentation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from cdmw.services.new_item_rust_protocol import (
    JsonLineReader, PROTOCOL, PresentationProtocolError, decode_message, encode_message,
)
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
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
