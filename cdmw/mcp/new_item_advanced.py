"""Stats & Prices' advanced editors: Item settings (with its stats, inventory, definition and behavior pages)
and Game table changes, through their own controls."""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT
from cdmw.mcp.new_item_workflow import (
    INT, TEXT, act, action_schema, array, available, choice, json_value, read_when, set_control, widget_reason,
    workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool, object_schema

EDITORS = ("item_settings", "stats", "inventory", "definition", "behavior", "game_tables")
# Writing a stock package is a file save, not an edit of this draft.
_NOT_HERE = {"write_stock": "Write stock item package is not reached by this tool."}
_ROWS = 200
_CHOICES = 30


def _editor(page, name):
    panel = page.stats_panel
    if name == "game_tables":
        return panel.game_tables
    settings = panel.item_settings
    return settings if name == "item_settings" else getattr(settings, name)


def _controls(editor):
    """The editor's own named controls, including those it keeps in dicts and tuples ('policies.tags')."""
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QGroupBox, QLineEdit,
                                   QPlainTextEdit, QPushButton, QTableWidget)

    kinds = (QComboBox, QLineEdit, QPlainTextEdit, QAbstractSpinBox, QAbstractButton, QGroupBox, QTableWidget)
    found = {}
    for name, value in vars(editor).items():
        if name.startswith("_"):
            continue
        if isinstance(value, dict):
            items = {f"{name}.{key}": widget for key, widget in value.items()}
        elif isinstance(value, tuple):
            items = {f"{name}.{index}": widget for index, widget in enumerate(value)}
        else:
            items = {name: value}
        for key, widget in items.items():
            if isinstance(widget, kinds):
                found[key] = widget
    buttons = {key: widget for key, widget in found.items() if isinstance(widget, QPushButton)}
    tables = {key: widget for key, widget in found.items() if isinstance(widget, QTableWidget)}
    fields = {key: widget for key, widget in found.items() if key not in buttons and key not in tables}
    return fields, buttons, tables


def _value(widget):
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QGroupBox, QLineEdit

    if isinstance(widget, QComboBox):
        return {"kind": "choice", "value": json_value(widget.currentData()), "label": widget.currentText(),
                "count": widget.count(), "choices": [
                    {"value": json_value(widget.itemData(row)), "label": widget.itemText(row)}
                    for row in range(min(widget.count(), _CHOICES))]}
    if isinstance(widget, (QAbstractButton, QGroupBox)):
        return {"kind": "check", "value": widget.isChecked()}
    if isinstance(widget, QAbstractSpinBox):
        return {"kind": "number", "value": widget.value(), "minimum": widget.minimum(), "maximum": widget.maximum()}
    if isinstance(widget, QLineEdit):
        return {"kind": "text", "value": widget.text(), "placeholder": widget.placeholderText()}
    return {"kind": "text", "value": widget.toPlainText()}


def _cell(item):
    from PySide6.QtCore import Qt

    if item is None:
        return None
    cell = {"text": item.text()}
    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
        cell["checked"] = item.checkState() == Qt.CheckState.Checked
    if item.flags() & Qt.ItemFlag.ItemIsEditable:
        cell["editable"] = True
    return cell


def _table(table, offset):
    columns = [table.horizontalHeaderItem(column).text() if table.horizontalHeaderItem(column) else str(column)
               for column in range(table.columnCount())]
    selected = sorted({index.row() for index in table.selectionModel().selectedRows()})
    rows = [[_cell(table.item(row, column)) for column in range(table.columnCount())]
            for row in range(offset, min(table.rowCount(), offset + _ROWS))]
    return {"columns": columns, "count": table.rowCount(), "offset": offset, "rows": rows, "selected": selected,
            "enabled": table.isEnabled()}


