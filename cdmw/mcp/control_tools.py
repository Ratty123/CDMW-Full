"""The generic tools: what makes the AI connection reach everything a user can.

* ``app.state``: which tool is shown, what is open, whether a dialog waits.
* ``app.open_tool``: show a tool, as its rail entry does.
* ``app.run_command``: run any registry command by id. Its class is the command's own.
* ``app.ui``: the controls of the shown window, a dialog or one widget.
* ``app.ui_act``: press, fill, tick, pick or select one control, as a click does.
* ``app.screenshot``: a picture of a window, a dialog or one widget.
* ``app.settings_get``: the settings file's values (``app.settings_set`` changes one
  through its Settings control, so every change takes the page's own path).

Acting tools run their action through ``ui_actions.run_action``: on the UI
thread, with the choosers and questions it would show answered from the
call's ``answers``. Nothing here names a file to write except through that
answer, which passes the output path rule.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, Tool, object_schema

MAX_PICTURE_SIDE = 1600
_WIDGET = {"type": "string", "maxLength": 32, "description": "A control's id from app_ui (such as w12)."}


def _answers_schema() -> dict[str, object]:
    from cdmw.mcp.ui_actions import ANSWERS_SCHEMA

    return dict(ANSWERS_SCHEMA)


def _window(context):
    window = getattr(context, "window", None)
    if window is None:
        raise ToolError(UNAVAILABLE, "CDMW's window is not ready yet.")
    return window


# ----- pictures ---------------------------------------------------------------------------
def png_of(pixmap, max_side: int = MAX_PICTURE_SIDE) -> tuple[bytes, int, int]:
    """(PNG bytes, width, height) of a QPixmap or QImage, scaled down to ``max_side``."""

    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage

    image = pixmap if isinstance(pixmap, QImage) else pixmap.toImage()
    if image.isNull():
        raise ToolError(UNAVAILABLE, "There is nothing to take a picture of.")
    if max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data()), image.width(), image.height()


# ----- app.state ----------------------------------------------------------------------------
def _tools_on_rail(shell) -> list[dict[str, object]]:
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS

    widgets = getattr(shell, "_tool_widgets_by_key", {}) or {}
    rows = []
    for spec in COMPACT_TOOL_SPECS:
        widget = widgets.get(spec.key) if isinstance(widgets, dict) else None
        available = widget is None or bool(widget.isEnabled())
        row: dict[str, object] = {"key": spec.key, "label": spec.label, "group": spec.category,
                                  "available": available}
        if not available:
            row["reason"] = str(widget.toolTip() or "")
        rows.append(row)
    return rows


def _open_windows(main) -> list[dict[str, object]]:
    from PySide6.QtWidgets import QApplication

    from cdmw.mcp.ui_tree import widget_id

    rows = []
    for widget in QApplication.topLevelWidgets():
        try:
            if not widget.isVisible() or widget is main or not widget.windowTitle():
                continue
        except RuntimeError:
            continue
        rows.append({"widget": widget_id(widget), "title": widget.windowTitle(), "class": type(widget).__name__,
                     "modal": bool(widget.isModal())})
    return rows


def _state(call) -> dict[str, object]:
    from cdmw.mcp import approvals
    from cdmw.mcp.ui_actions import modal_dialog
    from cdmw.mcp.ui_tree import widget_id

    context = call.context
    window = _window(context)
    shell = getattr(window, "shell", None)
    settings = getattr(context, "settings", None)
    state: dict[str, object] = {
        "title": str(window.windowTitle()),
        "window": widget_id(window) if hasattr(window, "isWidgetType") else "",
        "tool": str(getattr(getattr(shell, "compact_workspace", None), "_active_tool_key", "") or ""),
        "tools": _tools_on_rail(shell) if shell is not None else [],
        "game_folder": context.game_folder() if hasattr(context, "game_folder") else "",
        "dialog": modal_dialog(),
        "windows": _open_windows(window),
        "access": {
            "full_access": approvals.full_access(settings),
            **{effect: approvals.approval_mode(settings, effect) for effect in approvals.CONFIGURABLE},
        },
    }
    archive = getattr(window, "archive", None)
    if archive is not None:
        try:
            from cdmw.ui.archive_browser.remote_entry_lookup import LiveCatalogueState, live_catalogue_state

            state["archives_loaded"] = live_catalogue_state(archive) == LiveCatalogueState.READY
        except Exception:
            state["archives_loaded"] = False
    if shell is not None:
        from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

        view = created_tool_widget(getattr(shell, "mesh_editor_tab", None))
        state["mesh_documents"] = len(tuple(getattr(view, "documents", ()) or ())) if view is not None else 0
    status = getattr(window, "statusBar", None)
    try:
        state["status"] = str(status().currentMessage()) if callable(status) else ""
    except (AttributeError, RuntimeError):
        state["status"] = ""
    return state


# ----- app.open_tool --------------------------------------------------------------------------
def _tool_keys() -> list[str]:
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS

    return [spec.key for spec in COMPACT_TOOL_SPECS]


def _open_tool(call) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action
    from cdmw.ui.shell.shell_commands import tool_command_id

    context = call.context
    key = str(call.arguments["tool"])
    window = _window(context)

    def show() -> None:
        registry = context.command_registry()
        command_id = tool_command_id(key)
        if registry is not None and command_id in registry:
            registry.run(command_id)
        else:
            window.shell._activate_tool_key(key)

    outcome = run_action(context, show, None)
    return {"tool": key, **{k: v for k, v in outcome.items() if k != "result" and v}}


# ----- app.run_command ------------------------------------------------------------------------
def _command(call):
    """On the UI thread: the command a call names, refused when only the user may run it."""

    from cdmw.mcp.classification import USER_ONLY_COMMANDS

    command_id = str(call.arguments["command"])
    if command_id in USER_ONLY_COMMANDS:
        raise ToolError(REFUSED, "Only you can run this command in CDMW: it can change the AI connection "
                                 "settings or the game folder, or it writes into the game.")
    registry = call.context.command_registry()
    if registry is None or command_id not in registry:
        raise ToolError(NOT_FOUND, f"There is no command {command_id} now. commands_list lists them; the Mesh "
                                   "Editor's and the Texture Editor's exist while their tool is open.")
    return registry.get(command_id)


def command_effect(command) -> str:
    """A command's class; one that kept the default although its id or label says build,
    export, delete or remove (the Mesh Editor's mirrored commands) is output or destructive."""

    from cdmw.mcp.classification import needs_explicit_effect

    if not needs_explicit_effect(command):
        return command.effect
    words = f"{command.label} {str(command.id).split('.', 1)[-1]}".casefold()
    return DESTRUCTIVE if ("delete" in words or "remove" in words) else OUTPUT


def _run_command_effect(call) -> str:
    return command_effect(_command(call))


def _run_command(call) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    context = call.context
    command_id = str(call.arguments["command"])

    def run() -> None:
        _command(call)
        context.command_registry().run(command_id)

    outcome = run_action(context, run, call.arguments.get("answers"))
    if "result" not in outcome:
        return {"ran": True, "command": command_id, **outcome}
    return {"ran": True, "command": command_id, "asked": outcome["asked"]}


# ----- app.ui, app.ui_act, app.screenshot -----------------------------------------------------
def _root(call, name: str = "widget"):
    """The widget a call names, or the dialog that holds the interface, or the main window."""

    from PySide6.QtWidgets import QApplication

    from cdmw.mcp.ui_tree import widget_by_id

    wanted = str(call.arguments.get(name) or "")
    if wanted:
        return widget_by_id(wanted)
    modal = QApplication.activeModalWidget()
    if modal is not None:
        return modal
    window = _window(call.context)
    # Create New Item is drawn by a helper from Qt controls that are not shown themselves.
    shell = getattr(window, "shell", None)
    if str(getattr(getattr(shell, "compact_workspace", None), "_active_tool_key", "") or "") == "new_item_studio":
        from cdmw.mcp.ui_tree import mirrored_page

        workflow, dialogs = mirrored_page(window)
        if workflow is not None:
            return dialogs[-1] if dialogs else workflow
    return window


def _ui(call) -> dict[str, object]:
    from cdmw.mcp.ui_tree import MAX_ROWS, describe, describe_tree, kind_of, widget_id

    a = call.arguments
    root = _root(call)
    top = root.window()
    result: dict[str, object] = {"window": {"widget": widget_id(top), "title": top.windowTitle(),
                                            "class": type(top).__name__}}
    if kind_of(root) in ("list", "table", "tree"):
        result["controls"] = [describe(root, offset=int(a.get("rows_from") or 0), limit=MAX_ROWS)]
        return result
    result["controls"] = describe_tree(root, query=str(a.get("query") or ""),
                                       kinds=tuple(a.get("kinds") or ()), include_labels=bool(a.get("labels", True)))
    return result


def _target(call):
    """The control a call names. Found once: the control that was approved is the one used,
    whatever else has that text by the time the user has answered."""

    from cdmw.mcp.ui_tree import find_by_text, widget_by_id, widget_id

    pinned = getattr(call, "pinned_widget", "")
    if pinned:
        return widget_by_id(pinned)
    a = call.arguments
    if a.get("widget"):
        widget = widget_by_id(str(a["widget"]))
    elif a.get("text"):
        widget = find_by_text(_root(call, "inside"), str(a["text"]), str(a.get("kind") or ""))
    else:
        raise ToolError(INVALID_ARGUMENTS, "Name the control: widget (its id from app_ui) or text (what it "
                                           "says).")
    call.pinned_widget = widget_id(widget)
    return widget


def _ui_act_effect(call) -> str:
    from cdmw.mcp.ui_tree import effect_of_action, user_only_reason

    widget = _target(call)
    reason = user_only_reason(widget, getattr(call.context, "window", None))
    if reason:
        raise ToolError(REFUSED, reason)
    return effect_of_action(widget, str(call.arguments["action"]))


def _ui_act_key(call) -> str:
    from cdmw.mcp.ui_tree import describe

    widget = _target(call)
    row = describe(widget, rows=False)
    # One control of one window: allowing "OK" in a dialog does not allow every OK button.
    title = widget.window().windowTitle().split(" [AI connections on")[0]
    return f"{call.arguments['action']}:{title}:{row.get('text') or row.get('name') or row['widget']}"


def _ui_act(call) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action
    from cdmw.mcp.ui_tree import act

    a = call.arguments
    context = call.context

    def run() -> dict[str, object]:
        return act(_target(call), str(a["action"]), value=a.get("value"), row=a.get("row"),
                   window=getattr(context, "window", None), game_folder=context.game_folder())

    outcome = run_action(context, run, a.get("answers"))
    if "result" not in outcome:
        return {"done": True, **outcome}
    return {"done": True, "control": outcome["result"], "asked": outcome["asked"]}


def _screenshot(call):
    from cdmw.mcp.server import ImageResult
    from cdmw.mcp.ui_tree import widget_id

    widget = _root(call)
    data, width, height = png_of(widget.grab(), int(call.arguments.get("max_side") or MAX_PICTURE_SIDE))
    return ImageResult(data, {"widget": widget_id(widget), "title": widget.window().windowTitle(),
                              "width": width, "height": height,
                              "note": "Drawn by Qt: a 3D view drawn by a helper is blank here; use view_capture."})


# ----- app.settings_get -----------------------------------------------------------------------
def _settings_get(call) -> dict[str, object]:
    from cdmw.mcp.summary import summarize

    settings = getattr(call.context, "settings", None)
    if settings is None:
        return {"settings": []}
    prefix = str(call.arguments.get("prefix") or "").replace("\\", "/").casefold()
    rows = []
    for key in sorted(str(key) for key in settings.allKeys()):
        if prefix and not key.replace("\\", "/").casefold().startswith(prefix):
            continue
        value = settings.value(key)
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            value = [str(item) for item in value] if isinstance(value, (list, tuple)) else str(type(value).__name__)
        rows.append({"key": key, "value": summarize(value, key.rsplit("/", 1)[-1])})
    return {"settings": rows}


def control_tools() -> list[Tool]:
    from cdmw.mcp.ui_tree import ACTIONS

    return [
        Tool(name="app.state", family="app", title="App state",
             description="What CDMW shows now: the tool that is open, the tools on the rail and whether each can "
                         "open, whether the archives are loaded, the dialog that waits for an answer (if any), "
                         "other open windows, and what AI tools may do without asking. Start here.",
             input_schema=object_schema(), effect=READ, route="ui:MainWindow", handler=_state, runs_on=ON_UI),
        Tool(name="app.open_tool", family="app", title="Open a tool",
             description="Shows one of CDMW's tools, as its entry on the rail does: Browse Archives "
                         "(archive_browser), Create New Item (new_item_studio), Mesh Editor, Model Library and "
                         "the others. app_state lists the keys.",
             input_schema=object_schema({"tool": {"type": "string", "enum": _tool_keys()}}, ["tool"]),
             effect=READ, route="registry:shell.open.<tool>", handler=_open_tool, runs_on=ON_CALL),
        Tool(name="app.run_command", family="app", title="Run a command",
             description="Runs one of CDMW's commands by id, as its menu entry, button or key does. commands_list "
                         "lists every command with its class, whether it can run now and why not. The call has "
                         "the command's own class: a read command runs, the others may ask the user. A file "
                         "chooser or question the command would show is answered from 'answers' and listed in "
                         "'asked'; without an answer a chooser is cancelled and a question declined, so call "
                         "again with the answer. 'waiting_on' names a dialog that stays open: read it with "
                         "app_ui.",
             input_schema=object_schema({"command": {"type": "string", "minLength": 3, "maxLength": 128},
                                         "answers": _answers_schema()}, ["command"]),
             effect=EDIT, route="registry:CommandRegistry.run", handler=_run_command, runs_on=ON_CALL,
             effect_of=_run_command_effect, approval_key=lambda call: str(call.arguments["command"])),
        Tool(name="app.ui", family="app", title="Controls shown",
             description="The controls of what CDMW shows: the dialog that waits, or the main window, or the "
                         "widget named. Each has an id (widget), its kind (button, check, radio, field, text, "
                         "number, slider, choice, tabs, list, table, tree, label), its text or value and its "
                         "state; lists, tables and trees show their first rows (name the list as 'widget' for "
                         "all of them, from 'rows_from'). The Mesh Editor's own panels are drawn by its helper "
                         "and are not listed: use mesh_state and commands_list for them.",
             input_schema=object_schema({
                 "widget": _WIDGET, "query": {"type": "string", "maxLength": 128},
                 "kinds": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 16}},
                 "labels": {"type": "boolean", "default": True},
                 "rows_from": {"type": "integer", "minimum": 0}}),
             effect=READ, route="ui:ui_tree.describe_tree", handler=_ui, runs_on=ON_UI, paged="controls"),
        Tool(name="app.ui_act", family="app", title="Use a control",
             description="Does to one control what the user's click or typing does: click a button, check or "
                         "uncheck a box, set_text in a field, set_value of a number or slider, select a row, "
                         "list item or tab ('row': its number or text), activate a row (double-click). Name "
                         "the control by 'widget' (from app_ui) or by 'text'. The control's own handler runs, "
                         "with every rule it has. A button that builds, exports, saves or deletes has that "
                         "class and may ask the user. Choosers and questions are answered from 'answers'.",
             input_schema=object_schema({
                 "widget": _WIDGET, "text": {"type": "string", "maxLength": 256},
                 "kind": {"type": "string", "maxLength": 16}, "inside": _WIDGET,
                 "action": {"type": "string", "enum": list(ACTIONS)},
                 "value": {"type": ["string", "number", "boolean"]},
                 "row": {"type": ["integer", "string"]},
                 "answers": _answers_schema()}, ["action"]),
             effect=EDIT, route="ui:ui_tree.act", handler=_ui_act, runs_on=ON_CALL,
             effect_of=_ui_act_effect, approval_key=_ui_act_key),
        Tool(name="app.screenshot", family="app", title="Picture of a window",
             description="A picture (PNG) of the dialog that waits, the main window, or the widget named, as CDMW "
                         "draws it. For the 3D views use view_capture.",
             input_schema=object_schema({"widget": _WIDGET,
                                         "max_side": {"type": "integer", "minimum": 64, "maximum": 4096,
                                                      "default": MAX_PICTURE_SIDE}}),
             effect=READ, route="ui:QWidget.grab", handler=_screenshot, runs_on=ON_UI),
        Tool(name="app.settings_get", family="app", title="Settings",
             description="The values in CDMW's settings file, all or those under a prefix (such as "
                         "'appearance/'). Secrets are left out. To change a setting, use app_settings_set, which "
                         "sets it through its own control on the Settings page.",
             input_schema=object_schema({"prefix": {"type": "string", "maxLength": 128}}),
             effect=READ, route="service:settings.allKeys", handler=_settings_get, runs_on=ON_UI,
             paged="settings"),
    ]


__all__ = ["command_effect", "control_tools", "png_of"]
