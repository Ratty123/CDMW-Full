"""Browse Archives' Edit Game Table Values dialog as typed tools (MCP gap plan item 13).

``tables.editor_state`` reads the dialog: the loaded table, its rows in pages,
one row's values and the changes in this mod. ``tables.editor_edit`` opens the
dialog on a table, loads a table, and sets, restores or removes a value by
pressing the dialog's own controls, so its range checks and its DLC-only
refusal apply. ``tables.editor_write`` presses Write DMM Mod; the mod goes into
DMM's mods folder, never into the game.

Nothing here reads or writes a table itself: loading and writing run on the
shell's worker as the dialog's buttons start them.
"""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, TEXT, choices, press, required, tool, ui, window

PAGE = 100
_KEY = {"type": "integer"}


def _archive(call):
    archive = getattr(window(call), "archive", None)
    if archive is None or not hasattr(archive, "_open_game_table_editor"):
        raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
    return archive


def _dialog(archive, *, needed=True):
    dialog = getattr(archive, "_game_table_dialog", None)
    if dialog is None and needed:
        raise ToolError(UNAVAILABLE, "Edit Game Table Values is not open. Open it with tables_editor_edit "
                                     "action open.")
    return dialog


def _index(editor):
    return getattr(editor, "_index", None)


def _values(editor, row) -> list[dict[str, object]]:
    from cdmw.ui.new_item.game_tables_editor import value_label

    table = editor.loaded_table()
    values = []
    for position, value in enumerate(row.values):
        owner = getattr(value, "owner", "") or ""
        label = value_label(value.target, owner) if owner or isinstance(value.target, str) else value.label
        pending = editor._edits.get((table, row.key, value.target))
        entry = {"value": position, "label": label, "current": value.value, "about": value.rule.note}
        if pending is not None:
            entry["in_this_mod"] = pending.value
        values.append(entry)
    return values


def _state(archive, arguments=None) -> dict[str, object]:
    from cdmw.ui.new_item.game_tables_editor import table_names

    arguments = arguments or {}
    dialog = _dialog(archive, needed=False)
    if dialog is None:
        return {"open": False, "tables": sorted(_editable())}
    editor = dialog.editor
    index = _index(editor)
    names = table_names()
    state: dict[str, object] = {
        "open": dialog.isVisible(), "table": editor.current_table(), "loaded": editor.loaded_table(),
        "loading": not editor.load.isEnabled(), "message": editor.message.text(),
        "mod_name": dialog.mod_name.text(), "can_write": dialog.write.isEnabled(),
        "tables": sorted(_editable()),
        "changes": [{"change": position, "table": edit.table, "table_name": names.get(edit.table, edit.table),
                     "row": edit.key, "target": str(edit.target), "value": edit.value}
                    for position, edit in enumerate(editor.edits())],
    }
    if index is None:
        return state
    query = str(arguments.get("query") or "").strip().casefold()
    rows = [row for row in index.rows if not query or query in row.name.casefold() or query == str(row.key)]
    offset = int(arguments.get("offset") or 0)
    count = int(arguments.get("count") or PAGE)
    state["rows"] = [{"row": row.key, "name": row.name, "copy": "DLC" if "." in row.layer else "Base",
                      "can_change": bool(row.editable), "values": len(row.values)}
                     for row in rows[offset:offset + count]]
    state["row_count"] = len(rows)
    state["more_rows"] = offset + count < len(rows)
    if arguments.get("row") is not None:
        row = _row(index, arguments["row"])
        state["values"] = _values(editor, row)
    return state


def _editable() -> frozenset[str]:
    from cdmw.core.static_table_records import editable_kinds

    return frozenset(editable_kinds())


def _row(index, key):
    row = next((row for row in index.rows if row.key == key), None)
    if row is None:
        raise ToolError(NOT_FOUND, f"The loaded {index.table} table has no row {key}.")
    return row


def _read(call):
    return ui(call, lambda: _state(_archive(call), call.arguments))


def _show_row(editor, key) -> None:
    """Select the row on the dialog as a user does: filter by its key, then click it."""

    editor.search.setText(str(key))
    for position in range(editor.rows.rowCount()):
        if editor.rows.item(position, 0).data(_key_role()) == key:
            editor.rows.selectRow(position)
            return
    raise ToolError(NOT_FOUND, f"Row {key} is not listed in the dialog.")


def _key_role():
    from cdmw.ui.new_item import game_tables_editor

    return game_tables_editor._KEY_ROLE


def _show_value(editor, row, position) -> None:
    if not 0 <= position < len(row.values):
        raise ToolError(NOT_FOUND, f"Row {row.key} has values 0 to {len(row.values) - 1}.")
    for line in range(editor.values.rowCount()):
        if editor.values.item(line, 0).data(_key_role()) == position:
            editor.values.selectRow(line)
            return
    raise ToolError(NOT_FOUND, "That value is not listed in the dialog.")


def _open(archive, args) -> None:
    from cdmw.ui.archive_browser.game_table_actions import table_kind

    path = str(args.get("path") or "")
    table = table_kind(path) if path else str(args.get("table") or "")
    if not table:
        raise ToolError(INVALID_ARGUMENTS, "Give the table, or the archive path of a .staticinfobody or "
                                           ".staticinfoheader file.")
    if table not in _editable():
        raise ToolError(REFUSED, f"CDMW has no proven values to edit in the {table} table.",
                        {"tables": sorted(_editable())})
    path = path or f"gamedata/binarystaticinfo__/bin/{table}.staticinfobody"
    archive._open_game_table_editor(SimpleNamespace(path=path, basename=path.rsplit("/", 1)[-1]))


