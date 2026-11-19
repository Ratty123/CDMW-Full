"""Shared control routes for the typed Create New Item tools."""

from __future__ import annotations

import math
import time
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.tools import object_schema
from cdmw.mcp.ui_actions import ANSWERS_SCHEMA, DialogAnswers, answering, run_action

STEPS = ("template", "identity", "model", "stats", "effects", "distribution", "output")
TEXT = {"type": "string", "maxLength": 8192}
PATH = {"type": "string", "minLength": 1, "maxLength": 1024}
INT = {"type": "integer"}
NUMBER = {"type": "number"}
BOOL = {"type": "boolean"}
VEC3 = {"type": "array", "items": NUMBER, "minItems": 3, "maxItems": 3}


def choice(*values):
    return {"type": "string", "enum": list(values)}


def array(items, *, limit=512):
    return {"type": "array", "items": items, "maxItems": limit}


def action_schema(actions, properties, *, default=None):
    action = choice(*actions)
    if default is not None:
        action["default"] = default
    return object_schema({"action": action, **properties, "answers": ANSWERS_SCHEMA},
                         ["action"] if default is None else ())


def workflow(context):
    from cdmw.mcp.new_item_tools import NOT_OPEN, _workflow

    _tab, page = _workflow(context)
    if page is None:
        raise ToolError(UNAVAILABLE, NOT_OPEN)
    if not page._panels_built:
        raise ToolError(UNAVAILABLE, page._status.text())
    return page


def idle(page):
    if page.controller.busy:
        raise ToolError(UNAVAILABLE, "Wait for the current operation to finish, then try again.")


def act(call, fn, *, answers=None, message_boxes=None):
    from cdmw.mcp.new_item_tools import _workflow

    def edit():
        tab, _page = _workflow(call.context)
        dialogs = getattr(tab, "_dialogs", None)
        if dialogs is not None and dialogs.native_modal():
            raise ToolError(UNAVAILABLE, "Complete the file or colour dialog before editing the item.")
        return fn()

    supplied = {**(call.arguments.get("answers") or {}), **(answers or {})}
    outcome = run_action(call.context, edit, supplied, message_boxes=message_boxes)
    result = outcome.pop("result", None)
    return {**(result or {}), **{key: value for key, value in outcome.items() if value}}


def answer_later(call, asked):
    """Use this call's answers at one operation's later dialog, on the UI thread."""
    answers = dict(call.arguments.get("answers") or {})
    game = call.context.game_folder()

    def run(dialog):
        record = DialogAnswers(answers, game)
        with answering(record):
            result = dialog()
        asked.extend(record.asked)
        return result

    return run


def read_when(call, read, *, timeout=20.0):
    """Read published UI state from the call thread until the requested result arrives."""
    deadline = time.monotonic() + timeout
    while True:
        call.check_cancelled()
        result = call.context.ui_call(read)
        if result is not None or time.monotonic() >= deadline:
            return result
        time.sleep(0.04)


def required(arguments, *names):
    for name in names:
        if name not in arguments:
            raise ToolError(INVALID_ARGUMENTS, f"{name} is required for this action.")


def checked_output(context, path, *, existing=False):
    from cdmw.domain.output_paths import OutputPathRefused, check_output_path

    try:
        return check_output_path(path, game_folder=context.game_folder(), allow_existing=existing)
    except OutputPathRefused as exc:
        raise ToolError(REFUSED, str(exc)) from None


def widget_reason(widget):
    return widget.toolTip() or widget.statusTip() or "This control is disabled on the page."


def available(widget):
    if not widget.isEnabled():
        raise ValueError(widget_reason(widget))


def set_control(widget, value):
    """Enter a typed value with the control's input bounds and normal signals."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QDoubleSpinBox, QGroupBox, QLineEdit, QPlainTextEdit, QSlider, QSpinBox

    available(widget)
    if isinstance(widget, QComboBox):
        index = widget.findData(value)
        if index < 0:
            raise ValueError(widget_reason(widget) if not widget.count() else f"{value!r} is not an available choice.")
        item = widget.model().index(index, widget.modelColumn(), widget.rootModelIndex())
        if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            raise ValueError(item.data(Qt.ItemDataRole.ToolTipRole) or widget_reason(widget))
        widget.setCurrentIndex(index)
    elif isinstance(widget, (QAbstractButton, QGroupBox)):
        widget.setChecked(value)
    elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
        if not math.isfinite(value) or not widget.minimum() <= value <= widget.maximum():
            raise ValueError(f"Enter a number from {widget.minimum()} to {widget.maximum()}.")
        widget.setValue(value)
    elif isinstance(widget, QLineEdit):
        validator = widget.validator()
        if len(value) > widget.maxLength() or (value and validator is not None
                and validator.validate(value, len(value))[0] != validator.State.Acceptable):
            raise ValueError(widget_reason(widget))
        widget.setText(value)
        widget.editingFinished.emit()
    elif isinstance(widget, QPlainTextEdit):
        widget.setPlainText(value)
    else:
        raise TypeError(f"Unsupported New Item control {type(widget).__name__}.")


def combo_choices(combo, *, limit=200):
    return {"count": combo.count(), "choices": [
        {"value": json_value(combo.itemData(row)), "label": combo.itemText(row)}
        for row in range(min(combo.count(), limit))
    ]}


def json_value(value):
    """Draft values for MCP, including compact descriptors for embedded mask pixels."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"byte_count": len(value)}
    if is_dataclass(value):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_value(item) for item in value]
    return value
