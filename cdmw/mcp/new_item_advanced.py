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

EDITORS = ("item_settings", "stats", "inventory", "definition", "behavior", "game_tables", "wearers",
           "fitting_reference", "rig")
# Model step groups reached here, by the panel's own control names. Browse installed models and Add bones open
# their own dialogs, and Export rig GLB writes files (new_item.export_rig).
_MODEL_GROUPS = {
    "fitting_reference": (("show_installed_reference", "clear_reference_button"), "reference_name", "reference_group"),
    "rig": (("clear_skeleton_edit_button",), "rig_summary", "rig_field"),
}


class _Group:
    """A few of a panel's controls, shown as one editor."""

    def __init__(self, panel, names, message, holder):
        for name in names:
            setattr(self, name, getattr(panel, name))
        self.message = getattr(panel, message)
        self._holder = getattr(panel, holder)

    def toolTip(self):  # noqa: N802 (Qt's name)
        return self._holder.toolTip()
# Writing a stock package is a file save, not an edit of this draft.
_NOT_HERE = {"write_stock": "Write stock item package is not reached by this tool."}
_ROWS = 200
_CHOICES = 30


def _editor(page, name):
    if name == "wearers":
        return page.template_panel.wearers
    if name in _MODEL_GROUPS:
        names, message, holder = _MODEL_GROUPS[name]
        return _Group(page.model_panel, names, message, holder)
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
        "editor": name, "message": (editor.message if hasattr(editor, "message") else editor.status).text(),
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
    if name == "wearers":
        state["worn_by"] = editor.worn_by.text() if not editor.worn_by.isHidden() else ""
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
    if "waiting_on" in result:
        return result
    # A Load button reads references on the worker; answer once it is done.
    state = read_when(call, lambda: None if workflow(context).controller.busy else _state(workflow(context), name,
                                                                                         offset), timeout=60.0)
    if state is None:
        state = {**context.ui_call(lambda: _state(workflow(context), name, offset)), "loading": True}
    return {**result, "applied_steps": len(done), **state}


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
                    "passive skills), inventory, definition, behavior, game_tables (values in other game "
                    "tables), wearers (Wearable by: Kliff, Damiane, Oongka), fitting_reference (show or clear the "
                    "preview-only reference) and rig (clear added bones). 'state' lists the editor's fields, buttons, tables and tree rows by name; 'apply' "
                    "runs steps in order: set a field, press a button (Load ... references first), edit or tick "
                    "a table cell, select table rows, edit or select tree rows by path (tick override first). "
                    "Each control checks its value as on the page; a refused step stops the rest. In-game "
                    "effects of these raw values are unverified.",
        input_schema=action_schema(("state", "apply"), {
            "editor": {**choice(*EDITORS), "default": "item_settings"},
            "steps": array(step, limit=64), "offset": {"type": "integer", "minimum": 0}}),
        effect=EDIT, route="ui:StatsPanel.item_settings,StatsPanel.game_tables,TemplatePanel.wearers,ModelPanel", handler=_advanced,
        runs_on=ON_CALL)


def _export_rig(call):
    from pathlib import Path

    from cdmw.mcp.new_item_workflow import checked_output, idle

    a, context = call.arguments, call.context
    folder = checked_output(context, a["folder"], existing=True)
    if not folder.is_dir():
        raise ToolError(UNAVAILABLE, f"There is no folder {folder}.")
    messages = []

    def start():
        page = workflow(context)
        idle(page)
        panel, controller = page.model_panel, page.controller
        entry = controller.template_primary_entry()
        if entry is None:
            raise ToolError(UNAVAILABLE, "Choose a template first; its mesh and rig are exported.")
        if not panel.export_rig_button.isEnabled():
            raise ToolError(UNAVAILABLE, widget_reason(panel.export_rig_button))
        record = lambda message, error: messages.append((str(message), bool(error)))  # noqa: E731
        controller.status_message.connect(record)
        capture["record"], capture["controller"] = record, controller
        # The export refuses a GLB already there under the name it writes (<stem>_rig.glb, or
        # <stem>_edited_rig.glb when bones were added); only it knows which once the rig is read.
        controller.rig_export_replaces = False
        try:
            panel.export_rig_button.click()  # Its folder prompt is answered with folder.
        finally:
            controller.rig_export_replaces = True
        return {}

    capture = {}
    result = act(call, start, answers={"folder": str(folder)})
    if "waiting_on" in result or "record" not in capture:
        return result
    try:
        done = read_when(call, lambda: None if capture["controller"].busy else True, timeout=300.0)
    finally:
        context.ui_call(lambda: capture["controller"].status_message.disconnect(capture["record"]))
    if done is None:
        return {**result, "running": True, "folder": str(folder)}
    failed = next((message for message, error in messages if error), None)
    if failed:
        raise ToolError(UNAVAILABLE, failed)
    written = sorted(str(path) for path in Path(folder).glob("*_rig*.glb"))
    return {**result, "folder": str(folder), "written": written, "message": messages[-1][0] if messages else ""}


def export_rig_tool():
    from cdmw.mcp.names import OUTPUT
    from cdmw.mcp.new_item_workflow import PATH
    from cdmw.mcp.ui_actions import ANSWERS_SCHEMA

    return Tool(
        name="new_item.export_rig", family="new_item", title="Export the template rig as GLB",
        description="Press the Model step's Export rig GLB into a folder you allow: the template mesh skinned to "
                    "its skeleton, with any added bones, to weight a model against in Blender. It never replaces "
                    "a GLB already in that folder.",
        input_schema=object_schema({"folder": PATH, "answers": ANSWERS_SCHEMA}, ["folder"]),
        effect=OUTPUT, route="ui:ModelPanel.export_rig_button", handler=_export_rig, runs_on=ON_CALL,
        output_folders=("folder",))