def _edit(call):
    args = call.arguments
    action = args["action"]

    def change():
        archive = _archive(call)
        if action == "open":
            _open(archive, args)
            return _state(archive)
        dialog = _dialog(archive)
        editor = dialog.editor
        if action == "load":
            table = required(args, "table")
            position = editor.table.findData(table)
            if position < 0:
                raise ToolError(NOT_FOUND, f"The dialog lists no table {table}.", {"tables": sorted(_editable())})
            editor.table.setCurrentIndex(position)
            press(editor.load)
            return _state(archive)
        if action == "name":
            dialog.mod_name.setText(str(required(args, "name")).strip())
            return _state(archive)
        if action == "remove":
            position = required(args, "change")
            if not 0 <= position < editor.pending.rowCount():
                raise ToolError(NOT_FOUND, "There is no change with that number; tables_editor_state lists them.")
            editor.pending.selectRow(position)
            press(editor.remove)
            return _state(archive)
        index = _index(editor)
        if index is None:
            raise ToolError(UNAVAILABLE, "Load a table first.")
        row = _row(index, required(args, "row"))
        _show_row(editor, row.key)
        _show_value(editor, row, required(args, "value"))
        if action == "set":
            if not row.editable:
                raise ToolError(REFUSED, "This row exists only in the DLC copy; a DMM mod cannot change it.")
            editor.value.setText(str(required(args, "new_value")))
            press(editor.set)
            if editor.message.text().startswith("Enter a value from"):
                raise ToolError(INVALID_ARGUMENTS, editor.message.text())
        else:  # restore
            press(editor.restore)
        return _state(archive, {"row": row.key})

    return ui(call, change)


def _write(call):
    from cdmw.domain.output_paths import OutputPathRefused, check_output_path

    args = call.arguments
    answers = {"confirm": "yes" if args.get("replace") else "no"}
    if args.get("dmm_folder"):
        answers["folder"] = args["dmm_folder"]
    mods = _mods_folder(call, args.get("dmm_folder"))
    if mods is not None:
        try:
            check_output_path(str(mods), game_folder=call.context.game_folder(), allow_existing=True)
        except (OutputPathRefused, ValueError) as refused:
            raise ToolError(REFUSED, str(refused)) from None

    def write():
        archive = _archive(call)
        dialog = _dialog(archive)
        if args.get("name"):
            dialog.mod_name.setText(str(args["name"]).strip())
        press(dialog.write)
        return {**_state(archive), "dmm_mods_folder": str(mods) if mods is not None else ""}

    return ui(call, write, answers)


def _mods_folder(call, given):
    """DMM's mods folder the dialog will write into.

    A given dmm_folder is the only folder checked, and it is remembered as DMM's folder (as the dialog's own
    chooser does when the user picks one), so the dialog writes where the tool says. Without one, the dialog's
    own lookup applies: the remembered folder, then DMM's usual places.
    """

    from PySide6.QtCore import QSettings

    from cdmw.services.settings_service import resolve_settings_file_path
    from cdmw.ui.new_item import dmm_send_ui
    from cdmw.ui.widgets import request_settings_sync

    # The same settings file the dialog's own chooser reads.
    settings = QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)
    if given:
        install = Path(str(given))
        if not (install / "DMM.exe").is_file():
            raise ToolError(NOT_FOUND, f"{given} is not DMM's folder (the one that contains DMM.exe).")
    else:
        install = dmm_send_ui.find_dmm(str(settings.value(dmm_send_ui.DMM_FOLDER_SETTING, "") or ""))
        if install is None:
            raise ToolError(INVALID_ARGUMENTS, "CDMW does not know DMM's folder yet. Give dmm_folder: the folder "
                                               "that contains DMM.exe.")
    try:
        mods = dmm_send_ui.dmm_mods_folder(install)
    except ValueError as exc:
        raise ToolError(NOT_FOUND, str(exc)) from None
    if given:
        settings.setValue(dmm_send_ui.DMM_FOLDER_SETTING, str(install))
        request_settings_sync(settings)
    return mods


def game_table_tools():
    return [
        tool("tables.editor_state", READ,
             "Read Browse Archives' Edit Game Table Values dialog: the loaded table, its rows in pages (query "
             "filters by name or key), one row's values with row, and the changes in this mod.",
             "ui:GameTableEditDialog", _read,
             {"query": TEXT, "offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500},
              "row": _KEY}),
        tool("tables.editor_edit", EDIT,
             "Work Edit Game Table Values: open it on a table (table, or path of a .staticinfobody file), load "
             "another table, set a value (row, value, new_value) or restore it, remove a change, or name the "
             "mod. The dialog's own range checks apply; DLC-only rows cannot change.",
             "ui:GameTableEditDialog.editor", _edit,
             {"action": choices("open", "load", "set", "restore", "remove", "name"), "table": TEXT, "path": PATH,
              "row": _KEY, "value": ROW, "new_value": {"type": ["string", "number"]}, "change": ROW,
              "name": TEXT},
             ("action",)),
        tool("tables.editor_write", OUTPUT,
             "Press Write DMM Mod: write the changed tables as a new mod in DMM's mods folder. The game's "
             "archives are not changed. replace writes over a mod of the same name CDMW wrote earlier.",
             "ui:GameTableEditDialog.write", _write,
             {"name": TEXT, "dmm_folder": PATH, "replace": BOOL}, output_folders=("dmm_folder",)),
    ]


__all__ = ["game_table_tools"]
