"""Add Bones as typed tools (MCP gap plan item 13, Add Bones part).

Both tools act on the ``.pab`` skeleton selected in Browse Archives (``view_open``
selects one). ``files.skeleton_read`` lists its bones. ``files.skeleton_add_bones``
loads the new bones into the Add Bones dialog as a draft, so the dialog's own checks
(unique names, a parent that exists, a skeleton the writer accepts) apply, then applies
them as Save as Mod does and answers the mod-ready export prompt. The game archives
are never changed; added bones are untested in game.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp import mod_ready_prompt
from cdmw.mcp.errors import INVALID_ARGUMENTS, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, TEXT, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

MAX_BONES = 64


def _source(call):
    """The selected skeleton entry (UI thread), then its bytes (this worker)."""

    from cdmw.services.archive_read_service import read_archive_entry_data

    def selected():
        archive = getattr(window(call), "archive", None)
        if archive is None or not hasattr(archive, "_write_pab_edit_loose_mod"):
            raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
        entry = archive._current_archive_pab_entry()
        if entry is None:
            raise ToolError(UNAVAILABLE, "Select a .pab skeleton in Browse Archives first (view_open selects one).")
        return archive, entry

    archive, entry = call.context.ui_call(selected)
    call.check_cancelled()
    return archive, entry, bytes(read_archive_entry_data(entry)[0])


def _read(call):
    from cdmw.modding.skeleton_writer import read_pab_document

    _archive, entry, data = _source(call)
    try:
        document = read_pab_document(data, entry.path)
    except ValueError as exc:
        raise ToolError(UNAVAILABLE, str(exc)) from None
    bones = document.bones
    return {"path": entry.path, "variant": document.variant,
            "bones": [{"index": index, "name": bone.name,
                       "parent": bones[bone.parent_index].name if 0 <= bone.parent_index < len(bones) else "",
                       "world_position": [round(v, 6) for v in bone.bind_matrix[12:15]]}
                      for index, bone in enumerate(bones)]}


def _triple(value, default):
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ToolError(INVALID_ARGUMENTS, "position, angles and scale take three numbers each.")
    return tuple(float(part) for part in value)


def _add(call):
    from cdmw.modding.skeleton_writer import PabEditRefused
    from cdmw.services.pab_skeleton_edit_service import (
        PabAppendEdit, apply_pab_edits, dumps_pab_edit_json, euler_degrees_to_quaternion,
    )
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog

    args = call.arguments
    folder = Path(str(args["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")
    wanted = list(args["bones"])
    if not 1 <= len(wanted) <= MAX_BONES:
        raise ToolError(INVALID_ARGUMENTS, f"Give 1 to {MAX_BONES} bones.")
    archive, entry, data = _source(call)
    drafts = tuple(PabAppendEdit(str(bone["parent"]), str(bone["name"]).strip(),
                                 position=_triple(bone.get("position"), (0.0, 0.0, 0.0)),
                                 rotation=euler_degrees_to_quaternion(*_triple(bone.get("angles"), (0.0, 0.0, 0.0))),
                                 scale=_triple(bone.get("scale"), (1.0, 1.0, 1.0)))
                   for bone in wanted)

    def check():
        dialog = PabBoneEditorDialog(data, entry.path, archive,
                                     draft_directory=archive._default_archive_pab_edit_json_path(entry).parent)
        try:
            loaded = dialog.load_draft_text(dumps_pab_edit_json(data, entry.path, drafts))
            error = dialog._error if loaded else ""
            return loaded, error, dialog.edits()
        finally:
            dialog.deleteLater()

    try:
        outcome = ui(call, lambda: dict(zip(("loaded", "error", "edits"), check())))
    except PabEditRefused as exc:
        raise ToolError(REFUSED, str(exc)) from None
    asked = outcome.get("asked")
    if not outcome.get("loaded"):
        text = next((ask.get("text") for ask in asked or () if ask.get("kind") == "warning"), "")
        raise ToolError(REFUSED, str(text or "The Add Bones dialog refused the bones."), {"asked": asked})
    if outcome.get("error"):
        raise ToolError(REFUSED, str(outcome["error"]))
    edits = outcome["edits"]
    call.check_cancelled()
    try:
        applied = apply_pab_edits(data, edits, path=entry.path)  # what Save as Mod runs
    except (PabEditRefused, ValueError) as exc:
        raise ToolError(REFUSED, str(exc)) from None
    before = mod_ready_prompt.children(folder)

    def write():
        archive._write_pab_edit_loose_mod(entry, applied)
        return {"path": entry.path, "added": list(applied.appended),
                "bones": [applied.source_bone_count, applied.bone_count]}

    written = ui(call, write, mod_ready_prompt.answers(args), dialogs=mod_ready_prompt.dialogs(args))
    return mod_ready_prompt.wait_for_package(call, folder, before, written, "Add Bones")


_TRIPLE = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_BONE = {"type": "object", "additionalProperties": False, "required": ["parent", "name"],
         "properties": {"parent": TEXT, "name": {**TEXT, "minLength": 1}, "position": _TRIPLE, "angles": _TRIPLE,
                        "scale": _TRIPLE}}


def skeleton_tools():
    return [
        tool("files.skeleton_read", READ,
             "List the bones of the .pab skeleton selected in Browse Archives: index, name, parent and world "
             "position.",
             "ui:PabBoneEditorDialog", _read, runs_on=ON_WORKER),
        tool("files.skeleton_add_bones", OUTPUT,
             "Add Bones: add new child bones (parent, name, and optional local position, angles in degrees and "
             "scale) to the selected .pab skeleton and write it as a mod package under folder, with the package "
             "details given. The Add Bones dialog checks the bones; existing bones are never changed and the game "
             "archives are not changed. New bones follow their parent and are untested in game.",
             "ui:PabBoneEditorDialog.save_mod_button", _add,
             {"bones": {"type": "array", "items": _BONE, "minItems": 1, "maxItems": MAX_BONES},
              "folder": PATH, **mod_ready_prompt.SCHEMA},
             ("bones", "folder"), output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["skeleton_tools"]
