"""The Action Chart Editor as typed tools (MCP gap plan item 14, action chart part).

``files.action_chart_edit`` opens the editor on the ``.paac`` chart selected in Browse
Archives (``view_open`` selects one) and makes edits through the editor's own
controls: the chart speed rate, an animation's timing values, its clip and blend space,
a frame event's fields, and Replace Everywhere on the Names and Paths tab. Apply and
Re-read writes the pending edits into a copy and reads it back, as the button does.
``files.action_chart_state`` reads the editor. ``files.action_chart_export`` presses
Export DMM Mod, fills the mod details and saves the mod folder under ``folder``; the
game archives are never changed. Send to DMM and Other Charts Playing This Clip stay on
the generic controls (``app_ui_act``) for now.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, TEXT, choices, press, required, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

OPEN_WAIT_S = 180.0
TASK_WAIT_S = 120.0


def _archive(call):
    archive = getattr(window(call), "archive", None)
    if archive is None or not hasattr(archive, "_open_current_archive_action_chart_editor"):
        raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
    return archive


def _editors(archive) -> list:
    return [dialog for dialog in getattr(archive, "_action_chart_editors", None) or () if dialog.isVisible()]


def _editor(archive):
    editors = _editors(archive)
    if not editors:
        raise ToolError(UNAVAILABLE, "The Action Chart Editor is not open. Select a .paac chart and call "
                                     "files_action_chart_edit with action open.")
    return editors[-1]


def _number(value) -> float:
    return round(float(value), 6)


def _state(archive, args=None) -> dict[str, object]:
    from cdmw.services.action_chart_edit_service import animation_event_rows, animation_value_rows, string_rows

    editors = _editors(archive)
    if not editors:
        return {"open": False}
    dialog = editors[-1]
    args = args or {}
    chart, data = dialog._chart, dialog._data
    needle = str(args.get("query") or "").strip().lower()
    offset, count = int(args.get("offset") or 0), int(args.get("count") or 100)
    animations = [{"animation": animation.index, "clip": chart.clip_name(animation),
                   "blend": chart.blend_name(animation), "start": _number(animation.start_time),
                   "end": _number(animation.end_time), "events": len(animation.events)}
                  for animation in chart.animations
                  if not needle or needle in f"{chart.clip_name(animation)} {chart.blend_name(animation)}".lower()]
    state: dict[str, object] = {
        "open": True, "path": dialog._path, "rate": _number(dialog.rate_spin.value()),
        "animations_total": len(animations), "offset": offset, "animations": animations[offset:offset + count],
        "tables": [dialog.table_combo.itemText(index) for index in range(dialog.table_combo.count())],
        "pending": [dialog.pending_list.item(row).text() for row in range(dialog.pending_list.count())],
        "changes": dialog.changes_view.toPlainText().splitlines(), "status": dialog.status_label.text(),
        "busy": dialog.busy(), "can_apply": dialog.apply_button.isEnabled(),
        "can_export": dialog.export_button.isEnabled(),
    }
    if args.get("animation") is not None:
        index = int(args["animation"])
        if not 0 <= index < len(chart.animations):
            raise ToolError(NOT_FOUND, f"There is no animation {index}; this chart has {len(chart.animations)}.")
        state["values"] = [{"field": row.field, "item": row.item, "value": _number(row.value),
                            **({"pending": dialog._pending_values[row.key]} if row.key in dialog._pending_values
                               else {})}
                           for row in animation_value_rows(chart, data, index)]
        state["frame_events"] = [{"event": row.item, "kind": row.kind_name, "begin": _number(row.begin),
                                  "fields": {name: value for name, value in row.fields},
                                  "shared_by": list(row.shared_by)}
                                 for row in animation_event_rows(chart, data, index)]
    if args.get("table") is not None:
        table = int(args["table"])
        if not 0 <= table < dialog.table_combo.count():
            raise ToolError(NOT_FOUND, f"There is no table {table}; tables lists them.")
        state["names"] = [{"index": row.index, "value": row.value, "uses": row.uses}
                          for row in string_rows(chart, data, table)][:500]
    return state


def _read(call):
    return ui(call, lambda: _state(_archive(call), call.arguments))


def _select_animation(dialog, index: int) -> None:
    from cdmw.ui.archive_browser.action_chart_editor_dialog import _KEY_ROLE

    for position in range(dialog.animation_table.rowCount()):
        if int(dialog.animation_table.item(position, 0).data(_KEY_ROLE)) == index:
            dialog.animation_table.setRowHidden(position, False)
            dialog.animation_table.selectRow(position)
            return
    raise ToolError(NOT_FOUND, f"There is no animation {index}; files_action_chart_state lists them.")


def _wait_idle(call, archive) -> None:
    deadline = time.monotonic() + TASK_WAIT_S
    while call.context.ui_call(lambda: _editor(archive).busy()):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The Action Chart Editor did not finish in time.")
        time.sleep(0.05)


def _open(call):
    def start():
        archive = _archive(call)
        if archive._current_archive_action_chart_entry() is None:
            raise ToolError(UNAVAILABLE, "Select an editable .paac action chart in Browse Archives first "
                                         "(view_open selects one).")
        before = len(getattr(archive, "_action_chart_editors", None) or ())
        archive._open_current_archive_action_chart_editor()
        return archive, before

    archive, before = call.context.ui_call(start)
    deadline = time.monotonic() + OPEN_WAIT_S
    while call.context.ui_call(lambda: len(_editors(archive))) <= before:
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The Action Chart Editor did not open in time. Browse Archives' status says "
                                    "why (a shared action table cannot be edited).")
        time.sleep(0.05)
    return ui(call, lambda: _state(archive))


def _edit(call):
    args = call.arguments
    action = args["action"]
    if action == "open":
        return _open(call)

    def change():
        from cdmw.ui.archive_browser.action_chart_editor_dialog import _KEY_ROLE

        archive = _archive(call)
        dialog = _editor(archive)
        if dialog.busy():
            raise ToolError(UNAVAILABLE, "The Action Chart Editor is busy; wait for its task to finish.")
        if action == "set_rate":
            value = float(required(args, "value"))
            if not dialog.rate_spin.minimum() <= value <= dialog.rate_spin.maximum():
                raise ToolError(INVALID_ARGUMENTS, f"Choose a rate from {dialog.rate_spin.minimum():g} to "
                                                   f"{dialog.rate_spin.maximum():g}.")
            dialog.rate_spin.setValue(value)
        elif action == "set_value":
            _select_animation(dialog, int(required(args, "animation")))
            field, item = str(required(args, "field")), int(args.get("item") or 0)
            for row in range(dialog.value_table.rowCount()):
                key = tuple(dialog.value_table.item(row, 0).data(_KEY_ROLE))
                if key[0] == field and key[2] == item:
                    dialog.value_table.item(row, 2).setText(str(float(required(args, "value"))))
                    break
            else:
                raise ToolError(NOT_FOUND, f"Animation {args['animation']} has no value {field} (item {item}); "
                                           "files_action_chart_state with animation lists them.")
        elif action == "set_clip":
            _select_animation(dialog, int(required(args, "animation")))
            if args.get("clip") is None and args.get("blend") is None:
                raise ToolError(INVALID_ARGUMENTS, "Give clip, blend or both.")
            if args.get("clip") is not None:
                dialog.clip_edit.setText(str(args["clip"]))
            if args.get("blend") is not None:
                dialog.blend_edit.setText(str(args["blend"]))
            press(dialog.set_resources_button)
        elif action == "set_event":
            _select_animation(dialog, int(required(args, "animation")))
            event = int(required(args, "event"))
            dialog._select_event(event)
            row = dialog._selected_event()
            if row is None or row.item != event:
                raise ToolError(NOT_FOUND, f"Animation {args['animation']} has no frame event {event}.")
            if not dialog.set_event_button.isEnabled():
                raise ToolError(REFUSED, dialog.event_note.text() or "This event has no fields CDMW can change.")
            field = str(required(args, "field"))
            widget = dialog._event_widgets.get(field)
            if widget is None:
                raise ToolError(NOT_FOUND, f"This event has no field {field}.", {"fields": sorted(dialog._event_widgets)})
            value = required(args, "value")
            if hasattr(widget, "setValue"):
                widget.setValue(float(value))
            elif widget.isEditable():
                widget.setCurrentText(str(value))
            else:
                widget.setCurrentIndex(int(value))
            (dialog.every_user_radio if args.get("every_user") else dialog.only_this_radio).setChecked(True)
            press(dialog.set_event_button)
        elif action == "replace":
            table = int(required(args, "table"))
            if not 0 <= table < dialog.table_combo.count():
                raise ToolError(NOT_FOUND, f"There is no table {table}; files_action_chart_state lists them.")
            dialog.table_combo.setCurrentIndex(table)
            old = str(required(args, "old"))
            for position in range(dialog.string_table.rowCount()):
                if str(dialog.string_table.item(position, 1).data(_KEY_ROLE)) == old:
                    dialog.string_table.setRowHidden(position, False)
                    dialog.string_table.selectRow(position)
                    break
            else:
                raise ToolError(NOT_FOUND, f"{dialog.table_combo.itemText(table)} has no entry {old}.")
            dialog.new_string_edit.setText(str(required(args, "new")))
            press(dialog.replace_button)
        elif action == "remove_pending":
            index = int(required(args, "pending"))
            if not 0 <= index < dialog.pending_list.count():
                raise ToolError(NOT_FOUND, f"There is no pending edit {index}.")
            dialog.pending_list.setCurrentRow(index)
            press(dialog.remove_pending_button)
        elif action == "apply":
            if not dialog.apply_button.isEnabled():
                raise ToolError(UNAVAILABLE, "There are no pending edits to apply.")
            press(dialog.apply_button)
        elif action == "reset":
            press(dialog.reset_button)
        if dialog.status_label.styleSheet() and action != "apply":
            raise ToolError(REFUSED, dialog.status_label.text())
        return _state(archive)

    answers = {"confirm": "yes" if args.get("apply_unknown_names") else "no"}
    outcome = ui(call, change, answers)
    if action == "apply":
        archive = call.context.ui_call(lambda: _archive(call))
        _wait_idle(call, archive)
        outcome = {**outcome, **ui(call, lambda: _state(archive))}
        if outcome.get("pending"):
            raise ToolError(REFUSED, str(outcome.get("status") or "The edit was not applied."), outcome)
    return outcome


def _export(call):
    from cdmw.ui.archive_browser.action_chart_export_dialog import ActionChartExportDialog

    args = call.arguments
    folder = Path(str(args["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The output folder does not exist: {folder}")

    def fill(details):
        if args.get("title"):
            details.title_edit.setText(str(args["title"]).strip())
        for key, edit in (("author", details.author_edit), ("version", details.version_edit)):
            if args.get(key):
                edit.setText(str(args[key]).strip())
        if args.get("description"):
            details.description_edit.setPlainText(str(args["description"]).strip())
        if args.get("keep_existing") is not None:
            details.keep_checkbox.setChecked(bool(args["keep_existing"]))
        details.folder_button.click()  # Save Mod Folder...; its own check that the mod has a name
        if details.result() != details.DialogCode.Accepted:
            raise ToolError(INVALID_ARGUMENTS, details.error_label.text() or "The mod needs a name.")
        return details.result()

    holder: dict = {}

    def start():
        dialog = _editor(_archive(call))
        if not dialog.export_button.isEnabled():
            raise ToolError(UNAVAILABLE, dialog.export_button.toolTip() or "There is nothing to export yet: apply "
                                                                         "the edits first.")
        holder["dialog"] = dialog
        press(dialog.export_button)
        return {"path": dialog._path}

    outcome = ui(call, start, {"folder": str(folder)}, dialogs={ActionChartExportDialog: fill})
    warned = [ask for ask in outcome.get("asked", ()) if ask.get("kind") == "warning"]
    if warned:
        raise ToolError(REFUSED, str(warned[0].get("text") or "The export was refused."), {"asked": outcome["asked"]})
    dialog = holder["dialog"]
    deadline = time.monotonic() + TASK_WAIT_S
    while True:
        done, busy, status, plan = call.context.ui_call(
            lambda: (dialog.result_payload is not None, dialog.busy(), dialog.status_label.text(), dialog.export_plan))
        if done:
            parent = Path(str(getattr(plan, "parent", folder)))
            title = str(getattr(plan, "title", ""))
            return {**outcome, "saved": str(parent / title) if title else str(parent)}
        if not busy and status.startswith("The export failed"):
            raise ToolError(FAILED, status, outcome)
        if not busy and not status.startswith("Writing"):
            raise ToolError(FAILED, status or "The export did not start.", outcome)
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "The Action Chart Editor did not export in time.", outcome)
        time.sleep(0.05)


_NEW = {"type": ["number", "string"]}


def action_chart_tools():
    return [
        tool("files.action_chart_state", READ,
             "Read the open Action Chart Editor: the chart's speed rate, its animations in pages (query filters by "
             "clip or blend space), pending edits, changes from the shipped chart and whether Apply or Export is "
             "possible. animation adds that animation's timing values and frame events; table adds that table's "
             "names and paths.",
             "ui:ActionChartEditorDialog", _read,
             {"query": TEXT, "offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500},
              "animation": ROW, "table": ROW}),
        tool("files.action_chart_edit", EDIT,
             "Work the Action Chart Editor: open it on the .paac chart selected in Browse Archives; set the chart "
             "speed rate (value); set an animation's timing value (animation, field, item, value); set its clip or "
             "blend space (animation, clip, blend); set a frame event field (animation, event, field, value, "
             "every_user); Replace Everywhere in a names table (table, old, new); remove a pending edit (pending); "
             "apply the pending edits and read the chart back (apply_unknown_names answers the editor's check of "
             "names the game does not have); or reset to the shipped chart. Edits are not confirmed in game.",
             "ui:ActionChartEditorDialog", _edit,
             {"action": choices("open", "set_rate", "set_value", "set_clip", "set_event", "replace",
                                "remove_pending", "apply", "reset"),
              "animation": ROW, "field": TEXT, "item": ROW, "value": _NEW, "clip": TEXT, "blend": TEXT,
              "event": ROW, "every_user": BOOL, "table": ROW, "old": TEXT, "new": TEXT, "pending": ROW,
              "apply_unknown_names": BOOL},
             ("action",), runs_on=ON_WORKER),
        tool("files.action_chart_export", OUTPUT,
             "Press Export DMM Mod in the Action Chart Editor and save the mod folder under folder, with the mod "
             "name (title), author, version and description given; keep_existing keeps other charts already in a "
             "mod of that name. The game archives are not changed. Action chart edits have not been confirmed in "
             "game; test the mod there.",
             "ui:ActionChartEditorDialog.export_button", _export,
             {"folder": PATH, "title": TEXT, "author": TEXT, "version": TEXT, "description": TEXT,
              "keep_existing": BOOL},
             ("folder",), output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["action_chart_tools"]
