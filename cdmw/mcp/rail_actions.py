"""Common glue for typed calls to the rail's Qt controls."""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.tools import ON_CALL, Tool, object_schema
from cdmw.mcp.ui_actions import run_action


TEXT = {"type": "string", "maxLength": 1024}
PATH = {**TEXT, "minLength": 1}
BOOL = {"type": "boolean"}
ROW = {"type": "integer", "minimum": 0}
ROWS = {"type": "array", "items": ROW, "minItems": 1, "maxItems": 256}


def choices(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def tool(name, effect, description, route, handler, properties=None, required=(), **options):
    options.setdefault("runs_on", ON_CALL)
    return Tool(name, name.split(".", 1)[0], description, object_schema(properties, required),
                effect, route, handler, **options)


def required(arguments, key):
    if arguments.get(key) in (None, ""):
        raise ToolError(INVALID_ARGUMENTS, f"This action needs '{key}'.")
    return arguments[key]


def window(call):
    result = getattr(call.context, "window", None)
    if result is None:
        raise ToolError(UNAVAILABLE, "CDMW's window is not ready yet.")
    return result


def page(call, key):
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab

    shell = window(call).shell
    widget = shell._tool_widgets_by_key.get(key)
    if widget is None or not widget.isEnabled():
        raise ToolError(UNAVAILABLE, f"The {key} page is unavailable.")
    if isinstance(widget, LazyToolTab):
        return widget.ensure_widget()
    return widget


def press(control):
    if not control.isEnabled():
        raise ToolError(UNAVAILABLE, control.toolTip() or f"{control.text()} is unavailable.")
    control.click()


def choose(combo, value):
    index = combo.findData(value)
    if index < 0 and isinstance(value, str):
        index = combo.findText(value)
    if index < 0:
        raise ToolError(NOT_FOUND, f"No control choice matches {value!r}.")
    combo.setCurrentIndex(index)


def select_tree_rows(tree, rows):
    from PySide6.QtCore import QItemSelectionModel

    items = [tree.topLevelItem(row) for row in rows]
    if not items or any(item is None for item in items):
        raise ToolError(NOT_FOUND, "A requested row is absent from the current results.")
    tree.clearSelection()
    tree.setCurrentItem(items[0], 0, QItemSelectionModel.SelectionFlag.NoUpdate)
    for item in items:
        item.setSelected(True)


def ui(call, operation, answers=None, **options):
    call.check_cancelled()
    outcome = run_action(call.context, operation, answers, **options)
    result = outcome.pop("result", None)
    return {**(result or {}), **{key: value for key, value in outcome.items() if value}}


def output(call, path, *, folder=False):
    from cdmw.domain.output_paths import OutputPathRefused, check_output_path

    try:
        target = check_output_path(path, game_folder=call.context.game_folder(), allow_existing=folder)
    except (OutputPathRefused, ValueError) as refused:
        raise ToolError(REFUSED, str(refused)) from None
    if folder and not target.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {target}")
    return target
