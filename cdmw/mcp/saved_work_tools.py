"""Typed controls for Drafts & Mods and its Combine into One Mod flow."""

from __future__ import annotations

import time

from cdmw.mcp.errors import FAILED, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, TEXT, choices, choose, output, page, press, required, tool, ui
from cdmw.mcp.tools import ON_WORKER


PATHS = {"type": "array", "items": PATH, "minItems": 1, "maxItems": 256}


def _state(tab, args):
    from cdmw.ui.mesh_editor.saved_work_page import _row_key

    rows = tab.rows()
    offset = args.get("offset", 0)
    count = args.get("count", 0)
    return {
        "project": tab._selected_project, "total": len(rows), "combining": tab.combine_flow.busy,
        "projects": [{"id": project.project_id, "name": project.name} for project in tab.projects()],
        "rows": [{"id": _row_key(row), "name": row.display_name, "kind": row.kind, "notes": row.notes,
                  "folder": str(row.folder), "project": row.project_id, "game_files": list(row.game_files)}
                 for row in rows[offset:offset + count]],
    }


def _list(call):
    args = {"count": 100, **call.arguments}
    return call.context.ui_call(lambda: _state(page(call, "saved_work"), args))


def _select(tab, ids):
    from PySide6.QtCore import QItemSelectionModel
    from cdmw.ui.mesh_editor.saved_work_page import _ROW_KEY_ROLE

    tab._show_all_work()
    selected = set(ids)
    rows = [i for i in range(tab.table.rowCount()) if tab.table.item(i, 0).data(_ROW_KEY_ROLE) in selected]
    if not rows or len(rows) != len(selected):
        raise ToolError(NOT_FOUND, "A requested draft or mod is absent from Drafts & Mods.")
    tab.table.clearSelection()
    for row in rows:
        tab.table.selectionModel().select(tab.table.model().index(row, 0),
                                         QItemSelectionModel.SelectionFlag.Select |
                                         QItemSelectionModel.SelectionFlag.Rows)


def _select_project(tab, project):
    if project not in tab._project_keys:
        raise ToolError(NOT_FOUND, f"Drafts & Mods has no project {project!r}.")
    tab.project_list.setCurrentRow(tab._project_keys.index(project))


def _guard_store(call, tab):
    from cdmw.domain.output_paths import game_path_reason

    reason = game_path_reason(tab.draft_root, game_folder=call.context.game_folder())
    if reason:
        raise ToolError(REFUSED, reason)


def _pick_folder_models(call, picker):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    paths = call.arguments.get("models", [])
    if not paths:
        return QDialog.DialogCode.Rejected
    for path in paths:
        picker.filter_edit.setText(path)
        item = next((picker.list.item(i) for i in range(picker.list.count())
                     if picker.list.item(i).data(Qt.ItemDataRole.UserRole).casefold() == path.casefold()), None)
        if item is None:
            return QDialog.DialogCode.Rejected
        item.setSelected(True)
    if not picker.add_button.isEnabled():
        return QDialog.DialogCode.Rejected
    press(picker.add_button)
    return QDialog.DialogCode.Accepted


def _change(call):
    from PySide6.QtWidgets import QDialog
    from cdmw.ui.mesh_editor.folder_model_picker import FolderModelPicker

    args = call.arguments
    action = args.get("action", "continue")
    answers = {}
    if action in {"new_project", "rename_project", "duplicate"}:
        answers["text"] = required(args, "name")
    if action == "add_folder":
        answers["folder"] = required(args, "path")
    if action == "add_package":
        answers["file"] = required(args, "path")
    if action == "move":
        answers["item"] = required(args, "project_name")

    def run_picker(picker):
        result = ui(call, lambda: {"code": int(picker.exec())},
                    dialogs={FolderModelPicker: lambda dialog: _pick_folder_models(call, dialog)})
        return result.get("code", QDialog.DialogCode.Rejected)

    def change():
        tab = page(call, "saved_work")
        if action == "refresh":
            press(tab.refresh_button)
            return _state(tab, {})
        if action != "continue":
            _guard_store(call, tab)
        if action in {"continue", "rename", "duplicate", "move"}:
            ids = args.get("ids") if action == "move" else None
            _select(tab, ids or [required(args, "id")])
        if "project" in args and action in {"add_folder", "add_package", "rename_project"}:
            _select_project(tab, args["project"])
        if action == "rename":
            if "name" in args:
                tab.name_edit.setText(args["name"])
            if "notes" in args:
                tab.notes_edit.setPlainText(args["notes"])
            if "project" in args:
                choose(tab.project_combo, args["project"])
            press(tab.save_details_button)
        elif action == "add_folder":
            tab._add_mod_folder(run_picker=run_picker)
        else:
            press({"continue": tab.continue_button, "new_project": tab.new_project_button,
                   "rename_project": tab.rename_project_button, "duplicate": tab.duplicate_button,
                   "add_package": tab.add_package_button, "move": tab.move_button}[action])
        return _state(tab, {})

    return ui(call, change, answers)


