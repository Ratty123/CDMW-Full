"""The Mesh Editor's Qt-side session buttons as a typed tool (MCP gap plan item 8).

After Finish Edit Mesh the editor shows its result page: Resume current edit, Start
next edit pass, Add to Archive Browser, Check mesh and, for a Create New Item model,
Return to Create New Item. The top bar's Name Draft... names the open draft and its
project. ``mesh.session`` presses those same buttons, so their own checks apply.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.mesh_tools import NO_EDITOR, _act, shown_document
from cdmw.mcp.names import EDIT
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

#: action -> the result page button's objectName.
RESULT_BUTTONS = {
    "resume": "MeshEditorRustResultReopenEdit",
    "next_pass": "MeshEditorRustResultContinueeditingmodifiedmesh",
    "add_to_archive_browser": "MeshEditorRustResultAddtoArchiveBrowser",
    "check": "MeshEditorRustResultRunValidation",
    "return_to_new_item": "MeshEditorRustResultReturnToNewItem",
}
ACTIONS = ("name_draft", *RESULT_BUTTONS)


def _button(tab, name: str):
    from PySide6.QtWidgets import QPushButton

    button = tab.findChild(QPushButton, name) if tab is not None else None
    if button is None or not button.isVisibleTo(tab.window()) or not button.isEnabled():
        return None
    return button


def _name_draft(call, tab):
    from PySide6.QtWidgets import QDialog

    args = call.arguments
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError(INVALID_ARGUMENTS, "Give the draft's name.")
    button = _button(tab, "MeshEditorNameDraftButton")
    if button is None:
        raise ToolError(UNAVAILABLE, "This mesh has no draft to name: open it from Browse Archives first.")

    refused: list[ToolError] = []

    def fill(dialog) -> int:
        # A button's slot swallows exceptions, so a refusal cancels the dialog and is raised after.
        dialog.name_edit.setText(name)
        project = str(args.get("project") or "")
        if project:
            combo = dialog.project_combo
            index = next((i for i in range(combo.count())
                          if project in (str(combo.itemData(i) or ""), combo.itemText(i))), -1)
            if index < 0:
                refused.append(ToolError(NOT_FOUND, f"There is no project {project!r}; make it in Drafts & Mods "
                                                    "first."))
                return QDialog.DialogCode.Rejected
            combo.setCurrentIndex(index)
        if not dialog.name():
            refused.append(ToolError(INVALID_ARGUMENTS, "That name is empty once cleaned up."))
            return QDialog.DialogCode.Rejected
        return QDialog.DialogCode.Accepted

    from cdmw.mcp.ui_actions import run_action

    def press():
        button.click()
        if refused:
            raise refused[0]
        return {"pressed": "name_draft"}

    outcome = run_action(call.context, press, dialogs={"MeshEditorNameDraftDialog": fill})
    outcome = {**(outcome.pop("result", None) or {}), **{k: v for k, v in outcome.items() if v}}
    lineage = call.context.ui_call(lambda: dict(getattr(tab, "mesh_editor_draft_lineage", {}) or {}))
    return {**outcome, "draft": {"name": lineage.get("display_name", ""), "project": lineage.get("project_id", "")}}


def _session(call):
    action = call.arguments["action"]
    tab = call.context.ui_call(lambda: shown_document(call.context))
    if tab is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    if action == "name_draft":
        return _name_draft(call, tab)

    def press():
        button = _button(tab, RESULT_BUTTONS[action])
        if button is None:
            raise ToolError(UNAVAILABLE, "That button is not shown: finish the edit first (mesh_finish), and "
                                         "Return to Create New Item only shows for a Create New Item model.")
        button.click()
        return {"pressed": action, "message": "mesh_state says when the editor is ready again."
                if action in ("resume", "next_pass") else ""}

    return _act(call, press)


def mesh_session_tools() -> list[Tool]:
    return [
        Tool(name="mesh.session", family="mesh", title="Mesh Editor session buttons",
             description="Presses the Mesh Editor's session buttons. After mesh_finish: 'resume' (Resume current "
                         "edit), 'next_pass' (Start next edit pass), 'add_to_archive_browser', 'check' (Check mesh) "
                         "and 'return_to_new_item' for a Create New Item model. 'name_draft' names the open draft "
                         "(name) and puts it in an existing project (its name or id), as Name Draft... does.",
             input_schema=object_schema({"action": {"type": "string", "enum": list(ACTIONS)},
                                         "name": {"type": "string", "maxLength": 200},
                                         "project": {"type": "string", "maxLength": 200}}, ["action"]),
             effect=EDIT, route="ui:MeshEditorRustResult* buttons|MeshEditorNameDraftButton", handler=_session,
             runs_on=ON_WORKER),
    ]


__all__ = ["mesh_session_tools"]
