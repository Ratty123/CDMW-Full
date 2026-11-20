"""The Prefab Inspector's path edits as typed tools (MCP gap plan item 13, prefab part).

Both tools act on the ``.prefab`` selected in Browse Archives (``view_open`` selects
one). ``files.prefab_read`` lists the Inspector's rows: each object and the fields it
holds, with the row id ``files.prefab_save`` takes. ``files.prefab_save`` types the new
paths into those rows, presses Save changes, answers the review (its warnings block
unless accept_warnings is given), chooses Loose Folder and answers the mod-ready export
prompt. The game archives are never changed; prefab edits have not been confirmed to
load in game. Placement values, adding or removing objects and item packages (.cdmw)
stay on the generic controls (``app_ui_act``) for now.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp import mod_ready_prompt
from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, TEXT, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

MAX_CHANGES = 200


def _source(call):
    from cdmw.services.archive_read_service import read_archive_entry_data

    def selected():
        archive = getattr(window(call), "archive", None)
        if archive is None or not hasattr(archive, "_show_prefab_inspector"):
            raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
        entry = archive._current_archive_prefab_entry()
        if entry is None:
            raise ToolError(UNAVAILABLE, "Select a .prefab file in Browse Archives first (view_open selects one).")
        return archive, entry

    archive, entry = call.context.ui_call(selected)
    call.check_cancelled()
    return archive, entry, bytes(read_archive_entry_data(entry)[0])


def _rows(dialog):
    """(row id, object, child item) for every row the Inspector lists."""

    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            yield f"{index}.{child_index}", parent, parent.child(child_index)


def _row_data(row, parent, child) -> dict[str, object]:
    from cdmw.ui.archive_browser.prefab_inspector_editing import EDIT_ROLE

    editable = isinstance(child.data(2, EDIT_ROLE), str)
    return {"row": row, "object": parent.text(0), "field": child.text(0), "kind": child.text(1),
            "value": child.text(2), "can_change": editable}


def _read(call):
    from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog

    _archive, entry, data = _source(call)

    def inspect():
        dialog = PrefabInspectorDialog(data)
        try:
            return {"path": entry.path, "banner": dialog.banner.text(),
                    "rows": [_row_data(row, parent, child) for row, parent, child in _rows(dialog)]}
        finally:
            dialog.deleteLater()

    return ui(call, inspect)


def _save(call):
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

    from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog
    from cdmw.ui.archive_browser.prefab_inspector_editing import EDIT_ROLE
    from cdmw.ui.archive_browser.prefab_inspector_review import PrefabChangeReview

    args = call.arguments
    folder = Path(str(args["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")
    changes = {str(change["row"]): str(change["new"]) for change in args["changes"]}
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ToolError(INVALID_ARGUMENTS, f"Give 1 to {MAX_CHANGES} changes.")
    archive, entry, data = _source(call)
    report: dict[str, object] = {}

    def review(dialog):
        if dialog.acknowledge is not None:
            if not args.get("accept_warnings"):
                report["warnings"] = list(dialog._warnings)
                return dialog.DialogCode.Rejected
            dialog.acknowledge.setChecked(True)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        return dialog.result()

    def inspect(dialog):
        rows = {row: child for row, _parent, child in _rows(dialog)}
        for row, new in changes.items():
            child = rows.get(row)
            if child is None:
                raise ToolError(NOT_FOUND, f"There is no row {row}; files_prefab_read lists them.")
            if not isinstance(child.data(2, EDIT_ROLE), str):
                raise ToolError(REFUSED, f"Row {row} ({child.text(0)}) cannot change.")
            child.setText(2, new)
        if not dialog.apply_button.isEnabled():
            raise ToolError(REFUSED, dialog.status.text() or dialog.banner.text())
        dialog.apply_button.click()  # Save changes..., then the review
        if dialog.result_payload is None:
            if "warnings" in report:
                raise ToolError(REFUSED, "The review lists warnings; give accept_warnings to save anyway.",
                                {"warnings": report["warnings"]})
            lines = dialog.log.toPlainText().strip().splitlines()
            raise ToolError(REFUSED, lines[-1] if lines else "Nothing was built.")
        report["summary"] = dialog.result_payload.summary
        return dialog.DialogCode.Accepted

    def export_as(box):
        loose = next((button for button in box.buttons() if button.text() == "Loose Folder..."), None)
        if loose is None:
            raise ToolError(UNAVAILABLE, "The export question has no Loose Folder choice.")
        loose.click()
        return 0

    def show():
        archive._show_prefab_inspector(entry, data, {})
        return {"path": entry.path}

    before = mod_ready_prompt.children(folder)
    dialogs = {PrefabInspectorDialog: inspect, PrefabChangeReview: review, QMessageBox: export_as,
               **mod_ready_prompt.dialogs(args)}
    outcome = ui(call, show, mod_ready_prompt.answers(args), dialogs=dialogs)
    return mod_ready_prompt.wait_for_package(call, folder, before, {**outcome, **report}, "Prefab Inspector")


_CHANGE = {"type": "object", "additionalProperties": False, "required": ["row", "new"],
           "properties": {"row": TEXT, "new": TEXT}}


def prefab_tools():
    return [
        tool("files.prefab_read", READ,
             "List the Prefab Inspector's rows for the .prefab selected in Browse Archives: each object's fields "
             "with their row id, what they are, their value and whether a path can change, plus how fully CDMW "
             "read the file.",
             "ui:PrefabInspectorDialog", _read, runs_on=ON_WORKER),
        tool("files.prefab_save", OUTPUT,
             "Prefab Inspector: give rows new paths (changes: row id from files_prefab_read and the new path), "
             "build the edited prefab and save it as a loose mod package under folder, with the package details "
             "given. The review's warnings block unless accept_warnings is true. The game archives are not "
             "changed; prefab edits have not been confirmed to load in game.",
             "ui:PrefabInspectorDialog.apply_button", _save,
             {"changes": {"type": "array", "items": _CHANGE, "minItems": 1, "maxItems": MAX_CHANGES},
              "accept_warnings": BOOL, "folder": PATH, **mod_ready_prompt.SCHEMA},
             ("changes", "folder"), output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["prefab_tools"]
