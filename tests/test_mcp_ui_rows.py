"""app_ui_act on lists, tables and trees: several rows, a row's tick, a cell, a branch, a key."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from cdmw.mcp.errors import ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.ui_tree import act, describe, effect_of_action


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Page(QWidget):
    def __init__(self):
        super().__init__()
        self.seen: list[tuple] = []
        layout = QVBoxLayout(self)
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.addItems([f"texture_{number}.dds" for number in range(6)])
        self.single = QListWidget()
        self.single.addItems(["one", "two"])
        self.rows = QTableWidget(3, 2)
        self.rows.setHorizontalHeaderLabels(["File", "Value"])
        for number in range(3):
            name = QTableWidgetItem(f"row_{number}")
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            name.setCheckState(Qt.CheckState.Unchecked)
            self.rows.setItem(number, 0, name)
            value = QTableWidgetItem()
            value.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsSelectable)
            value.setData(Qt.ItemDataRole.EditRole, number * 10)
            self.rows.setItem(number, 1, value)
        self.rows.itemChanged.connect(lambda item: self.seen.append(("changed", item.row(), item.column())))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Object"])
        parent = QTreeWidgetItem(self.tree, ["castle"])
        QTreeWidgetItem(parent, ["gate"])
        QTreeWidgetItem(self.tree, ["leaf"])
        self.tree.itemExpanded.connect(lambda item: self.seen.append(("expanded", item.text(0))))
        clear = QShortcut(QKeySequence("Esc"), self)
        clear.activated.connect(lambda: self.seen.append(("esc",)))
        for widget in (self.files, self.single, self.rows, self.tree):
            layout.addWidget(widget)


@pytest.fixture
def page(app):
    widget = _Page()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_several_rows_are_selected_and_extended(page):
    act(page.files, "select", rows=[1, "texture_3.dds"])
    assert sorted(item.text() for item in page.files.selectedItems()) == ["texture_1.dds", "texture_3.dds"]
    act(page.files, "select", rows=[5], extend=True)
    assert len(page.files.selectedItems()) == 3
    act(page.files, "select", rows=[0])
    assert [item.text() for item in page.files.selectedItems()] == ["texture_0.dds"]


def test_a_single_selection_list_refuses_several_rows(page):
    with pytest.raises(ToolError, match="one row at a time"):
        act(page.single, "select", rows=[0, 1])


def test_a_rows_box_is_ticked_through_the_model(page):
    act(page.rows, "check", row="row_1")
    assert page.rows.item(1, 0).checkState() == Qt.CheckState.Checked
    assert ("changed", 1, 0) in page.seen
    listed = describe(page.rows)["rows"]
    assert listed[1]["checked"] is True and listed[1]["checkable"] is True
    act(page.rows, "uncheck", row=1)
    assert page.rows.item(1, 0).checkState() == Qt.CheckState.Unchecked
    with pytest.raises(ToolError, match="no box you can tick"):
        act(page.rows, "check", row=1, column="Value")


def test_an_editable_cell_is_set_and_a_read_only_one_refused(page):
    act(page.rows, "set_cell", row="row_2", column="Value", value="45")
    assert page.rows.item(2, 1).data(Qt.ItemDataRole.EditRole) == 45
    assert describe(page.rows)["rows"][2]["editable"] == [1]
    with pytest.raises(ToolError, match="cannot be edited"):
        act(page.rows, "set_cell", row=0, column=0, value="renamed")
    with pytest.raises(ToolError, match="whole number"):
        act(page.rows, "set_cell", row=0, column=1, value="many")


def test_a_branch_opens_and_closes(page):
    act(page.tree, "expand", row="castle")
    assert page.tree.topLevelItem(0).isExpanded() and ("expanded", "castle") in page.seen
    rows = describe(page.tree)["rows"]
    assert rows[0]["children"] == 1 and rows[0]["expanded"] is True and rows[1]["cells"] == ["gate"]
    act(page.tree, "collapse", row=0)
    assert not page.tree.topLevelItem(0).isExpanded()
    with pytest.raises(ToolError, match="nothing under it"):
        act(page.tree, "expand", row="leaf")


def test_a_key_reaches_the_windows_shortcut(page):
    act(page.files, "key", keys="Esc")
    assert ("esc",) in page.seen
    with pytest.raises(ToolError, match="key sequence"):
        act(page.files, "key", keys="")


@pytest.mark.parametrize(("action", "keys", "effect"), [
    ("expand", None, READ), ("collapse", None, READ), ("set_cell", None, EDIT), ("key", "Esc", EDIT),
    ("key", "Delete", DESTRUCTIVE), ("key", "Ctrl+S", OUTPUT),
])
def test_the_classes(page, action, keys, effect):
    assert effect_of_action(page.tree, action, keys=keys) == effect


def test_a_key_in_a_user_only_window_is_refused(page, monkeypatch):
    from cdmw.mcp import ui_tree

    monkeypatch.setattr(ui_tree, "user_only_reason", lambda widget, window=None: "Only you can use this control.")
    with pytest.raises(ToolError, match="Only you"):
        act(page.files, "key", keys="Delete")
    assert page.files.count() == 6
