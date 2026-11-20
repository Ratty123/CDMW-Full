"""Textures > Recolor as typed tools (MCP gap plan item 11, the Recolor mode).

``textures.recolor_state`` reads the analysed mod's targets, the template, the output
settings and the log. ``textures.recolor`` works the page's own controls: analyse a mod,
choose, edit, save, import or review a template, pick targets and preview one.
``textures.recolor_build`` presses Build Variants into a folder the user allows. The
page's own checks and messages apply throughout; its messages come back as ``messages``.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, choices, choose, page, press, required, tool, ui
from cdmw.mcp.tools import ON_WORKER

PAGE = "recolor_variants"
WAIT_S = 30 * 60
LOG_LINES = 40
#: Template fields an AI app may set, with the control that holds each.
FIELDS = {
    "name": ("template_name_edit", "text"), "target_kind": ("target_kind_combo", "combo"),
    "slot_kind": ("slot_kind_combo", "combo"), "texture_glob": ("filename_glob_edit", "text"),
    "material_parameter": ("parameter_glob_edit", "text"), "operation": ("operation_combo", "combo"),
    "source_color": ("source_color_edit", "color"), "target_color": ("target_color_edit", "color"),
    "tolerance": ("tolerance_slider", "slider"), "strength": ("strength_slider", "slider"),
    "preserve_luma": ("preserve_luma_checkbox", "check"),
}


def _busy(tab) -> bool:
    return tab.worker_thread is not None


def _target(target) -> dict[str, object]:
    return {"id": target.target_id, "kind": target.target_kind, "game_path": target.game_path,
            "label": target.label, "slot": target.slot_kind or target.parameter_name, "editable": target.editable,
            "locked": target.locked_reason, "value": target.current_value, "format": target.dds_format}


def _chosen_ids(tab) -> list[str]:
    """The targets a build would use: the ticked assets in Textures, or the page's own list."""

    workspace = tab.workspace
    if workspace is not None:
        job = workspace.job
        return [asset.package_target.target_id for key, asset in job.assets.items()
                if key in job.selected and asset.package_target is not None]
    return [target.target_id for target in (tab.analysis.editable_targets if tab.analysis else ())]


def _template(tab) -> dict[str, object]:
    values: dict[str, object] = {"id": tab.template_combo.currentData()}
    for name, (attribute, kind) in FIELDS.items():
        control = getattr(tab, attribute)
        values[name] = (control.currentData() if kind == "combo" else control.value() if kind == "slider"
                        else control.isChecked() if kind == "check" else control.text())
    return values


def _state(tab, args=None) -> dict[str, object]:
    args = args or {}
    analysis = tab.analysis
    targets = list(analysis.targets) if analysis is not None else []
    start = args.get("offset", 0)
    end = start + args.get("count", 200)
    log = tab.log_edit.toPlainText().splitlines()
    selected = tab._selected_target()
    return {"source": tab.source_path_edit.text(), "analyzed": analysis is not None,
            "package": str(analysis.package_path) if analysis is not None else "",
            "warnings": list(analysis.warnings) if analysis is not None else [],
            "total": len(targets), "targets": [_target(target) for target in targets[start:end]],
            "chosen": _chosen_ids(tab), "selected": selected.target_id if selected is not None else "",
            "templates": [{"id": template.template_id, "name": template.name} for template in tab.templates],
            "template": _template(tab), "output_folder": tab.output_root_edit.text(),
            "outputs": {key: box.isChecked() for key, box in tab.profile_checkboxes.items()},
            "busy": _busy(tab), "preview": tab.preview_summary_label.text(),
            "built": [str(path) for path in tab.last_output_roots], "log": log[-LOG_LINES:]}


def _read(call):
    return ui(call, lambda: _state(page(call, PAGE), call.arguments))


class _Messages:
    """The page's status messages while an action runs: it reports problems this way."""

    def __init__(self, tab):
        self.tab, self.seen = tab, []

    def __enter__(self):
        self.tab.status_message_requested.connect(self._note)
        return self

    def _note(self, message, error):
        self.seen.append({"text": str(message), "error": bool(error)})

    def __exit__(self, *_exc):
        self.tab.status_message_requested.disconnect(self._note)

    def refusal(self):
        errors = [row["text"] for row in self.seen if row["error"]]
        return errors[-1] if errors else ""