def _tree(editor):
    from PySide6.QtCore import Qt

    tree = getattr(editor, "tree", None)
    if tree is None:
        return None
    rows = []
    current = editor._selected_path()
    for path, cell in list(editor._nodes.items())[:1000]:
        title = cell.model().itemFromIndex(cell.index().siblingAtColumn(0))
        row = {"path": list(path), "label": title.text() if title is not None else "", "value": cell.text()}
        if cell.isEditable():
            row["editable"] = True
        if cell.isCheckable():
            row["checked"] = cell.checkState() == Qt.CheckState.Checked
        rows.append(row)
    return {"rows": rows, "count": len(editor._nodes), "current": list(current), "enabled": tree.isEnabled()}


def _state(page, name, offset=0):
    editor = _editor(page, name)
    fields, buttons, tables = _controls(editor)
    state = {
        "editor": name, "message": editor.message.text() if hasattr(editor, "message") else "",
        "tooltip": editor.toolTip(), "busy": page.controller.busy,
        "fields": {key: {**_value(widget), **({} if widget.isEnabled() else {"enabled": False})}
                   for key, widget in fields.items()},
        "buttons": {key: {"text": widget.text(), "enabled": widget.isEnabled()}
                    for key, widget in buttons.items() if key not in _NOT_HERE},
        "tables": {key: _table(widget, offset) for key, widget in tables.items()},
    }
    tree = _tree(editor)
    if tree is not None:
        state["tree"] = tree
    if name == "game_tables":
        state["edits"] = json_value(editor.edits())
    return state


def _named(collection, key, what):
    if key not in collection:
        raise ToolError(NOT_FOUND, f"There is no {what} {key!r} here.", {"choices": sorted(collection)})
    return collection[key]


def _tree_node(editor, path):
    nodes = getattr(editor, "_nodes", None)
    if nodes is None:
        raise ToolError(INVALID_ARGUMENTS, "This editor has no tree.")
    key = tuple(path)
    if key not in nodes:
        raise ToolError(NOT_FOUND, f"There is no tree row {list(path)!r}.")
    return nodes[key]


def _step(page, editor, step):
    from PySide6.QtCore import QItemSelectionModel, Qt

    fields, buttons, tables = _controls(editor)
    kind = step["kind"]
    if kind == "set":
        widget = _named(fields, step.get("control", ""), "control")
        try:
            set_control(widget, step.get("value"))
        except (TypeError, ValueError) as exc:
            raise ToolError(INVALID_ARGUMENTS, str(exc)) from None
    elif kind == "press":
        key = step.get("control", "")
        if key in _NOT_HERE:
            raise ToolError(UNAVAILABLE, _NOT_HERE[key])
        button = _named(buttons, key, "button")
        if not button.isEnabled():
            raise ToolError(UNAVAILABLE, widget_reason(button))
        button.click()
    elif kind in ("cell", "select_rows"):
        table = _named(tables, step.get("control", ""), "table")
        try:
            available(table)
        except ValueError as exc:
            raise ToolError(UNAVAILABLE, str(exc)) from None
        if kind == "select_rows":
            rows = step.get("rows") or []
            if any(not 0 <= row < table.rowCount() for row in rows):
                raise ToolError(NOT_FOUND, f"The table has {table.rowCount()} rows.")
            table.clearSelection()
            for row in rows:
                table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select
                                              | QItemSelectionModel.SelectionFlag.Rows)
            return
        row, column = step.get("row", -1), step.get("column", -1)
        item = table.item(row, column) if 0 <= row < table.rowCount() and 0 <= column < table.columnCount() else None
        if item is None:
            raise ToolError(NOT_FOUND, f"There is no cell at row {row}, column {column}.")
        if "checked" in step:
            if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                raise ToolError(UNAVAILABLE, "That cell has no box to tick.")
            item.setCheckState(Qt.CheckState.Checked if step["checked"] else Qt.CheckState.Unchecked)
        else:
            if not item.flags() & Qt.ItemFlag.ItemIsEditable:
                raise ToolError(UNAVAILABLE, table.toolTip() or "That cell cannot be edited.")
            item.setText(str(step.get("value", "")))
    elif kind in ("tree_value", "tree_select"):
        tree = getattr(editor, "tree", None)
        if tree is None:
            raise ToolError(INVALID_ARGUMENTS, "This editor has no tree.")
        if not tree.isEnabled():
            raise ToolError(UNAVAILABLE, editor.message.text() or tree.toolTip())
        if kind == "tree_select":
            paths = step.get("paths") or []
            nodes = [_tree_node(editor, path) for path in paths]
            tree.clearSelection()
            for node in nodes:
                tree.selectionModel().select(node.index().siblingAtColumn(0), QItemSelectionModel.SelectionFlag.Select
                                             | QItemSelectionModel.SelectionFlag.Rows)
            if nodes:
                tree.selectionModel().setCurrentIndex(nodes[-1].index(), QItemSelectionModel.SelectionFlag.NoUpdate)
            return
        node = _tree_node(editor, step.get("path") or [])
        if "checked" in step:
            if not node.isCheckable():
                raise ToolError(UNAVAILABLE, "That row has no box to tick.")
            node.setCheckState(Qt.CheckState.Checked if step["checked"] else Qt.CheckState.Unchecked)
        else:
            if not node.isEditable():
                raise ToolError(UNAVAILABLE, "Tick override first; this row cannot be edited now.")
            node.setText(str(step.get("value", "")))
    else:
        raise ToolError(INVALID_ARGUMENTS, f"Unknown step kind {kind!r}.")


