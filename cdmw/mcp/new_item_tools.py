"""Create New Item's tools: the page, its templates, and New painting.

Create New Item's page is drawn by a helper from Qt controls that are never
shown themselves; a click in the page runs the control's handler. The tools
here use the same controls: the template search box, the template list, and
New painting's own dialog (its frame list, Choose picture..., the texts and
Build mod). ``new_item.state`` also gives the id of the page's controls, so
``app.ui`` lists every step's fields and ``app.ui_act`` fills them.

A painting mod is written where the dialog's own Build writes it: a new
folder inside the folder named, which passes the output path rule.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, Tool, object_schema

NOT_OPEN = "Create New Item is not open yet: app_open_tool new_item_studio shows it; ask again when it is built."
NO_PAINTING = "New painting is not open: new_item_painting_open opens it."


def _workflow(context):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    shell = getattr(getattr(context, "window", None), "shell", None)
    tab = created_tool_widget(getattr(shell, "new_item_studio_tab", None))
    return tab, getattr(tab, "workflow", None)


def _act(call, function) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    outcome = run_action(call.context, function, call.arguments.get("answers"))
    result = outcome.get("result")
    rest = {key: value for key, value in outcome.items() if key != "result" and value}
    return {**(result if isinstance(result, dict) else {"done": True}), **rest}


def _automation(function, window, arguments: dict) -> dict[str, object]:
    try:
        result = function(window, arguments)
    except ValueError as error:
        raise ToolError(INVALID_ARGUMENTS, str(error)) from None
    except RuntimeError as error:
        raise ToolError(UNAVAILABLE, str(error)) from None
    return result if isinstance(result, dict) else {"done": bool(result)}


# ----- the page -------------------------------------------------------------------------
def _state(call) -> dict[str, object]:
    from cdmw.mcp.ui_tree import mirrored_page, widget_id

    context = call.context
    tab, workflow = _workflow(context)
    if workflow is None:
        return {"open": False, "message": NOT_OPEN}
    panel = getattr(workflow, "template_panel", None)
    if panel is None or not getattr(workflow, "_panels_built", True):
        return {"open": True, "ready": False, "message": "Create New Item is still building its pages."}
    controller = getattr(workflow, "controller", None) or getattr(tab, "controller", None)
    matches = panel.matches
    current = matches.currentItem()
    templates = [str(matches.topLevelItem(row).text(0)) for row in range(min(matches.topLevelItemCount(), 200))]
    _page, dialogs = mirrored_page(getattr(context, "window", None))
    state: dict[str, object] = {
        "open": True,
        "ready": bool(getattr(controller, "ready", False)),
        "busy": bool(getattr(controller, "busy", False)),
        "search": panel.filter_edit.text(),
        "templates": templates,
        "template_count": int(matches.topLevelItemCount()),
        "picked": "" if current is None else str(current.text(0)),
        # app_ui with this id lists the page's controls: every step's fields and buttons.
        "controls": widget_id(workflow),
        "dialogs": [{"widget": widget_id(dialog), "title": dialog.windowTitle()} for dialog in dialogs],
    }
    # The step header (WorkflowHeader): its items, the current row and each step's state.
    header = getattr(workflow, "steps", None)
    if header is not None and hasattr(header, "item") and hasattr(header, "currentRow"):
        items = [header.item(index) for index in range(header.count())]
        state["steps"] = [{"index": index, "name": item.text() if item is not None else "",
                           "state": str(getattr(header.stepState(index), "name", "") or "").lower()}
                          for index, item in enumerate(items)]
        row = int(header.currentRow())
        state["step"] = state["steps"][row]["name"] if 0 <= row < len(items) else ""
    return state


def _search(call) -> dict[str, object]:
    context = call.context

    def search() -> dict[str, object]:
        _tab, workflow = _workflow(context)
        if workflow is None or getattr(workflow, "template_panel", None) is None:
            raise ToolError(UNAVAILABLE, NOT_OPEN)
        from cdmw.mcp.ui_tree import act

        act(workflow.template_panel.filter_edit, "set_text", value=str(call.arguments.get("text") or ""),
            window=getattr(context, "window", None), game_folder=context.game_folder())
        matches = workflow.template_panel.matches
        return {"search": workflow.template_panel.filter_edit.text(),
                "template_count": int(matches.topLevelItemCount()),
                "templates": [str(matches.topLevelItem(row).text(0))
                              for row in range(min(matches.topLevelItemCount(), 200))]}

    return _act(call, search)


def _pick(call) -> dict[str, object]:
    from cdmw.automation.review_commands import new_item_pick

    context = call.context
    a = call.arguments
    if not a.get("match") and a.get("row") is None:
        raise ToolError(INVALID_ARGUMENTS, "Name the template: match (text in its row) or row (its number).")

    def pick() -> dict[str, object]:
        result = _automation(new_item_pick, getattr(context, "window", None),
                             {"match": a.get("match") or "", "row": a.get("row") or 0})
        if not result.get("picked"):
            raise ToolError(UNAVAILABLE, "No template in the list matches. new_item_search changes the list.")
        return result

    return _act(call, pick)


# ----- New painting -----------------------------------------------------------------------
def _painting_state(call) -> dict[str, object]:
    from cdmw.automation.authoring_commands import painting_state

    return _automation(painting_state, getattr(call.context, "window", None), {})


def _painting_open(call) -> dict[str, object]:
    from cdmw.automation.authoring_commands import painting_open

    context = call.context
    return _act(call, lambda: _automation(painting_open, getattr(context, "window", None), {}))


def _painting_set(call) -> dict[str, object]:
    from cdmw.automation import authoring_commands

    context = call.context
    arguments = {key: value for key, value in call.arguments.items() if value is not None}
    if not arguments.get("add"):
        arguments.pop("add", None)
    return _act(call, lambda: _automation(authoring_commands.painting_set, getattr(context, "window", None),
                                          arguments))


def _painting_build(call) -> dict[str, object]:
    from cdmw.automation import authoring_commands
    from cdmw.domain.output_paths import OutputPathRefused, check_output_path
    from cdmw.mcp.errors import REFUSED

    context = call.context

    def build() -> dict[str, object]:
        window = getattr(context, "window", None)
        try:
            dialog = authoring_commands._open_dialog(window)
        except RuntimeError:
            raise ToolError(UNAVAILABLE, NO_PAINTING) from None
        # The folder field, typed as the user types it; the path rule has passed for it.
        dialog.folder.setText(str(Path(str(call.arguments["folder"]))))
        folder = dialog.folder.text().strip()
        try:
            check_output_path(folder, game_folder=context.game_folder(), allow_existing=True)
        except OutputPathRefused as refused:
            raise ToolError(REFUSED, str(refused)) from None
        if not dialog.build_button.isEnabled():
            return {"started": False, "status": dialog.status.text()}
        dialog.build_button.click()
        return {"started": bool(dialog._building), "status": dialog.status.text(), "folder": folder}

    return _act(call, build)


def _painting_close(call) -> dict[str, object]:
    from cdmw.automation.authoring_commands import painting_close

    context = call.context
    return _act(call, lambda: {"closed": bool(painting_close(getattr(context, "window", None), {}))})


def new_item_tools() -> list[Tool]:
    text = {"type": "string", "maxLength": 512}
    return [
        Tool(name="new_item.state", family="new_item", title="Create New Item state",
             description="Create New Item now: whether it is ready, the template search and the templates "
                         "listed, the one picked, and 'controls': the id to give app_ui for every field and "
                         "button of the page's steps (app_ui_act fills and presses them), and its open "
                         "dialogs.",
             input_schema=object_schema(), effect=READ, route="ui:NewItemWorkflow", handler=_state,
             runs_on=ON_UI),
        Tool(name="new_item.search", family="new_item", title="Search templates",
             description="Types into Create New Item's template search, as the user does; returns the "
                         "templates then listed.",
             input_schema=object_schema({"text": text}), effect=EDIT, route="ui:TemplatePanel.filter_edit",
             handler=_search, runs_on=ON_CALL),
        Tool(name="new_item.pick", family="new_item", title="Pick a template",
             description="Picks a template in Create New Item's list, as a click on its row does: 'match' "
                         "(text in the row) or 'row' (its number).",
             input_schema=object_schema({"match": text, "row": {"type": "integer", "minimum": 0}}),
             effect=EDIT, route="ui:TemplatePanel.matches", handler=_pick, runs_on=ON_CALL),
        Tool(name="new_item.painting_state", family="new_item", title="New painting state",
             description="The New painting dialog as shown: the frames offered, each painting with its frame, "
                         "picture, fit and texts, the mod name and folder, the status line and log, and "
                         "whether Build mod can be pressed.",
             input_schema=object_schema(), effect=READ, route="ui:PaintingDialog", handler=_painting_state,
             runs_on=ON_UI),
        Tool(name="new_item.painting_open", family="new_item", title="Open New painting",
             description="Shows Create New Item and presses New painting... on its Template page. Until the "
                         "page and the archives are ready it says what it waits for ('waiting'): ask again.",
             input_schema=object_schema(), effect=EDIT, route="ui:TemplatePanel.painting_button",
             handler=_painting_open, runs_on=ON_CALL),
        Tool(name="new_item.painting_set", family="new_item", title="Fill New painting",
             description="Fills the shown painting as the user would: 'add' (Add painting first), 'frame' (its "
                         "mesh path or file stem), 'picture' (the file Choose picture... answers with), 'fit' "
                         "(fill or whole), 'texts' ({language: {name, description}}), 'mod_name' and 'view' "
                         "(front or 3d).",
             input_schema=object_schema({
                 "add": {"type": "boolean"}, "frame": text, "picture": {"type": "string", "maxLength": 1024},
                 "fit": {"type": "string", "enum": ["fill", "whole"]}, "texts": {"type": "object"},
                 "mod_name": text,
                 "view": {"type": "string", "enum": ["front", "3d"]}}),
             effect=EDIT, route="ui:PaintingDialog", handler=_painting_set, runs_on=ON_CALL),
        Tool(name="new_item.painting_build", family="new_item", title="Build the painting mod",
             description="Presses Build mod in New painting: the mod is written as a new folder inside "
                         "'folder' (an existing folder outside the game). new_item_painting_state shows the "
                         "status and log while it builds.",
             input_schema=object_schema({"folder": {"type": "string", "minLength": 3, "maxLength": 1024}},
                                        ["folder"]),
             effect=OUTPUT, route="ui:PaintingDialog.build_button", handler=_painting_build, runs_on=ON_CALL,
             output_folders=("folder",)),
        Tool(name="new_item.painting_close", family="new_item", title="Close New painting",
             description="Presses Close in New painting (it cancels a build that is still running, as the "
                         "button does).",
             input_schema=object_schema(), effect=EDIT, route="ui:PaintingDialog.close_button",
             handler=_painting_close, runs_on=ON_CALL),
    ]


__all__ = ["new_item_tools"]
