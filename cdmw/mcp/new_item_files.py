"""Draft file I/O, package continuation and the mod maintenance dialogs."""

import os
import tempfile
from copy import deepcopy
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.new_item_output import _notify_export, _started
from cdmw.mcp.new_item_workflow import (
    BOOL, PATH, TEXT, act, action_schema, array, available, checked_output, idle, read_when, required,
    set_control, workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool

_ACTIONS = ("save", "load", "list", "continue", "save_package", "update_package", "update", "merge", "merge_write", "status")


def _save(call):
    from cdmw.core.protected_roots import check_writable
    from cdmw.ui.new_item.draft_file import encode_draft

    required(call.arguments, "path")
    context = call.context
    path = checked_output(context, call.arguments["path"])

    def capture():
        page = workflow(context)
        idle(page)
        page.template_panel.apply_pending_pick()
        if page.controller._template_request is not None:
            raise ToolError(UNAVAILABLE, "Wait for the selected template to finish loading.")
        return deepcopy(page.controller.draft)

    draft = context.ui_call(capture)
    data = encode_draft(draft)
    call.check_cancelled()
    check_writable(path)
    # Stage beside the destination, and publish without replacing an intervening save.
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        call.check_cancelled()
        checked_output(context, path)
        if os.name == "nt":
            temporary.rename(path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"saved": str(path), "template_key": draft.template_key, "model_assets_included": False}


def _saved_root(context):
    root = context.ui_call(lambda: workflow(context).controller.saved_work_root)
    if root is None:
        raise ToolError(UNAVAILABLE, "Drafts & Mods is unavailable in this workspace.")
    return root


def _load(call, *, package):
    from cdmw.ui.new_item.continue_launch import ItemPackageLaunch, item_package_launch, prepare_item_package_launch

    a, context = call.arguments, call.context
    if package and "row_id" in a:
        launch = prepare_item_package_launch(_saved_root(context), a["row_id"])
    else:
        required(a, "file")
        path = Path(a["file"]).expanduser().resolve()
        if package:
            from cdmw.services.item_package_saved_work import read_item_package_file

            launch = item_package_launch(read_item_package_file(path))
        else:
            from cdmw.ui.new_item.draft_file import MAX_DRAFT_BYTES, decode_draft

            with path.open("rb") as stream:
                draft = decode_draft(stream.read(MAX_DRAFT_BYTES + 1))
            launch = ItemPackageLaunch(None, draft.independent_identity, path.name, draft, from_saved_draft=True)
    call.check_cancelled()
    previous = {}

    def restore():
        page = workflow(context)
        idle(page)
        controller = page.controller
        if not controller.ready:
            raise ToolError(UNAVAILABLE, "Read the archives first.")
        key = launch.draft.template_key
        if key is not None and key not in controller.snapshot.rows:
            raise ToolError(UNAVAILABLE, f"Item {key} is not in the snapshot.")
        previous.update(draft=controller.draft, page=page)
        page.continue_item_package(launch)
        return {}

    result = act(call, restore)
    if result:
        return result

    def read():
        page = previous["page"]
        if page._pending_package is launch:
            return None
        draft = page.controller.draft
        loaded = (draft is not previous["draft"] and draft.template_key == launch.draft.template_key
                  and draft.internal_name == launch.draft.internal_name
                  and page.controller.continued_package_path == launch.package_path)
        if not loaded:
            raise ToolError(UNAVAILABLE, page.log.toPlainText().splitlines()[-1])
        return {"loaded": True, "template_key": draft.template_key, "internal_name": draft.internal_name,
                "package": str(launch.package_path) if launch.package_path is not None else None}

    return read_when(call, read) or {"loading": True}


def _write_package(call, *, update):
    from cdmw.constants import PACKAGE_EXTENSIONS

    a, context = call.arguments, call.context
    argument = "package" if update else "path"
    required(a, argument)
    path = checked_output(context, a[argument], existing=update)
    if not path.name.lower().endswith(PACKAGE_EXTENSIONS):
        raise ToolError(INVALID_ARGUMENTS, "Use a Create New Item package filename ending in .cdmw.")
    if update and not path.is_file():
        raise ToolError(UNAVAILABLE, f"There is no item package at {path}.")

    def write():
        page = workflow(context)
        idle(page)
        panel = page.output_panel
        if panel.output_mode.currentData() != "independent" or not page.controller.has_current_plan:
            raise ToolError(UNAVAILABLE, panel.plan_state.plain_text(),
                            {"action": "Refresh the plan in independent mode first."})
        if "mod_name" in a:
            set_control(panel.mod_name, a["mod_name"])
        state, notify = _notify_export(call, panel, path)
        return _started(panel, state, panel._write_independent(update=update, notify=notify))

    return act(call, write, answers={"file" if update else "save_file": str(path)})


def _mod_state(page):
    from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog

    dialog = getattr(page, "_mcp_mod_dialog", None)
    if dialog is None:
        return {"open": False}
    plan = dialog._plan
    is_merge = isinstance(dialog, ModMergeDialog)
    return {"open": True, "action": "merge" if is_merge else "update", "status": dialog.status.text(),
            "busy": dialog._working or dialog._review_lookup.busy,
            "review": dialog._review_writer.text or dialog.review.toPlainText(),
            "result": getattr(plan, "status", None), "can_write": is_merge and dialog.export_button.isEnabled(),
            "conflicts": list(plan.conflicts) if plan is not None else []}


def _scan_mods(call, *, merge):
    from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
    from cdmw.ui.new_item.mod_update_dialog import ModUpdateDialog

    a, context = call.arguments, call.context
    source_name = "sources" if merge else "source"
    required(a, source_name)
    sources = a["sources"] if merge else [a["source"]]
    if any(not Path(name).is_dir() for name in sources):
        raise ToolError(INVALID_ARGUMENTS, "Choose existing source mod folders.")

    def start():
        page = workflow(context)
        idle(page)
        prior = getattr(page, "_mcp_mod_dialog", None)
        if prior is not None:
            prior.reject()
            prior.deleteLater()
        factory = ModMergeDialog if merge else ModUpdateDialog
        dialog = page._mcp_mod_dialog = factory(page.controller, a.get("game_root") or context.game_folder(),
                                                page, embedded=True)
        dialog.hide()
        if merge:
            for name in sources:
                dialog.add_folder(name)
            if "path" in a:
                set_control(dialog.destination, a["path"])
        else:
            set_control(dialog.folder, sources[0])
        if not dialog.scan_button.isEnabled():
            raise ToolError(UNAVAILABLE, dialog.status.text())
        dialog.scan_button.click()
        return _mod_state(page)

    result = act(call, start)
    if "busy" not in result:
        return result

    def read():
        result = _mod_state(workflow(context))
        return None if result["busy"] else result

    result = read_when(call, read) or result
    if merge and a.get("path") and not result["busy"]:
        return _merge_write(call)
    return result


def _merge_write(call):
    from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog

    a, context = call.arguments, call.context
    required(a, "path")
    path = checked_output(context, a["path"])

    def write():
        page = workflow(context)
        idle(page)
        dialog = getattr(page, "_mcp_mod_dialog", None)
        if not isinstance(dialog, ModMergeDialog):
            raise ToolError(UNAVAILABLE, "Check compatibility with the merge action first.")
        set_control(dialog.destination, str(path))
        if "mod_name" in a:
            set_control(dialog.title, a["mod_name"])
        if "dmm_v3" in a:
            set_control(dialog.dmm_v3, a["dmm_v3"])
        if not dialog.export_button.isEnabled():
            raise ToolError(UNAVAILABLE, dialog.status.text())
        dialog.export_button.click()
        return _mod_state(page)

    return act(call, write)


def _files(call):
    a, context = call.arguments, call.context
    action = a["action"]
    try:
        if action == "save":
            return _save(call)
        if action in ("load", "continue"):
            return _load(call, package=action == "continue")
        if action == "list":
            from cdmw.services.item_package_saved_work import read_item_package_index

            return {"packages": read_item_package_index(_saved_root(context))}
        if action in ("save_package", "update_package"):
            return _write_package(call, update=action == "update_package")
        if action in ("merge", "update"):
            return _scan_mods(call, merge=action == "merge")
        if action == "merge_write":
            return _merge_write(call)
        return context.ui_call(lambda: _mod_state(workflow(context)))
    except (ValueError, OSError) as exc:
        raise ToolError(FAILED, str(exc)) from None


def _effect(call):
    action = call.arguments["action"]
    if action in ("list", "status"):
        return READ
    if action == "update_package":
        return DESTRUCTIVE
    if action in ("save", "save_package", "merge_write") or (action == "merge" and call.arguments.get("path")):
        return OUTPUT
    return EDIT


def _approval_key(call):
    action = call.arguments["action"]
    if action == "update_package":
        required(call.arguments, "package")
        path = checked_output(call.context, call.arguments["package"], existing=True)
        return f"{call.tool.name}.{action}:{path}"
    return f"{call.tool.name}.{action}"


def draft_file_tool():
    return Tool(
        name="new_item.draft_file", family="new_item", title="Save or continue New Item work",
        description="Save or load standalone draft settings, or write, list and continue item packages. "
                    "Update an existing item package with its identity, check a mod for game updates, or "
                    "check and merge mod folders. Standalone settings omit imported model assets.",
        input_schema=action_schema(_ACTIONS, {
            "file": PATH, "path": PATH, "package": PATH, "row_id": TEXT, "source": PATH,
            "sources": {**array(PATH, limit=64), "minItems": 2}, "game_root": PATH, "mod_name": TEXT, "dmm_v3": BOOL,
        }),
        effect=OUTPUT, effect_of=_effect, output_paths=("path",),
        approval_key=_approval_key,
        route="ui:NewItemStudioTab.continue_item_package,OutputPanel,ModUpdateDialog,ModMergeDialog",
        handler=_files, runs_on=ON_CALL,
    )