def _delete(call):
    args = call.arguments

    def delete():
        tab = page(call, "saved_work")
        _guard_store(call, tab)
        if args["action"] == "project":
            _select_project(tab, required(args, "project"))
            press(tab.delete_project_button)
        else:
            _select(tab, [required(args, "id")])
            press(tab.delete_button)
        return _state(tab, {})

    return ui(call, delete, {"confirm": "yes"})


def _combine(call):
    from cdmw.ui.mesh_editor.saved_work_combine import STAGE_REFUSED, STAGE_REVIEW

    args = call.arguments
    destination = output(call, args["destination"])
    started = {}
    final = {}

    def finished(result):
        if result is not None:
            final["output"] = str(result.result.output_path)
            final["zip"] = str(result.result.zip_path or "")

    def start():
        tab = page(call, "saved_work")
        _guard_store(call, tab)
        _select(tab, args["ids"])
        flow = tab.combine_flow
        try:
            press(tab.combine_button)
        except ToolError as exc:
            raise ToolError(UNAVAILABLE, tab.combine_reason() or exc.message) from None
        started.update(flow=flow, dialog=flow.dialog)
        flow.finished.connect(finished)

    def publish():
        dialog = started["dialog"]
        dialog.title_edit.setText(args["name"])
        dialog.folder_edit.setText(str(destination))
        dialog.zip_check.setChecked(args.get("zip", False))
        press(dialog.combine_button)

    ui(call, start)
    flow, dialog = started["flow"], started["dialog"]
    deadline = time.monotonic() + 600
    publishing = False
    try:
        while time.monotonic() < deadline:
            call.check_cancelled()
            stage, message = call.context.ui_call(
                lambda: (dialog.stage, dialog.status_label.text()) if flow.dialog is dialog else ("", ""))
            if not stage:
                if "output" in final:
                    return final
                raise ToolError(FAILED, "Combine into One Mod closed before producing an output.")
            if stage == STAGE_REFUSED:
                raise ToolError(FAILED, message)
            if stage == STAGE_REVIEW and not publishing:
                output(call, args["destination"])
                ui(call, publish)
                publishing = True
            time.sleep(0.05)
        raise ToolError(FAILED, "Combine into One Mod did not finish in time.")
    finally:
        def finish():
            flow.finished.disconnect(finished)
            if flow.dialog is dialog:
                flow.cancel()
        call.context.ui_call(finish)


def saved_work_tools():
    return [
        tool("saved.list", READ, "Read Drafts & Mods IDs, projects and entries.", "ui:SavedWorkPage.rows", _list,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("saved.change", EDIT, "Continue, rename, duplicate, move or add saved work. Refresh the list or create "
             "and rename projects. IDs come from saved_list.", "ui:SavedWorkPage", _change,
             {"action": choices("continue", "rename", "duplicate", "move", "add_folder", "add_package",
                                "new_project", "rename_project", "refresh"),
              "id": PATH, "ids": PATHS, "name": TEXT, "notes": {"type": "string", "maxLength": 16384},
              "project": PATH, "project_name": TEXT, "path": PATH, "models": PATHS}, ("action",)),
        tool("saved.delete", DESTRUCTIVE, "Delete a draft or project, or remove a built mod or package from the list.",
             "ui:SavedWorkPage.delete_button", _delete,
             {"action": choices("entry", "project"), "id": PATH, "project": PATH}, ("action",)),
        tool("saved.combine", OUTPUT, "Review and combine built mods into one new output folder.",
             "ui:SavedWorkPage.combine_button", _combine,
             {"ids": {**PATHS, "minItems": 2}, "destination": PATH, "name": PATH, "zip": BOOL},
             ("ids", "destination", "name"), output_paths=("destination",), runs_on=ON_WORKER),
    ]
