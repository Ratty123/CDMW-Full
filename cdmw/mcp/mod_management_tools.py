"""Typed controls for CDMW's package list and the supported mod merge workflow."""

from __future__ import annotations

from cdmw.mcp.errors import NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROWS, TEXT, choices, output, page, press, required, tool, ui
from cdmw.mcp.ui_actions import run_action


def _workspace(call):
    tab = page(call, "mod_management")
    return getattr(tab, "workflow", tab)


def _state(tab):
    merge = tab.merge_page
    return {"packages": tab.mods_page.packages(), "merge_available": tab.pages.folder_tools,
            "merge_folders": list(merge._folder_paths()),
            "busy": bool(tab.controller.busy), "status": merge.status.text(),
            "review": merge.review.toPlainText()[:32000], "can_export": merge.export_button.isEnabled(),
            "dmm_status": tab.mods_page.status.text()}


def _list(call):
    return call.context.ui_call(lambda: _state(_workspace(call)))


def _change(call):
    args = call.arguments
    action = args["action"]
    answers = {}
    if action == "add_packages":
        answers["files"] = required(args, "paths")
    if action == "add_merge_folder":
        answers["folder"] = required(args, "path")

    def change():
        tab = _workspace(call)
        mods, merge = tab.mods_page, tab.merge_page
        if action == "cancel":
            press(tab.cancel_button)
        elif action == "add_packages":
            press(mods.add_items)
        elif action == "remove_packages":
            selected = [mods.selection.topLevelItem(row) for row in required(args, "rows")]
            if any(item is None for item in selected):
                raise ToolError(NOT_FOUND, "A requested package is absent from Mod Management.")
            mods.selection.clearSelection()
            for item in selected:
                item.setSelected(True)
            press(mods.remove_selected)
        else:
            if not tab.pages.folder_tools:
                raise ToolError(UNAVAILABLE, "This Mod Management page has no Combine controls.")
            if tab._current_page() is not merge:
                tab.open_page("merge")
            if action == "add_merge_folder":
                press(merge.add_button)
            elif action == "remove_merge_folder":
                rows = required(args, "rows")
                if len(rows) != 1 or merge.folders.item(rows[0]) is None:
                    raise ToolError(NOT_FOUND, "Choose a single merge folder by row.")
                merge.folders.setCurrentRow(rows[0])
                press(merge.remove_button)
            else:
                press(merge.scan_button)
        return _state(tab)

    return ui(call, change, answers)


def _export(call):
    args = call.arguments
    if args.get("action", "merge") == "dmm":
        return _export_dmm(call)
    destination = output(call, required(args, "destination"))

    def export():
        tab = _workspace(call)
        merge = tab.merge_page
        if not tab.pages.folder_tools:
            raise ToolError(UNAVAILABLE, "This Mod Management page has no Combine controls.")
        if merge._plan is None:
            raise ToolError(UNAVAILABLE, "Check the selected mod folders before exporting.")
        merge.destination.setText(str(destination))
        if "title" in args:
            merge.title.setText(args["title"])
        if "dmm_v3" in args:
            merge.dmm_v3.setChecked(args["dmm_v3"])
        press(merge.export_button)
        return _state(tab)

    return ui(call, export)


def _export_dmm(call):
    from cdmw.services.dmm_send import destination
    from cdmw.ui.tools.dmm_packages_page import DMM_MOD_TITLE

    args = call.arguments
    folder = output(call, required(args, "folder"), folder=True)
    target, _ = destination(folder, DMM_MOD_TITLE)
    output(call, target)

    def export():
        tab = _workspace(call)
        mods = tab.mods_page
        if not mods.send_dmm_button.isEnabled():
            raise ToolError(UNAVAILABLE, "Add item packages and set the game folder before exporting to DMM.")
        if tab.controller.busy:
            raise ToolError(UNAVAILABLE, "Wait for Mod Management's current operation to finish.")
        mods.selection.clearSelection()
        if "rows" in args:
            items = [mods.selection.topLevelItem(row) for row in args["rows"]]
            if any(item is None for item in items):
                raise ToolError(NOT_FOUND, "A requested package is absent from Mod Management.")
            for item in items:
                item.setSelected(True)

        def notify(dialog):
            run_action(call.context, dialog)

        mods._send_to_dmm(choose_folder=lambda _parent: folder, notify=notify)
        return {**_state(tab), "destination": str(target)}

    return ui(call, export)


def mod_management_tools():
    return [
        tool("mods.list", READ, "List Mod Management's item packages, merge inputs, review and progress.",
             "ui:ModManagementTab.mods_page", _list),
        tool("mods.change", EDIT, "Add or remove packages or merge folders, check merge compatibility or cancel.",
             "ui:ModManagementTab", _change,
             {"action": choices("add_packages", "remove_packages", "add_merge_folder", "remove_merge_folder",
                                "check_merge", "cancel"), "path": PATH,
              "paths": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 256}, "rows": ROWS},
             ("action",)),
        tool("mods.export", OUTPUT, "Write a checked merge or export item packages into a DMM mods folder.",
             "ui:ModManagementTab.merge_page.export_button,DmmPackagesPage.send_dmm_button", _export,
             {"action": choices("merge", "dmm"), "destination": PATH, "title": TEXT, "dmm_v3": BOOL,
              "folder": PATH, "rows": ROWS}, output_paths=("destination",), output_folders=("folder",)),
    ]