def _advanced(call):
    a, context = call.arguments, call.context
    name, offset = a.get("editor", "item_settings"), a.get("offset", 0)
    if a["action"] == "state":
        return context.ui_call(lambda: _state(workflow(context), name, offset))
    steps = a.get("steps") or []
    if not steps:
        raise ToolError(INVALID_ARGUMENTS, "Give steps to apply.")
    done = []

    def edit():
        page = workflow(context)
        editor = _editor(page, name)
        for number, step in enumerate(steps):
            if page.controller.busy and step["kind"] != "press":
                raise ToolError(UNAVAILABLE, "Wait for the current operation to finish, then try again.",
                                {"applied_steps": number})
            try:
                _step(page, editor, step)
            except ToolError as refused:
                refused.data["applied_steps"] = number
                raise
            done.append(number)
        return {}

    result = act(call, edit)
    if result:
        return result
    # A Load button reads references on the worker; answer once it is done.
    state = read_when(call, lambda: None if workflow(context).controller.busy else _state(workflow(context), name,
                                                                                         offset), timeout=60.0)
    if state is None:
        state = {**context.ui_call(lambda: _state(workflow(context), name, offset)), "loading": True}
    return {"applied_steps": len(done), **state}


def advanced_tool():
    step = object_schema({
        "kind": choice("set", "press", "cell", "select_rows", "tree_value", "tree_select"),
        "control": TEXT, "value": {}, "checked": {"type": "boolean"},
        "row": INT, "column": INT, "rows": array(INT, limit=_ROWS),
        "path": array({"type": ["string", "integer"]}, limit=32),
        "paths": array(array({"type": ["string", "integer"]}, limit=32), limit=_ROWS),
    }, ["kind"])
    return Tool(
        name="new_item.advanced", family="new_item", title="Work the New Item advanced editors",
        description="Stats & Prices' experimental editors through their own controls: item_settings (item rules, "
                    "repairs, extraction, use and charges, price and stat amounts), stats (stat entries and "
                    "passive skills), inventory, definition, behavior, and game_tables (values in other game "
                    "tables). 'state' lists the editor's fields, buttons, tables and tree rows by name; 'apply' "
                    "runs steps in order: set a field, press a button (Load ... references first), edit or tick "
                    "a table cell, select table rows, edit or select tree rows by path (tick override first). "
                    "Each control checks its value as on the page; a refused step stops the rest. In-game "
                    "effects of these raw values are unverified.",
        input_schema=action_schema(("state", "apply"), {
            "editor": {**choice(*EDITORS), "default": "item_settings"},
            "steps": array(step, limit=64), "offset": {"type": "integer", "minimum": 0}}),
        effect=EDIT, route="ui:StatsPanel.item_settings,StatsPanel.game_tables", handler=_advanced,
        runs_on=ON_CALL)