def _set_fields(tab, fields) -> None:
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ToolError(INVALID_ARGUMENTS, f"Unknown template field {sorted(unknown)[0]!r}.")
    for name, value in fields.items():
        attribute, kind = FIELDS[name]
        control = getattr(tab, attribute)
        if kind == "combo":
            choose(control, value)
        elif kind == "slider":
            if not isinstance(value, int) or not control.minimum() <= value <= control.maximum():
                raise ToolError(INVALID_ARGUMENTS, f"{name} is a whole number from {control.minimum()} to "
                                                   f"{control.maximum()}.")
            control.setValue(value)
        elif kind == "check":
            control.setChecked(bool(value))
        else:
            text = str(value)
            if kind == "color" and not (len(text) == 7 and text.startswith("#")
                                        and all(c in "0123456789abcdefABCDEF" for c in text[1:])):
                raise ToolError(INVALID_ARGUMENTS, f"{name} is a colour such as #C85A30.")
            control.setText(text)


def _pick_targets(tab, ids, active) -> None:
    from PySide6.QtCore import Qt

    analysis = tab.analysis
    if analysis is None:
        raise ToolError(UNAVAILABLE, "Analyze a Source Mod first.")
    known = {target.target_id: target for target in analysis.targets}
    for target_id in [*(ids or ()), *([active] if active else [])]:
        if target_id not in known:
            raise ToolError(NOT_FOUND, f"The analysis has no target {target_id!r}.")
    workspace = tab.workspace
    if workspace is None:
        if active:
            tree = tab.targets_tree
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == active:
                    tree.setCurrentItem(item)
        return
    rows = workspace.asset_list
    for index in range(rows.topLevelItemCount()):
        item = rows.topLevelItem(index)
        asset = workspace.job.assets.get(item.data(0, Qt.ItemDataRole.UserRole))
        target = getattr(asset, "package_target", None)
        if target is None or asset.package_path != Path(analysis.package_path):
            continue
        if ids is not None:
            # Ticking a row is the user's way of choosing what a build changes.
            item.setCheckState(0, Qt.CheckState.Checked if target.target_id in ids else Qt.CheckState.Unchecked)
        if active == target.target_id:
            rows.setCurrentItem(item)


def _change(call):
    args = call.arguments
    action = args["action"]
    answers = {}
    if action == "analyze":
        source = Path(str(required(args, "source")))
        if not source.exists():
            raise ToolError(INVALID_ARGUMENTS, f"There is no mod folder or ZIP at {source}.")
    elif action == "import_templates":
        source = Path(str(required(args, "file")))
        if not source.is_file() or source.suffix.lower() != ".json":
            raise ToolError(INVALID_ARGUMENTS, "import_templates takes an existing .json file.")
        answers = {"file": str(source)}

    def change():
        tab = page(call, PAGE)
        if _busy(tab) and action != "stop":
            raise ToolError(UNAVAILABLE, "Texture Recolor is busy; read textures_recolor_state until it is not.")
        with _Messages(tab) as messages:
            if action == "analyze":
                tab.source_path_edit.setText(str(Path(str(args["source"]))))
                press(tab.analyze_button)
            elif action == "template":
                choose(tab.template_combo, required(args, "template"))
            elif action == "edit_template":
                _set_fields(tab, required(args, "fields"))
            elif action == "save_template":
                if "fields" in args:
                    _set_fields(tab, args["fields"])
                press(tab.save_template_button)
            elif action == "import_templates":
                press(tab.import_template_button)
            elif action == "review":
                if "fields" in args:
                    _set_fields(tab, args["fields"])
                press(tab.preview_template_button)
            elif action == "targets":
                if "targets" not in args and "active" not in args:
                    raise ToolError(INVALID_ARGUMENTS, "targets takes targets (ids to build) or active (one id).")
                _pick_targets(tab, args.get("targets"), args.get("active"))
            elif action == "preview":
                if "active" in args:
                    _pick_targets(tab, None, args["active"])
                press(tab.refresh_selected_preview_button)
            elif action == "open_in_editor":
                if "active" in args:
                    _pick_targets(tab, None, args["active"])
                press(tab.open_selected_in_editor_button)
            else:  # stop
                press(tab.stop_button)
        refusal = messages.refusal()
        if refusal:
            raise ToolError(UNAVAILABLE, refusal, {"messages": messages.seen})
        return {**_state(tab), "messages": messages.seen}

    return ui(call, change, answers)


