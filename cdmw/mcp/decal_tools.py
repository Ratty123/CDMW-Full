"""Edit Skinned Decal as typed tools (MCP gap plan item 13).

Both tools act on the ``.paseq`` file selected in Browse Archives, as the
right-click entry does (``view_open`` selects one by path).
``files.decal_read`` lists the decal's settings as the dialog shows them.
``files.decal_save`` fills the dialog's own fields with the changes, lets its
Save check every value, and saves the loose copy to ``save_file`` through the
same chooser and worker the menu entry uses. The archives are never changed.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

SAVE_WAIT_S = 60.0


def _source(call):
    """The selected entry (UI thread), then its decal document (this worker)."""

    from cdmw.services.skinned_decal_service import load_decal_source
    from cdmw.ui.archive_browser.workflow_dependencies import (
        ArchiveWorkflowDependenciesUnavailable, archive_workflow_dependency_context,
    )

    def selected():
        archive = getattr(window(call), "archive", None)
        if archive is None or not hasattr(archive, "_show_skinned_decal_editor"):
            raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
        entry = archive._current_archive_entry()
        if entry is None or str(entry.extension).lower() != ".paseq":
            raise ToolError(UNAVAILABLE, "Select a .paseq file in Browse Archives first (view_open selects one).")
        try:
            return archive, archive_workflow_dependency_context(archive, entry).selected_entry
        except ArchiveWorkflowDependenciesUnavailable as exc:
            raise ToolError(UNAVAILABLE, str(exc)) from None

    archive, entry = call.context.ui_call(selected)
    call.check_cancelled()
    try:
        return archive, load_decal_source(entry)
    except ValueError as exc:
        raise ToolError(UNAVAILABLE, str(exc)) from None


def _fields(document) -> list[dict[str, object]]:
    return [{"setting": field.path, "type": field.type_name, "value": field.text()} for field in document.fields]


def _read(call):
    _archive, source = _source(call)
    return {"path": source.entry.path, "settings": _fields(source.document)}


def _save(call):
    from PySide6.QtWidgets import QDialog

    from cdmw.ui.archive_browser.skinned_decal_dialog import SkinnedDecalDialog

    args = call.arguments
    changes = {str(key): str(value) for key, value in dict(args["changes"]).items()}
    if not 1 <= len(changes) <= 256:
        raise ToolError(INVALID_ARGUMENTS, "Give 1 to 256 changes.")
    target = Path(args["save_file"])
    if target.suffix.lower() != ".paseq":
        raise ToolError(INVALID_ARGUMENTS, "Save the decal sequence as a .paseq file.")
    archive, source = _source(call)
    known = {field.path for field in source.document.fields}
    unknown = sorted(set(changes) - known)
    if unknown:
        raise ToolError(NOT_FOUND, f"The decal has no setting {unknown[0]}; files_decal_read lists them.",
                        {"unknown": unknown[:20]})

    def fill(dialog):
        for field, editor in dialog._editors:
            if field.path in changes:
                editor.setText(changes[field.path])
        dialog.accept()  # the dialog's own check of every changed value
        return QDialog.DialogCode.Accepted if dialog.result() == QDialog.DialogCode.Accepted \
            else QDialog.DialogCode.Rejected

    def show():
        request_id = int(getattr(archive, "_skinned_decal_request_id", 0)) + 1
        archive._skinned_decal_request_id = request_id
        archive._show_skinned_decal_editor(request_id, source)
        return {"path": source.entry.path}

    before = target.stat().st_mtime_ns if target.exists() else None
    outcome = ui(call, show, {"save_file": str(target)}, dialogs={SkinnedDecalDialog: fill})
    refused = [ask for ask in outcome.get("asked", ()) if ask.get("kind") in ("warning", "message")
               and "Invalid Decal Setting" in str(ask.get("title", ""))]
    if refused:
        raise ToolError(INVALID_ARGUMENTS, str(refused[0].get("text") or "A decal setting is not valid."),
                        {"asked": outcome.get("asked")})
    deadline = time.monotonic() + SAVE_WAIT_S
    while not (target.exists() and target.stat().st_mtime_ns != before):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Browse Archives did not save the decal copy in time.", outcome)
        time.sleep(0.05)
    return {**outcome, "saved": str(target), "changed": sorted(changes)}


def decal_tools():
    return [
        tool("files.decal_read", READ,
             "List the settings of the skinned decal in the .paseq file selected in Browse Archives, as Edit "
             "Skinned Decal shows them: setting path, type and value.",
             "ui:SkinnedDecalDialog", _read, runs_on=ON_WORKER),
        tool("files.decal_save", OUTPUT,
             "Edit Skinned Decal: change settings of the selected .paseq file (changes maps a setting path from "
             "files_decal_read to its new text) and save a loose .paseq copy to save_file. The dialog checks "
             "each value; the archives are not changed.",
             "ui:SkinnedDecalDialog.accept", _save,
             {"changes": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 4096}},
              "save_file": PATH},
             ("changes", "save_file"), output_paths=("save_file",), runs_on=ON_WORKER),
    ]


__all__ = ["decal_tools"]
