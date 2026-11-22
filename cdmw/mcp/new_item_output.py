"""The Output panel's plan review and worker-backed mod writing."""

from pathlib import Path

from cdmw.mcp.errors import UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.new_item_workflow import (
    BOOL, PATH, TEXT, act, action_schema, answer_later, checked_output, choice, idle, json_value,
    read_when, set_control, workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool, object_schema
from cdmw.mcp.ui_actions import ANSWERS_SCHEMA


def _review(page):
    panel, controller = page.output_panel, page.controller
    plan = controller.plan if controller.has_current_plan else None
    operation = getattr(panel, "_mcp_export", None)
    return {
        "current": plan is not None, "mode": panel.output_mode.currentData(), "status": panel.plan_state.plain_text(),
        "busy": controller.busy, "operation": controller._lane,
        "review_pending": panel._review_lookup.busy,
        "review": panel._summary_writer.text or panel.summary.toPlainText(),
        "warnings": list(plan.warnings) if plan is not None else [],
        "issues": json_value(plan.issues) if plan is not None else [],
        "item_key": plan.spec.item_key if plan is not None else None,
        "files": [{"path": path, "change": change} for path, change in panel._file_model.rows],
        "export_problem": panel.export_problem.plain_text(), "build": dict(operation) if operation is not None else None,
    }


def _plan(call):
    context, a = call.context, call.arguments
    if a["action"] == "refresh":
        def start():
            page = workflow(context)
            idle(page)
            panel = page.output_panel
            if "mode" in a:
                set_control(panel.output_mode, a["mode"])
            panel.build_button.click()
            return {}

        result = act(call, start)
        if result:
            return result

    def read():
        page = workflow(context)
        controller, panel = page.controller, page.output_panel
        if (controller.busy and controller._lane == "plan") or panel._review_lookup.busy:
            return None
        return _review(page)

    result = read_when(call, read)
    return result if result is not None else context.ui_call(lambda: _review(workflow(context)))


def _notify_export(call, panel, path):
    state = {"path": str(path), "status": "running"}
    asked = []
    answer = answer_later(call, asked)
    panel._mcp_export = state

    def notify(dialog, result):
        if result is None:
            state.update(status="failed" if panel._export_error else "cancelled", message=panel._export_error)
            return
        answer(dialog)
        written = getattr(result, "package_root", None) or getattr(result, "folder", None) or result.path
        state.update(status="written", path=str(written), asked=asked)
        if getattr(result, "replaced", False):
            state["replaced"] = True
        if getattr(result, "zip_path", None) is not None:
            state["zip"] = str(result.zip_path)

    return state, notify


def _started(panel, state, started):
    if state["status"] == "running" and (not started or not panel._controller.busy):
        state.update(status="failed", message=panel._export_error or panel.plan_state.plain_text())
    return {"started": started, **state}


def _build(call):
    a, context = call.arguments, call.context
    folder = checked_output(context, a["folder"], existing=True)
    if not folder.is_dir():
        raise ToolError(UNAVAILABLE, f"There is no folder {folder}.")

    def write():
        page = workflow(context)
        idle(page)
        panel = page.output_panel
        if not page.controller.has_current_plan or panel.output_mode.currentData() != "folder":
            raise ToolError(UNAVAILABLE, panel.plan_state.plain_text(),
                            {"action": "Refresh the plan in folder mode first."})
        adding = bool(a.get("add_to_existing"))
        if panel.add_to_mod.isChecked() != adding:
            # Add to existing mod builds the plan on that mod, so changing it makes the plan stale.
            panel.add_to_mod.setChecked(adding)
        if adding and Path(panel.export_root.text() or ".") != folder:
            panel.browse_button.click()
        if not page.controller.has_current_plan:
            raise ToolError(UNAVAILABLE, panel.plan_state.plain_text(),
                            {"action": "The plan now builds on that mod: refresh it with new_item_plan, then build "
                                       "again with the same folder." if adding else
                                       "Refresh the plan in folder mode first."})
        if not adding:
            panel.browse_button.click()
        if Path(panel.export_root.text() or ".") != folder:
            raise ToolError(UNAVAILABLE, "Choose an output folder first.")
        if "mod_name" in a:
            set_control(panel.mod_name, a["mod_name"])
        if "zip" in a:
            set_control(panel.create_zip, a["zip"])
        problem = panel.export_problem.plain_text()
        if not panel.export_button.isEnabled():
            raise ToolError(UNAVAILABLE, problem or panel.plan_state.plain_text())
        # Adding writes into the existing mod folder the call named, so that folder may exist;
        # a new package must not replace anything.
        root = checked_output(context, panel._package_root(), existing=adding)
        if adding and root != folder:
            raise ToolError(UNAVAILABLE, f"The item would be added to {root}, not to {folder}.")
        if panel.create_zip.isChecked():
            checked_output(context, root.with_name(f"{root.name}.zip"))
        state, notify = _notify_export(call, panel, root)
        return _started(panel, state, panel._export(notify=notify))

    return act(call, write, answers={"folder": str(folder)})


def _send(call):
    """Send to DMM: the mod goes straight into DMM's mods folder, through the page's own button."""
    from cdmw.mcp.game_table_tools import _mods_folder, _remember_dmm_folder

    a, context = call.arguments, call.context
    mods = checked_output(context, _mods_folder(call, a.get("dmm_folder")), existing=True)

    def send():
        page = workflow(context)
        idle(page)
        panel = page.output_panel
        if not page.controller.has_current_plan or panel.output_mode.currentData() != "folder":
            raise ToolError(UNAVAILABLE, panel.plan_state.plain_text(),
                            {"action": "Refresh the plan in folder mode first."})
        if "mod_name" in a:
            set_control(panel.mod_name, a["mod_name"])
        if not panel.send_dmm_button.isEnabled():
            raise ToolError(UNAVAILABLE, panel.export_problem.plain_text() or panel.send_dmm_button.toolTip())
        # The page reads its own settings for DMM's folder: point them at the folder the tool checked, here on
        # the UI thread and only once the plan and the button are known to be ready.
        _remember_dmm_folder(a.get("dmm_folder"), panel._settings)
        state, notify = _notify_export(call, panel, mods)
        started = panel._send_to_dmm(notify=notify)
        if not started and state["status"] == "running":
            # The page asked before replacing an earlier copy and the answer was no.
            state.update(status="cancelled", message=panel._export_error or
                         "Not sent: a mod of that name that CDMW sent earlier is in DMM's mods folder; "
                         "send again with replace to replace it.")
        return _started(panel, state, started)

    answers = {"confirm": "yes" if a.get("replace") else "no"}
    if a.get("dmm_folder"):
        answers["folder"] = str(a["dmm_folder"])
    return {**act(call, send, answers=answers), "dmm_mods_folder": str(mods)}


def output_tools():
    return [
        Tool(name="new_item.plan", family="new_item", title="Read the New Item plan review",
             description="Read Output's plan review, warnings and build status. Refresh presses Build plan "
                         "and waits for the page's review, optionally choosing folder or independent mode.",
             input_schema=action_schema(("read", "refresh"), {"mode": choice("folder", "independent")}, default="read"),
             effect=EDIT, effect_of=lambda call: READ if call.arguments["action"] == "read" else EDIT,
             route="ui:OutputPanel.build_button,OutputPanel.file_changes", handler=_plan, runs_on=ON_CALL,
             paged="files"),
        Tool(name="new_item.build", family="new_item", title="Write a new item mod folder",
             description="Write the current folder-mode plan in a new subfolder of an existing folder "
                         "outside the game, or with add_to_existing into that existing mod folder itself, keeping "
                         "its items (Add to existing mod). Adding builds the plan on that mod: the first call "
                         "says to refresh the plan, then build again. Read new_item_plan for completion, warnings "
                         "and file changes.",
             input_schema=object_schema({"folder": PATH, "mod_name": TEXT, "zip": BOOL, "add_to_existing": BOOL,
                                         "answers": ANSWERS_SCHEMA}, ["folder"]),
             effect=OUTPUT, route="ui:OutputPanel.export_button", handler=_build, runs_on=ON_CALL,
             output_folders=("folder",)),
        Tool(name="new_item.send_to_dmm", family="new_item", title="Send the new item to DMM",
             description="Press Send to DMM: write the current folder-mode plan as a mod straight into DMM's mods "
                         "folder (the remembered DMM folder, or dmm_folder: the folder that contains DMM.exe). With "
                         "Add to existing mod it updates that mod. replace allows replacing a copy CDMW sent "
                         "earlier under the same name. Then the user enables it in DMM and mounts it.",
             input_schema=object_schema({"dmm_folder": PATH, "mod_name": TEXT, "replace": BOOL,
                                         "answers": ANSWERS_SCHEMA}),
             effect=OUTPUT, route="ui:OutputPanel.send_dmm_button", handler=_send, runs_on=ON_CALL,
             output_folders=("dmm_folder",)),
    ]