def _build(call):
    from cdmw.mcp.rail_actions import output

    folder = output(call, call.arguments["folder"], folder=True)
    outputs = call.arguments.get("outputs")

    def start():
        tab = page(call, PAGE)
        if _busy(tab):
            raise ToolError(UNAVAILABLE, "Texture Recolor is busy; read textures_recolor_state until it is not.")
        if outputs is not None:
            unknown = set(outputs) - set(tab.profile_checkboxes)
            if unknown:
                raise ToolError(INVALID_ARGUMENTS, f"Unknown manager output {sorted(unknown)[0]!r}; the page offers "
                                                   f"{sorted(tab.profile_checkboxes)}.")
            for key, box in tab.profile_checkboxes.items():
                box.setChecked(key in outputs)
        tab.output_root_edit.setText(str(folder))
        # Clearing earlier generated folders deletes files: the build never ticks it.
        tab.overwrite_checkbox.setChecked(False)
        if not tab.build_button.isEnabled():
            raise ToolError(UNAVAILABLE, tab.build_button.toolTip() or (
                "Analyze a Source Mod first." if tab.analysis is None else "Build Variants is unavailable: "
                + (tab.summary_label.text() or "check textures_recolor_state.")))
        with _Messages(tab) as messages:
            press(tab.build_button)
        if not _busy(tab):
            raise ToolError(UNAVAILABLE, messages.refusal() or "Build Variants did not start.",
                            {"messages": messages.seen})
        return {"started": True, "messages": messages.seen}

    outcome = ui(call, start)
    deadline = time.monotonic() + WAIT_S
    while call.context.ui_call(lambda: _busy(page(call, PAGE))):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Build Variants did not finish in time.", outcome)
        time.sleep(0.1)
    state = call.context.ui_call(lambda: _state(page(call, PAGE)))
    if not state["built"]:
        raise ToolError(FAILED, "Build Variants wrote nothing; the log says why.", {"log": state["log"]})
    return {**outcome, **state, "folder": str(folder)}


def texture_recolor_tools():
    return [
        tool("textures.recolor_state", READ, "Read Textures > Recolor: the analysed mod's targets (editable or "
             "locked, and which a build uses), the template and its fields, the outputs and the log.",
             "ui:RecolorVariantsTab", _read,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("textures.recolor", EDIT, "Work Textures > Recolor: analyze (source mod folder or ZIP), template (id), "
             "edit_template (fields), save_template, import_templates (file), review (the template's matches), "
             "targets (ids a build uses, and/or active), preview (active target), open_in_editor or stop. "
             "Fields: name, target_kind (texture_slot, material_color), slot_kind (base, emissive), texture_glob, "
             "material_parameter, operation (tint, replace_color, set_color), source_color, target_color, "
             "tolerance (0-255), strength (1-100), preserve_luma.",
             "ui:RecolorVariantsTab", _change,
             {"action": choices("analyze", "template", "edit_template", "save_template", "import_templates",
                                "review", "targets", "preview", "open_in_editor", "stop"),
              "source": PATH, "file": PATH, "template": {"type": "string", "maxLength": 200},
              "fields": {"type": "object"},
              "targets": {"type": "array", "items": {"type": "string", "maxLength": 1024}, "maxItems": 1000},
              "active": {"type": "string", "maxLength": 1024}}, ("action",)),
        tool("textures.recolor_build", OUTPUT, "Press Build Variants: write recoloured copies of the analysed mod "
             "into folder, an existing folder outside the game. The source mod is never changed, and earlier "
             "generated folders are never cleared. outputs picks the manager outputs (such as dmm).",
             "ui:RecolorVariantsTab.build_button", _build,
             {"folder": PATH, "outputs": {"type": "array", "items": {"type": "string", "maxLength": 40},
                                          "minItems": 1, "maxItems": 8}},
             ("folder",), output_folders=("folder",), runs_on=ON_WORKER),
    ]


__all__ = ["texture_recolor_tools"]
