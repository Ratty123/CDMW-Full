"""Textures > Upscale as typed tools (MCP gap plan item 11, the Upscale mode).

``textures.upscale_state`` reads the Upscale controls: the run settings, DDS Output,
the backend and its settings, the mod package choices, the workflow profiles and rules,
the matched files, the progress and the log. ``textures.upscale`` works those controls:
change settings, add, change, remove or reorder profiles and rules, assign a profile to
matched files, Scan, Preview Policy, Run Summary and Stop. ``textures.upscale_start``
presses Start into an output folder the user allows. Each action uses the page's own
controls, so the page's own checks and messages apply.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, choices, choose, output, press, required, tool, ui
from cdmw.mcp.tools import ON_WORKER

WAIT_S = 6 * 60 * 60
DIALOG_WAIT_S = 120
LOG_LINES = 40
UNCLASSIFIED_TITLE = "DDS Files Need Saved Classification"
#: The collapsible sections whose controls are built when first opened.
SECTIONS = ("settings_section", "dds_output_section", "filters_section", "chainner_section")
#: Settings an AI app may change, with the control that holds each. ``folder`` is a folder
#: to read from, ``output`` a folder the run writes to (it passes the output path rule).
FIELDS = {
    "original_dds_root": ("original_dds_edit", "folder"),
    "png_root": ("png_root_edit", "output"),
    "staging_png_root": ("dds_staging_root_edit", "output"),
    "output_root": ("output_root_edit", "output"),
    "dry_run": ("dry_run_checkbox", "check"),
    "incremental_resume": ("enable_incremental_resume_checkbox", "check"),
    "write_csv_log": ("csv_log_enabled_checkbox", "check"),
    "unique_basename_fallback": ("unique_basename_checkbox", "check"),
    "convert_dds_to_png": ("enable_dds_staging_checkbox", "check"),
    "dds_format_mode": ("dds_format_mode_combo", "combo"),
    "dds_custom_format": ("dds_custom_format_combo", "combo"),
    "dds_size_mode": ("dds_size_mode_combo", "combo"),
    "dds_custom_width": ("dds_custom_width_spin", "spin"),
    "dds_custom_height": ("dds_custom_height_spin", "spin"),
    "dds_mip_mode": ("dds_mip_mode_combo", "combo"),
    "dds_custom_mip_count": ("dds_custom_mip_spin", "spin"),
    "include_filters": ("filters_edit", "plain"),
    "backend": ("upscale_backend_combo", "combo"),
    "chainner_overrides": ("chainner_override_edit", "plain"),
    "ncnn_model": ("ncnn_model_combo", "combo"),
    "ncnn_scale": ("ncnn_scale_spin", "spin"),
    "ncnn_tile_size": ("ncnn_tile_size_spin", "spin"),
    "ncnn_extra_args": ("ncnn_extra_args_edit", "text"),
    "post_correction": ("upscale_post_correction_combo", "combo"),
    "texture_preset": ("upscale_texture_preset_combo", "combo"),
    "automatic_rules": ("enable_automatic_texture_rules_checkbox", "check"),
    "unsafe_technical_override": ("enable_unsafe_technical_override_checkbox", "check"),
    "retry_smaller_tile": ("retry_smaller_tile_checkbox", "check"),
    "create_mod_package": ("enable_mod_ready_loose_export_checkbox", "check"),
    "mod_package_root": ("mod_ready_export_root_edit", "output"),
    "package_title": ("mod_ready_package_title_edit", "text"),
    "package_version": ("mod_ready_package_version_edit", "text"),
    "package_author": ("mod_ready_package_author_edit", "text"),
    "package_description": ("mod_ready_package_description_edit", "text"),
    "package_nexus_url": ("mod_ready_package_nexus_url_edit", "text"),
    "mod_manager": ("mod_ready_manager_combo", "combo"),
    "conflict_mode": ("mod_ready_conflict_mode_combo", "combo"),
    "target_language": ("mod_ready_target_language_edit", "text"),
    "ready_zip": ("mod_ready_zip_checkbox", "check"),
}
#: A workflow profile's fields and their controls.
PROFILE_FIELDS = {
    "name": ("workflow_profile_name_edit", "text"),
    "action": ("workflow_profile_action_combo", "combo"),
    "format": ("workflow_profile_format_combo", "combo"),
    "size": ("workflow_profile_size_combo", "combo"),
    "custom_width": ("workflow_profile_custom_width_spin", "spin"),
    "custom_height": ("workflow_profile_custom_height_spin", "spin"),
    "mips": ("workflow_profile_mip_combo", "combo"),
    "custom_mip_count": ("workflow_profile_custom_mip_spin", "spin"),
    "ncnn_model": ("workflow_profile_ncnn_model_combo", "combo"),
    "ncnn_scale": ("workflow_profile_ncnn_scale_combo", "combo"),
    "override_tile": ("workflow_profile_ncnn_tile_override_checkbox", "check"),
    "tile_size": ("workflow_profile_ncnn_tile_spin", "spin"),
    "extra_args": ("workflow_profile_ncnn_extra_args_edit", "text"),
    "post_correction": ("workflow_profile_post_correction_combo", "combo"),
}
#: A texture rule's fields and their controls.
RULE_FIELDS = {
    "enabled": ("workflow_rule_enabled_checkbox", "check"),
    "match_mode": ("workflow_rule_match_mode_combo", "combo"),
    "pattern": ("workflow_rule_pattern_edit", "text"),
    "profile": ("workflow_rule_profile_combo", "combo"),
    "semantic": ("workflow_rule_semantic_combo", "editable_combo"),
    "planner_profile": ("workflow_rule_planner_profile_combo", "combo"),
    "colorspace": ("workflow_rule_colorspace_combo", "combo"),
    "alpha": ("workflow_rule_alpha_combo", "combo"),
    "intermediate": ("workflow_rule_intermediate_combo", "combo"),
}


def _workspace(call):
    from cdmw.mcp.texture_files import workspace

    view = workspace(call.context)
    for name in SECTIONS:
        getattr(view, name).ensure_body_built()
    return view


def _busy(view) -> bool:
    shell = view.shell
    return bool(shell._background_task_active() or getattr(shell, "utility_worker", None) is not None)


def _value(control, kind):
    if kind in ("combo",):
        data = control.currentData()
        return data if data is not None else control.currentText()
    if kind == "editable_combo":
        return control.currentText()
    if kind == "spin":
        return control.value()
    if kind == "check":
        return control.isChecked()
    if kind == "plain":
        return control.toPlainText()
    return control.text()


def _values(view, fields) -> dict[str, object]:
    return {name: _value(getattr(view, attribute), kind) for name, (attribute, kind) in fields.items()}


def _profile(profile) -> dict[str, object]:
    return {"id": profile.profile_id, "name": profile.label, "action": profile.action_mode,
            "format": profile.format_value or "", "size": profile.size_value or "", "mips": profile.mip_value or "",
            "ncnn_model": profile.ncnn_model_name, "ncnn_scale": profile.ncnn_scale,
            "tile_size": profile.ncnn_tile_size, "extra_args": profile.ncnn_extra_args,
            "post_correction": profile.post_correction_mode}


def _rule(index, rule) -> dict[str, object]:
    return {"index": index, "enabled": rule.enabled, "match_mode": rule.match_mode or "glob", "pattern": rule.pattern,
            "profile": rule.workflow_profile_id, "semantic": rule.semantic_value or "",
            "planner_profile": rule.profile_value or "", "colorspace": rule.colorspace_value or "",
            "alpha": rule.alpha_policy_value or "", "intermediate": rule.intermediate_value or ""}


def _matches(view, offset, count) -> dict[str, object]:
    tree = view.workflow_matched_files_tree
    rows = []
    for index in range(offset, min(tree.topLevelItemCount(), offset + count)):
        item = tree.topLevelItem(index)
        rows.append({"path": item.text(0), "type": item.text(1), "rule": item.text(2), "profile": item.text(3),
                     "dds": item.text(4), "ncnn": item.text(5), "action": item.text(6),
                     "selected": item.isSelected()})
    return {"summary": view.workflow_matched_summary_label.text(), "total": tree.topLevelItemCount(), "rows": rows}


def _progress(view) -> dict[str, object]:
    status = view.error_message_value
    return {"phase": view.phase_value.text(), "phase_progress": view.phase_progress_value.text(),
            "total_files": view.total_files_value.text(), "current_file": view.current_file_value.text(),
            "converted": view.converted_value.text(), "skipped": view.skipped_value.text(),
            "failed": view.failed_value.text(), "status": status.text(), "status_is_error": bool(status.property("error"))}


def _state(view, args=None) -> dict[str, object]:
    args = args or {}
    return {"mode": view.job.mode, "busy": _busy(view), "settings": _values(view, FIELDS),
            "overwrite_existing": view.overwrite_existing_checkbox.isChecked(),
            "mod_package_outputs": {key: box.isChecked() for key, box in view.mod_ready_profile_checkboxes.items()},
            "profiles": [_profile(profile) for profile in view.workflow_profiles_state],
            "rules": [_rule(index, rule) for index, rule in enumerate(view.texture_rules_state)],
            "matches": _matches(view, args.get("offset", 0), args.get("count", 200)),
            "progress": _progress(view), "log": view.log_view.toPlainText().splitlines()[-LOG_LINES:]}


def _read(call):
    def read():
        state = _state(_workspace(call), call.arguments)
        from cdmw.mcp.texture_files import rail_assets

        state["assets"] = rail_assets(call.context)
        return state
    return ui(call, read)


def _set(view, fields, table, what, *, emit_editing=False) -> None:
    unknown = set(fields) - set(table)
    if unknown:
        raise ToolError(INVALID_ARGUMENTS, f"Unknown {what} field {sorted(unknown)[0]!r}; known: {sorted(table)}.")
    for name, value in fields.items():
        attribute, kind = table[name]
        control = getattr(view, attribute)
        if kind == "combo":
            choose(control, "" if value is None else str(value) if isinstance(value, int) else value)
        elif kind == "editable_combo":
            control.setCurrentText(str(value))
            control.lineEdit().editingFinished.emit()
        elif kind == "spin":
            if not isinstance(value, int) or isinstance(value, bool) or not (
                    control.minimum() <= value <= control.maximum()):
                raise ToolError(INVALID_ARGUMENTS, f"{name} is a whole number from {control.minimum()} to "
                                                   f"{control.maximum()}.")
            control.setValue(value)
        elif kind == "check":
            if not isinstance(value, bool):
                raise ToolError(INVALID_ARGUMENTS, f"{name} is true or false.")
            control.setChecked(value)
        elif kind == "plain":
            control.setPlainText(str(value))
        else:
            control.setText(str(value))
            if emit_editing:
                control.editingFinished.emit()


def _checked_paths(call, fields) -> dict[str, object]:
    """Folders are checked before the page sees them: a run writes into the output ones."""

    checked = dict(fields)
    for name, value in fields.items():
        kind = FIELDS.get(name, ("", ""))[1]
        if kind == "folder":
            path = Path(str(value)).expanduser()
            if not path.is_dir():
                raise ToolError(INVALID_ARGUMENTS, f"{name} is an existing folder; there is none at {path}.")
            checked[name] = str(path)
        elif kind == "output":
            checked[name] = "" if value in ("", None) else str(output(call, str(value), folder=True))
    return checked


def _select(tree, key) -> None:
    from PySide6.QtCore import Qt

    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.data(0, Qt.ItemDataRole.UserRole) == key:
            tree.setCurrentItem(item)
            return
    raise ToolError(NOT_FOUND, "No row matches that profile or rule.")


def _profile_action(view, args) -> None:
    op = required(args, "op")
    if op == "add":
        press(view.workflow_profile_add_button)
    else:
        profile_id = required(args, "profile")
        index = next((i for i, row in enumerate(view.workflow_profiles_state) if row.profile_id == profile_id), -1)
        if index < 0:
            raise ToolError(NOT_FOUND, f"There is no workflow profile {profile_id!r}.")
        _select(view.workflow_profiles_tree, index)
        if op == "duplicate":
            press(view.workflow_profile_duplicate_button)
        elif op == "delete":
            press(view.workflow_profile_delete_button)
    if op in ("add", "change") and args.get("fields"):
        _set(view, args["fields"], PROFILE_FIELDS, "profile", emit_editing=True)


def _rule_action(view, args) -> None:
    op = required(args, "op")
    if op == "add":
        press(view.workflow_rule_add_button)
    else:
        index = args.get("index")
        if not isinstance(index, int) or not 0 <= index < len(view.texture_rules_state):
            raise ToolError(NOT_FOUND, f"There is no rule at index {index!r}.")
        _select(view.workflow_rules_tree, index)
        button = {"duplicate": "workflow_rule_duplicate_button", "delete": "workflow_rule_delete_button",
                  "move_up": "workflow_rule_move_up_button", "move_down": "workflow_rule_move_down_button"}.get(op)
        if button:
            press(getattr(view, button))
    if op in ("add", "change") and args.get("fields"):
        fields = dict(args["fields"])
        _set(view, fields, RULE_FIELDS, "rule", emit_editing=True)


def _assign(view, args) -> None:
    from PySide6.QtCore import Qt

    paths = set(required(args, "paths"))
    profile_id = required(args, "profile")
    profile = next((row for row in view.workflow_profiles_state if row.profile_id == profile_id), None)
    if profile is None:
        raise ToolError(NOT_FOUND, f"There is no workflow profile {profile_id!r}.")
    tree = view.workflow_matched_files_tree
    tree.clearSelection()
    found = set()
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key in paths:
            item.setSelected(True)
            found.add(key)
    missing = sorted(paths - found)
    if missing:
        raise ToolError(NOT_FOUND, f"{missing[0]!r} is not among the matched files; refresh_matches first.")
    press(view.workflow_assign_profile_button)


def _flush(view) -> None:
    """The matched files refresh on a timer; run it now so the state is current."""

    timer = getattr(view, "_workflow_match_refresh_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        view._refresh_workflow_matched_files_view()


def _visible(predicate):
    from PySide6.QtWidgets import QApplication

    return next((widget for widget in QApplication.topLevelWidgets()
                 if widget.isVisible() and predicate(widget)), None)


def _wait(call, view_check, *, deadline_s, what):
    deadline = time.monotonic() + deadline_s
    while True:
        result = call.context.ui_call(view_check)
        if result is not None:
            return result
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, f"{what} did not finish in time.")
        time.sleep(0.05)


def _policy_preview(call, args) -> dict[str, object]:
    from cdmw.ui.policy_preview_dialog import TexturePolicyPreviewDialog
    from PySide6.QtCore import Qt

    def start():
        view = _workspace(call)
        if _busy(view):
            raise ToolError(UNAVAILABLE, "Textures is busy; read textures_upscale_state until it is not.")
        press(view.preview_policy_button)
        return {}

    ui(call, start)
    offset, count = args.get("offset", 0), args.get("count", 200)

    def check():
        dialog = _visible(lambda widget: isinstance(widget, TexturePolicyPreviewDialog))
        view = _workspace(call)
        if dialog is not None:
            tree = dialog.tree
            rows = [dict(tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or {})
                    for i in range(offset, min(tree.topLevelItemCount(), offset + count))]
            found = {"summary": dialog.summary_label.text().splitlines(), "warning": dialog.warning_label.text(),
                     "total": tree.topLevelItemCount(), "rows": rows}
            dialog.reject()  # the preview is read-only; closing it changes nothing
            return found
        if not _busy(view):
            progress = _progress(view)
            raise ToolError(UNAVAILABLE, progress["status"] or "Preview Policy did not open.", {"progress": progress})
        return None

    return _wait(call, check, deadline_s=DIALOG_WAIT_S, what="Preview Policy")


def _run_summary(call) -> dict[str, object]:
    from PySide6.QtWidgets import QDialog, QLabel
    from cdmw.ui.safe_upscale_wizard import SafeUpscaleWizard

    found: dict[str, object] = {}

    def read(dialog):
        found["configuration"] = dataclasses.asdict(dialog.current_configuration())
        found["summary"] = [label.text() for label in dialog.findChildren(QLabel) if label.text().strip()]
        return int(QDialog.DialogCode.Rejected)

    def show():
        press(_workspace(call).safe_upscale_wizard_button)
        return {}

    ui(call, show, dialogs={SafeUpscaleWizard: read})
    if not found:
        raise ToolError(UNAVAILABLE, "Run Summary did not open.")
    return found


def _wait_idle(call, *, what, deadline_s=60):
    def idle():
        return True if not _busy(_workspace(call)) else None

    _wait(call, idle, deadline_s=deadline_s, what=what)


def _change(call):
    args = call.arguments
    action = args["action"]
    if action == "preview_policy":
        return _policy_preview(call, args)
    if action == "run_summary":
        return _run_summary(call)
    fields = _checked_paths(call, args["fields"]) if action == "settings" and "fields" in args else None
    answers = {}

    def change():
        view = _workspace(call)
        if _busy(view) and action != "stop":
            raise ToolError(UNAVAILABLE, "Textures is busy; read textures_upscale_state until it is not.")
        if action == "show":
            press(view.mode_buttons["upscale"])
        elif action == "settings":
            if not fields:
                raise ToolError(INVALID_ARGUMENTS, "settings takes fields.")
            _set(view, fields, FIELDS, "setting")
        elif action == "profile":
            _profile_action(view, args)
        elif action == "rule":
            _rule_action(view, args)
        elif action == "refresh_matches":
            press(view.workflow_matched_refresh_button)
        elif action == "assign_profile":
            _assign(view, args)
        elif action == "scan":
            press(view.scan_button)
        else:  # stop
            press(view.stop_button)
        return {}

    if action == "assign_profile":
        # The page asks which profile in a pick-one prompt; it is answered with the profile's name.
        def pick():
            view = _workspace(call)
            profile = next((row for row in view.workflow_profiles_state
                            if row.profile_id == args.get("profile")), None)
            return profile.label if profile is not None else ""
        answers["item"] = call.context.ui_call(pick)
    outcome = ui(call, change, answers)
    if action == "scan":
        _wait_idle(call, what="Scan", deadline_s=10 * 60)

    def read():
        view = _workspace(call)
        _flush(view)
        return _state(view, args)

    return {**outcome, **ui(call, read)}


def _summary(view, serial):
    """The run's RunSummary, when the job kept it (it does unless the textures changed meanwhile)."""

    results = [row.value for row in view.job.results if row.kind == "upscale"]
    if view.job._serial <= serial or not results:
        return None
    summary = results[-1]
    return {key: getattr(summary, key) for key in ("total_files", "converted", "skipped", "failed")
            if hasattr(summary, key)}


