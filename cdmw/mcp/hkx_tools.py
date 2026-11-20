"""The HKX Physics Editor as typed tools (MCP gap plan item 14, HKX part).

``files.hkx_edit`` opens the editor on the ``.hkx`` file selected in Browse
Archives (``view_open`` selects one) and changes joint limits, stiffness and
names through the dialog's own spin boxes, scale and name cells, so its ranges
and its change list apply. ``files.hkx_state`` reads it. ``files.hkx_save``
presses Save HKX File and answers its chooser with ``save_file``; the dialog's
own minimum-above-maximum check refuses a bad save. ``files.hkx_save_mod``
presses Save as DMM Mod and fills the mod-ready export prompt (folder and package
details). The archives are never changed. Swapping collision stays on the generic
controls (``app_ui_act``) for now.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp import mod_ready_prompt
from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, TEXT, choices, press, required, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

OPEN_WAIT_S = 30.0
SAVE_WAIT_S = 60.0


def _archive(call):
    archive = getattr(window(call), "archive", None)
    if archive is None or not hasattr(archive, "_open_current_hkx_physics_editor"):
        raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
    return archive


def _dialog(archive, *, needed=True):
    dialog = getattr(archive, "_hkx_physics_editor_dialog", None)
    if dialog is not None and (dialog.closed or not dialog.isVisible()):
        dialog = None
    if dialog is None and needed:
        raise ToolError(UNAVAILABLE, "The HKX Physics Editor is not open. Select a .hkx file and call "
                                     "files_hkx_edit with action open.")
    return dialog


def _role():
    from cdmw.ui.archive_browser import hkx_physics_editor_dialog

    return hkx_physics_editor_dialog._ORIGINAL_ROLE


def _state(archive) -> dict[str, object]:
    from cdmw.ui.archive_browser.hkx_physics_editor_dialog import joint_display_name, joint_type_text

    dialog = _dialog(archive, needed=False)
    if dialog is None:
        return {"open": False}
    session = dialog.session
    joints = []
    for joint in session.joints:
        joints.append({
            "joint": joint.index, "name": joint_display_name(joint), "type": joint_type_text(joint),
            "fields": [{"field": field.key, "value": dialog._field_value(joint, field), "shipped": field.value,
                        "minimum": field.minimum, "maximum": field.maximum, "can_change": bool(field.editable),
                        **({} if field.editable else {"reason": field.reason})}
                       for field in joint.fields],
        })
    names = [{"name": name.item, "role": name.role, "text": name.text,
              **({"new_text": dialog._renames[name.item]} if name.item in dialog._renames else {})}
             for name in session.names]
    return {"open": True, "path": session.path, "kind": session.kind, "editable": bool(session.editable),
            "joints": joints, "names": names, "changes": dialog.change_count(),
            "changes_text": dialog.changes_label.text(), "range_problem": dialog.range_problem(),
            "collision_from": dialog._replacement[0] if dialog._replacement else ""}


def _read(call):
    return ui(call, lambda: _state(_archive(call)))


def _select_joint(dialog, index):
    tree = getattr(dialog, "joint_tree", None)
    if tree is None:
        raise ToolError(UNAVAILABLE, "This HKX file has no joints CDMW can edit.")
    if not tree.isEnabled():
        raise ToolError(UNAVAILABLE, "Joints cannot change while another file's collision is used.")
    for row in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(row)
        if int(item.data(0, _role())) == index:
            tree.setCurrentItem(item)
            return
    raise ToolError(NOT_FOUND, f"There is no joint {index}; files_hkx_state lists them.")


def _open(call):
    def start():
        archive = _archive(call)
        entry = archive._current_archive_hkx_entry()
        if entry is None:
            raise ToolError(UNAVAILABLE, "Select a Crimson Desert .hkx file in Browse Archives first "
                                         "(view_open selects one).")
        archive._hkx_physics_editor_dialog = None
        archive._open_hkx_physics_editor_for_entry(entry)
        return archive

    archive = call.context.ui_call(start)
    deadline = time.monotonic() + OPEN_WAIT_S
    while call.context.ui_call(lambda: _dialog(archive, needed=False)) is None:
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The HKX Physics Editor did not open in time.")
        time.sleep(0.05)
    return ui(call, lambda: _state(archive))


def _edit(call):
    args = call.arguments
    action = args["action"]
    if action == "open":
        return _open(call)

    def change():
        archive = _archive(call)
        dialog = _dialog(archive)
        if action == "set_joint":
            _select_joint(dialog, required(args, "joint"))
            key = required(args, "field")
            spin = dialog._joint_spins.get(key)
            if spin is None:
                raise ToolError(NOT_FOUND, f"This joint has no {key}.",
                                {"fields": sorted(dialog._joint_spins)})
            if not spin.isEnabled():
                raise ToolError(REFUSED, spin.toolTip() or f"{key} cannot change on this joint.")
            value = float(required(args, "value"))
            if not spin.minimum() <= value <= spin.maximum():
                raise ToolError(INVALID_ARGUMENTS, f"Choose {key} from {spin.minimum():g} to {spin.maximum():g}.")
            spin.setValue(value)
        elif action == "reset_joint":
            _select_joint(dialog, required(args, "joint"))
            press(dialog.reset_joint_button)
        elif action == "scale_stiffness":
            factor = float(required(args, "factor"))
            box = dialog.stiffness_factor if hasattr(dialog, "stiffness_factor") else None
            if box is None:
                raise ToolError(UNAVAILABLE, "This HKX file has no joints CDMW can edit.")
            if not box.minimum() <= factor <= box.maximum():
                raise ToolError(INVALID_ARGUMENTS, f"Choose a factor from {box.minimum():g} to {box.maximum():g}.")
            box.setValue(factor)
            dialog.apply_stiffness_factor(box.value())  # what Apply to All Joints runs
        elif action == "rename":
            table = getattr(dialog, "names_table", None)
            if table is None:
                raise ToolError(UNAVAILABLE, "This HKX file has no names CDMW can change.")
            item = required(args, "name")
            text = str(required(args, "text"))
            for row in range(table.rowCount()):
                cell = table.item(row, 2)
                if int(cell.data(_role())) == item:
                    cell.setText(text)
                    break
            else:
                raise ToolError(NOT_FOUND, f"There is no name {item}; files_hkx_state lists them.")
        elif action == "reset_all":
            press(dialog.reset_button)
        return _state(archive)

    return ui(call, change)


def _save(call):
    target = Path(call.arguments["save_file"])
    if target.suffix.lower() != ".hkx":
        raise ToolError(INVALID_ARGUMENTS, "Save the edited file as a .hkx file.")
    before = target.stat().st_mtime_ns if target.exists() else None

    def save():
        archive = _archive(call)
        dialog = _dialog(archive)
        press(dialog.save_file_button)
        return {"path": dialog.session.path}

    outcome = ui(call, save, {"save_file": str(target)})
    warned = [ask for ask in outcome.get("asked", ()) if ask.get("kind") == "warning"]
    if warned:
        raise ToolError(REFUSED, str(warned[0].get("text") or "The HKX Physics Editor refused the save."),
                        {"asked": outcome.get("asked")})
    deadline = time.monotonic() + SAVE_WAIT_S
    while not (target.exists() and target.stat().st_mtime_ns != before):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The HKX Physics Editor did not save in time.", outcome)
        time.sleep(0.05)
    return {**outcome, "saved": str(target)}


def _save_mod(call):
    args = call.arguments
    folder = Path(str(args["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")
    before = mod_ready_prompt.children(folder)

    def save():
        archive = _archive(call)
        dialog = _dialog(archive)
        press(dialog.save_mod_button)
        return {"path": dialog.session.path}

    outcome = ui(call, save, mod_ready_prompt.answers(args), dialogs=mod_ready_prompt.dialogs(args))
    return mod_ready_prompt.wait_for_package(call, folder, before, outcome, "Save as DMM Mod")


def hkx_tools():
    return [
        tool("files.hkx_state", READ,
             "Read the open HKX Physics Editor: joints with each limit's value, shipped value and range, names, "
             "the number of changes and any minimum-above-maximum problem.",
             "ui:HkxPhysicsEditorDialog", _read),
        tool("files.hkx_edit", EDIT,
             "Work the HKX Physics Editor: open it on the .hkx file selected in Browse Archives, set a joint's "
             "limit or stiffness (joint, field, value), reset a joint or everything, scale every joint's "
             "stiffness (factor), or rename a name (name, text). The dialog's ranges apply.",
             "ui:HkxPhysicsEditorDialog", _edit,
             {"action": choices("open", "set_joint", "reset_joint", "scale_stiffness", "rename", "reset_all"),
              "joint": ROW, "field": TEXT, "value": {"type": "number"}, "factor": {"type": "number"},
              "name": ROW, "text": {**TEXT, "minLength": 1}},
             ("action",), runs_on=ON_WORKER),
        tool("files.hkx_save", OUTPUT,
             "Press Save HKX File: write the edited file to save_file (.hkx). The game archives are not changed; "
             "test the result in game.",
             "ui:HkxPhysicsEditorDialog.save_file_button", _save,
             {"save_file": PATH}, ("save_file",), output_paths=("save_file",), runs_on=ON_WORKER),
        tool("files.hkx_save_mod", OUTPUT,
             "Press Save as DMM Mod: write a mod folder that replaces this file in game, under folder (an existing "
             "folder outside the game folder), with the package title, version, author and description given. "
             "CDMW remembers the folder and details, as the prompt does. The game archives are not changed; test "
             "the mod in game.",
             "ui:HkxPhysicsEditorDialog.save_mod_button", _save_mod,
             {"folder": PATH, **mod_ready_prompt.SCHEMA}, ("folder",), output_folders=("folder",),
             runs_on=ON_WORKER),
    ]


__all__ = ["hkx_tools"]
