"""Sound banks and replacement audio as typed tools (MCP gap plan item 14, sound part).

All three act on the file selected in Browse Archives, as its right-click entries do
(``view_open`` selects one). ``files.sound_bank_read`` lists what Edit Sound Bank can
change in a ``.bnk``. ``files.sound_bank_write`` fills the editor's own table, Add
Property and Remove Selected Property controls, presses Write Loose Mod, and answers the
mod-ready export prompt. ``files.audio_import`` is Import WAV as Loose Mod. Both write a
mod package under ``folder``; the game archives are never changed. Adding or removing
sounds in a random container stays on the generic controls (``app_ui_act``) for now.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp import mod_ready_prompt
from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, TEXT, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

_MAX_CHANGES = 500


def _selected(call, extensions: tuple[str, ...], what: str):
    def pick():
        archive = getattr(window(call), "archive", None)
        if archive is None or not hasattr(archive, "_edit_sound_bank_model"):
            raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
        entry = archive._current_archive_entry()
        if entry is None or str(entry.extension).lower() not in extensions:
            raise ToolError(UNAVAILABLE, f"Select {what} in Browse Archives first (view_open selects one).")
        return archive, entry

    return call.context.ui_call(pick)


def _model(call):
    from cdmw.core.archive_audio import read_sound_bank_editor_model

    archive, entry = _selected(call, (".bnk",), "a .bnk sound bank")
    call.check_cancelled()
    return archive, entry, read_sound_bank_editor_model(entry)


def _read(call):
    args = call.arguments
    _archive, entry, model = _model(call)
    needle = str(args.get("query") or "").strip().lower()
    rows = [row for row in model.rows if not needle or needle in f"{row.object_id} {row.target}".lower()]
    offset, count = int(args.get("offset") or 0), int(args.get("count") or 100)
    return {
        "path": entry.path, "notes": list(model.notes), "total": len(rows), "offset": offset,
        "values": [{"object": row.object_id, "type": row.kind_name, "value": row.target, "stored": row.value,
                    "whole_number": row.integer, "unit": row.unit} for row in rows[offset:offset + count]],
        "objects": [{"object": obj.object_id, "random_container": obj.kind == 5,
                     "can_add": list(obj.addable_properties), "can_add_range": list(obj.addable_ranges),
                     "sounds": list(obj.children)} for obj in model.objects],
    }


def _number(text: object, label: str) -> str:
    try:
        float(str(text))
    except ValueError:
        raise ToolError(INVALID_ARGUMENTS, f"{label} is not a number: {text}") from None
    return str(text)


def _fill(model, args):
    """Fill Edit Sound Bank with the changes, then press Write Loose Mod (UI thread, inside its exec)."""

    from PySide6.QtWidgets import QPushButton

    values = list(args.get("values") or ())
    adds = list(args.get("add") or ())
    removes = list(args.get("remove") or ())
    if not values and not adds and not removes:
        raise ToolError(INVALID_ARGUMENTS, "Give values, add or remove: nothing would change.")
    if len(values) + len(adds) + len(removes) > _MAX_CHANGES:
        raise ToolError(INVALID_ARGUMENTS, f"Give at most {_MAX_CHANGES} changes in one write.")
    rows = {(row.object_id, row.target): index for index, row in enumerate(model.rows)}
    for change in values:
        if (int(change["object"]), str(change["value"])) not in rows:
            raise ToolError(NOT_FOUND, f"Object {change['object']} has no value {change['value']}; "
                                       "files_sound_bank_read lists them.")
        _number(change["new"], change["value"])
    objects = {obj.object_id: obj for obj in model.objects}
    for change in adds:
        obj = objects.get(int(change["object"]))
        name = str(change["property"])
        kind = "range" if name.endswith(" range") else "property"
        bare = name[:-len(" range")] if kind == "range" else name
        offered = obj.addable_ranges if obj is not None and kind == "range" else (
            obj.addable_properties if obj is not None else ())
        if bare not in offered:
            raise ToolError(NOT_FOUND, f"Object {change['object']} cannot take {name}; files_sound_bank_read "
                                       "lists what each object can add.")
    for change in removes:
        target = str(change["value"])
        if (int(change["object"]), target) not in rows or not target.startswith(("property:", "range:")):
            raise ToolError(NOT_FOUND, f"Object {change['object']} has no added property {target} to remove.")

    def fill(dialog):
        for change in values:
            dialog.table.item(rows[(int(change["object"]), str(change["value"]))], 4).setText(str(change["new"]))
        add_button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Add Property")
        for change in adds:
            name = str(change["property"])
            data = f"range:{name[:-len(' range')]}" if name.endswith(" range") else f"property:{name}"
            dialog.object_combo.setCurrentIndex(dialog.object_combo.findData(int(change["object"])))
            dialog.property_combo.setCurrentIndex(dialog.property_combo.findData(data))
            dialog.value_edit.setText(str(change["new"]))
            add_button.click()
        if removes:
            remove_button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Remove Selected Property")
            dialog.table.clearSelection()
            for change in removes:
                dialog.table.selectRow(rows[(int(change["object"]), str(change["value"]))])
                remove_button.click()
                dialog.table.clearSelection()
        dialog.write_button.click()  # the editor's own check, then the mod-ready prompt
        return dialog.result()

    return fill


def _write(call):
    from cdmw.ui.archive_browser.sound_bank_editor import SoundBankEditorDialog

    args = call.arguments
    folder = Path(str(args["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")
    archive, entry, model = _model(call)
    if not model.rows and not model.objects:
        raise ToolError(UNAVAILABLE, " ".join(model.notes) or "This bank stores nothing the editor can change.")
    dialogs = {SoundBankEditorDialog: _fill(model, args), **mod_ready_prompt.dialogs(args)}
    before = mod_ready_prompt.children(folder)

    def show():
        archive._edit_sound_bank_model(entry, model)
        return {"path": entry.path}

    outcome = ui(call, show, mod_ready_prompt.answers(args), dialogs=dialogs)
    return mod_ready_prompt.wait_for_package(call, folder, before, outcome, "Edit Sound Bank")


def _import(call):
    from cdmw.domain.archives.constants import ARCHIVE_AUDIO_PATCH_EXTENSIONS

    args = call.arguments
    folder = Path(str(args["folder"]))
    source = Path(str(args["source"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")
    if not source.is_file():
        raise ToolError(NOT_FOUND, f"There is no audio file {source}.")
    archive, entry = _selected(call, tuple(ARCHIVE_AUDIO_PATCH_EXTENSIONS), "a sound file (.wem)")
    before = mod_ready_prompt.children(folder)

    def start():
        archive._start_archive_audio_patch(entry)
        return {"path": entry.path}

    outcome = ui(call, start, {**mod_ready_prompt.answers(args), "file": str(source)},
                 dialogs=mod_ready_prompt.dialogs(args))
    return mod_ready_prompt.wait_for_package(call, folder, before, outcome, "Import WAV as Loose Mod")


_VALUE = {"type": "object", "additionalProperties": False, "required": ["object", "value", "new"],
          "properties": {"object": ROW, "value": TEXT, "new": {"type": ["number", "string"]}}}
_ADD = {"type": "object", "additionalProperties": False, "required": ["object", "property", "new"],
        "properties": {"object": ROW, "property": TEXT, "new": {"type": ["number", "string"]}}}
_REMOVE = {"type": "object", "additionalProperties": False, "required": ["object", "value"],
           "properties": {"object": ROW, "value": TEXT}}
_PACKAGE = {"folder": PATH, **mod_ready_prompt.SCHEMA}


def sound_tools():
    return [
        tool("files.sound_bank_read", READ,
             "List what Edit Sound Bank can change in the .bnk selected in Browse Archives: its stored values "
             "(object, value name, stored value, unit) in pages, filtered by query, and each object's addable "
             "properties and the sounds in its random container.",
             "ui:SoundBankEditorDialog", _read,
             {"query": TEXT, "offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}},
             runs_on=ON_WORKER),
        tool("files.sound_bank_write", OUTPUT,
             "Edit Sound Bank as Loose Mod: give values new numbers (object, value, new), add properties "
             "(object, property, new; a range takes \"min, max\") or remove added ones (object, value), then "
             "write the edited bank as a mod package under folder, with the package title, version, author and "
             "description given. The editor checks every value; the game archives are not changed. Test the "
             "mod in game.",
             "ui:SoundBankEditorDialog.write_button", _write,
             {"values": {"type": "array", "items": _VALUE, "maxItems": _MAX_CHANGES},
              "add": {"type": "array", "items": _ADD, "maxItems": _MAX_CHANGES},
              "remove": {"type": "array", "items": _REMOVE, "maxItems": _MAX_CHANGES}, **_PACKAGE},
             ("folder",), output_folders=("folder",), runs_on=ON_WORKER),
        tool("files.audio_import", OUTPUT,
             "Import WAV as Loose Mod: replace the sound file selected in Browse Archives with source (.wav, "
             ".ogg, .mp3 or .wem) and write it, with the banks that play it, as a mod package under folder. "
             "The game archives are not changed. Test the mod in game.",
             "ui:archive.import_wav_loose_mod", _import,
             {"source": PATH, **_PACKAGE}, ("source", "folder"), output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["sound_tools"]