def _start(call):
    args = call.arguments
    folder = output(call, args["output_root"], folder=True)
    unclassified = args.get("unclassified", "cancel")

    def start():
        view = _workspace(call)
        if _busy(view):
            raise ToolError(UNAVAILABLE, "Textures is busy; read textures_upscale_state until it is not.")
        view.output_root_edit.setText(str(folder))
        # Start never replaces DDS files that are already in the output folder.
        view.overwrite_existing_checkbox.setChecked(False)
        serial = view.job._serial
        press(view.start_button)
        return {"serial": serial}

    outcome = ui(call, start)
    serial = outcome.pop("serial")
    idle_since = [0.0]

    def started():
        from PySide6.QtWidgets import QMessageBox

        view = _workspace(call)
        box = _visible(lambda widget: isinstance(widget, QMessageBox) and widget.windowTitle() == UNCLASSIFIED_TITLE)
        if box is not None:
            # Which files lack a saved classification is the user's review; continue only when asked.
            wanted = "Continue Anyway" if unclassified == "continue" else "Cancel"
            button = next((b for b in box.buttons() if b.text().replace("&", "") == wanted), None)
            outcome["unclassified"] = {"text": box.text(), "details": box.informativeText(), "answer": unclassified}
            (button or box.buttons()[-1]).click()
            idle_since[0] = 0.0
            return None
        if view.job._serial > serial:
            return "started"
        if _busy(view):
            idle_since[0] = 0.0
            return None
        # Between the pre-run check and the build the page is briefly idle: wait until it stays so.
        now = time.monotonic()
        idle_since[0] = idle_since[0] or now
        return "idle" if now - idle_since[0] > 1.5 else None

    first = _wait(call, started, deadline_s=DIALOG_WAIT_S, what="Start")
    deadline = time.monotonic() + WAIT_S
    while first == "started" and call.context.ui_call(lambda: _busy(_workspace(call))):
        if call.cancelled():
            call.context.ui_call(lambda: press(_workspace(call).stop_button))
            call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Start did not finish in time.")
        time.sleep(0.2)
    state = ui(call, lambda: {**_state(_workspace(call)), "summary": _summary(_workspace(call), serial)})
    details = {"progress": state["progress"], "log": state["log"],
               **({"unclassified": outcome["unclassified"]} if "unclassified" in outcome else {})}
    if first != "started":
        raise ToolError(UNAVAILABLE, state["progress"]["status"] or "Start did not run.", details)
    if state["progress"]["status_is_error"]:
        raise ToolError(FAILED, state["progress"]["status"], details)
    return {**outcome, **details, "output_root": str(folder), "summary": state["summary"]}


SETTING_NAMES = ", ".join(FIELDS)


def texture_upscale_tools():
    fields = {"type": "object"}
    return [
        tool("textures.upscale_state", READ, "Read Textures > Upscale: the run settings (names as "
             "textures_upscale takes them), the mod package outputs, the workflow profiles and rules, the matched "
             "files with their planned action, the progress and the log.",
             "ui:TexturesWorkspace.upscale_controls", _read,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("textures.upscale", EDIT, "Work Textures > Upscale: show (switch to Upscale), settings (fields), "
             "profile (op add, duplicate, delete or change; profile id; fields), rule (op add, duplicate, delete, "
             "move_up, move_down or change; index; fields), refresh_matches, assign_profile (paths of matched "
             "files, profile id: adds exact-path rules), scan, preview_policy (the per-file plan, read-only), "
             "run_summary (read-only) or stop. Settings: " + SETTING_NAMES + ". Profile fields: "
             + ", ".join(PROFILE_FIELDS) + ". Rule fields: " + ", ".join(RULE_FIELDS) + ". Choices take the "
             "control's value or its label. Output folders must exist and be outside the game.",
             "ui:TexturesWorkspace.upscale_controls", _change,
             {"action": choices("show", "settings", "profile", "rule", "refresh_matches", "assign_profile", "scan",
                                "preview_policy", "run_summary", "stop"),
              "op": choices("add", "duplicate", "delete", "change", "move_up", "move_down"),
              "profile": {"type": "string", "maxLength": 200}, "index": ROW, "fields": fields,
              "paths": {"type": "array", "items": {"type": "string", "maxLength": 1024}, "minItems": 1,
                        "maxItems": 1000},
              "offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}, ("action",),
             runs_on=ON_WORKER),
        tool("textures.upscale_start", OUTPUT, "Press Start: process the matched DDS files with the current "
             "settings into output_root, an existing folder outside the game. Existing DDS files there are never "
             "replaced. If files still lack a saved classification the page asks; unclassified is the answer "
             "(cancel unless continue). Waits for the run; cancelling the job presses Stop.",
             "ui:TexturesWorkspace.start_button", _start,
             {"output_root": PATH, "unclassified": choices("cancel", "continue")},
             ("output_root",), output_folders=("output_root",), runs_on=ON_WORKER),
    ]


__all__ = ["texture_upscale_tools"]
