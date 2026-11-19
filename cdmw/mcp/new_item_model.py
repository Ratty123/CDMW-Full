"""Typed access to the model step and its transparency canvas."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTableWidget
from shiboken6 import isValid

from cdmw.mcp.errors import INVALID_ARGUMENTS, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.new_item_workflow import (
    BOOL, INT, NUMBER, PATH, TEXT, VEC3, act, action_schema, answer_later, array, available, choice,
    combo_choices, idle, json_value, read_when, required, set_control, widget_reason, workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool, object_schema

_POINT = {"type": "array", "items": NUMBER, "minItems": 2, "maxItems": 2}
_INDEX = {"type": "integer", "minimum": 0}
_SKIN = object_schema({
    "part": _INDEX, "policy": choice("preserve", "reduce", "fold", "transfer", "body_transfer"),
    "capacity": {"type": "integer", "enum": [4, 6]}, "donor": _INDEX,
}, ["part", "policy"])
_SLOT = object_schema({"material_key": INT, "amount": INT}, ["material_key", "amount"])
_ACTIONS = (
    "state", "import", "library", "component", "placement", "apply_placement", "fit", "discard_import",
    "source", "icon", "skinning", "sockets", "body_visibility", "find_layers", "load_dyes",
    "dye", "remove_dye", "transparency", "paint",
)


def _click(button):
    available(button)
    button.click()


def _list_items(widget):
    return [widget.item(row) for row in range(widget.count())]


def _checks(widget, wanted):
    available(widget)
    items = {item.data(Qt.ItemDataRole.UserRole): item for item in _list_items(widget)}
    missing = set(wanted) - items.keys()
    if missing:
        raise ValueError(f"These parts or layers are unavailable: {sorted(missing)}.")
    for name, item in items.items():
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(Qt.CheckState.Checked if name in wanted else Qt.CheckState.Unchecked)


def _state(page):
    panel, controller = page.model_panel, page.controller
    source = controller.model_import
    layers = panel.body_visibility_editor.layers
    return {
        "busy": controller.busy, "operation": controller._lane, "source": controller.draft.model_source.value,
        "model": None if source is None else {"label": source.label, "path": str(source.chosen_path),
            "parts": [part.name for part in source.raw_import_mesh.submeshes] if source.raw_import_mesh else [],
            "skinning": json_value(source.skinning_choices)},
        "components": [{"id": list(row.identity), "selected": row.selected, "included": row.included}
                       for row in panel.components.rows()],
        "placement": json_value(controller.model_placement), "can_apply": panel.apply_button.isEnabled(),
        "applied": controller.model_result is not None, "status": panel.apply_status.plain_text(),
        "body_visibility": json_value(controller.draft.body_visibility),
        "layers": [item.data(Qt.ItemDataRole.UserRole) for item in _list_items(layers)],
        "socket_slots": json_value(controller.draft.socket_slots),
        "dyes": json_value(panel.dyes._values()), "dye_parts": combo_choices(panel.dyes.source),
        "translucency_parts": [item.data(Qt.ItemDataRole.UserRole) for item in _list_items(panel.translucency_editor.parts)],
        "shader_parts": combo_choices(panel.shader_controls_editor.part),
    }


def _placement(panel, arguments):
    groups = {"offset": panel.offset_spins, "rotation": panel.rotation_spins, "scale": panel.scale_spins}
    if "uniform_scale" in arguments:
        set_control(panel.uniform_scale, arguments["uniform_scale"])
    if panel.uniform_scale.isChecked() and "scale" in arguments:
        raise ValueError(panel.uniform_scale.toolTip() + " Set uniform_scale to false to enter all three axes.")
    for name, spins in groups.items():
        if name in arguments:
            for spin, value in zip(spins, arguments[name]):
                set_control(spin, value)


def _skinning(panel, choices):
    _click(panel.skinning_button)
    dialog = panel._skinning_dialog
    try:
        table = dialog.findChild(QTableWidget)
        for item in choices:
            part = item["part"]
            if part >= table.rowCount():
                raise ValueError("There is no such imported part in Skin weights.")
            set_control(table.cellWidget(part, 1), (item["policy"], item.get("capacity", 6)))
            if "donor" in item:
                set_control(table.cellWidget(part, 2), (item["donor"],))
        buttons = dialog.findChild(QDialogButtonBox)
        _click(buttons.button(QDialogButtonBox.StandardButton.Apply))
        if dialog.result() != QDialog.DialogCode.Accepted:
            raise ValueError(panel.import_problem_note.plain_text() or panel.skinning_button.toolTip())
    finally:
        if isValid(dialog) and dialog.result() != QDialog.DialogCode.Accepted:
            dialog.reject()


def _sockets(page, arguments):
    editor = page.perks_panel.socket_editor
    set_control(editor.customize, arguments.get("customize", True))
    slots = arguments.get("slots")
    if slots is None or not editor.customize.isChecked():
        return
    if len(slots) > 5:
        set_control(editor.experimental, True)
    set_control(editor.count, len(slots))
    for row, slot in enumerate(slots):
        for column, name in ((1, "material_key"), (2, "amount")):
            set_control(editor.costs.cellWidget(row, column), str(slot[name]))


def _body(panel, arguments):
    editor = panel.body_visibility_editor
    if not editor.keep_skin.isEnabled():
        raise ValueError(editor.scope.text() or widget_reason(editor.keep_skin))
    for name in ("keep_skin", "keep_hair"):
        if name in arguments:
            set_control(getattr(editor, name), arguments[name])
    if "keep_layers" in arguments:
        _checks(editor.layers, arguments["keep_layers"])
    if arguments.get("all_worn"):
        _click(editor.apply_to_worn)


def _dye(editor, arguments, *, remove):
    if remove:
        required(arguments, "row")
        row = arguments["row"]
        if row >= editor.mappings.count():
            raise ValueError(editor.state.text())
        editor.mappings.setCurrentRow(row)
        _click(editor.remove)
        return
    operation = arguments.get("dye_mode", "map")
    if operation != "map":
        _click(editor.inherit if operation == "inherit" else editor.clear)
        return
    required(arguments, "source_part", "target_part")
    set_control(editor, True)
    set_control(editor.source, arguments["source_part"])
    editor.target.setCurrentText(arguments["target_part"])
    for spin, value in zip(editor.slots, arguments.get("channels", ())):
        set_control(spin, value)
    set_control(editor.mask, arguments.get("mask", ""))
    _click(editor.add)
    if not any(value.target_submesh == arguments["target_part"] for value in editor._values() or ()):
        raise ValueError(editor.state.text())


def _transparency_editor(panel, arguments, *, setting=False):
    required(arguments, "part", "paint_mode")
    part, mode = arguments["part"], arguments["paint_mode"]
    if mode == "translucency":
        editor = panel.translucency_editor
        item = next((item for item in _list_items(editor.parts)
                     if item.data(Qt.ItemDataRole.UserRole) == part), None)
        if item is None:
            raise ValueError("This part is unavailable in the Translucency editor.")
        if setting:
            item.setCheckState(Qt.CheckState.Checked if arguments.get("enabled", True) else Qt.CheckState.Unchecked)
        editor.parts.setCurrentItem(item)
    else:
        editor = panel.shader_controls_editor
        set_control(editor.part, part)
        if setting:
            set_control(editor.family, ("SkinnedMeshWing" if mode == "cutout" else "SkinnedMeshEyeCover")
                        if arguments.get("enabled", True) else "")
    return editor, part, mode


def _paint(call):
    a = call.arguments
    required(a, "points")
    owner = {}

    def prepare():
        page = workflow(call.context)
        idle(page)
        panel = page.model_panel
        editor, part, mode = _transparency_editor(panel, a)
        available(editor.paint_mask)
        current = getattr(panel, "_transparency_painter", None)
        if current is not None and isValid(current):
            raise ValueError("Close the current transparency painter first.")
        owner.update(panel=panel, controller=page.controller)
        def record(message, error):
            if error:
                owner["problem"] = str(message)
        page.controller.status_message.connect(record)
        owner["record"] = record
        if not panel._paint_transparency(part, "blending" if mode == "cutout" else mode, present=False):
            raise ToolError(UNAVAILABLE, owner.get("problem") or widget_reason(editor.paint_mask))
        return {}

    def paint_ready():
        panel = owner["panel"]
        return True if not owner["controller"].busy and isValid(panel) else None

    def stroke():
        panel = owner["panel"]
        dialog = getattr(panel, "_transparency_painter", None)
        if dialog is None or not isValid(dialog):
            raise ToolError(UNAVAILABLE, owner.get("problem") or "The transparency painter could not be prepared.")
        width, height = dialog.document.width, dialog.document.height
        points = [tuple(point) for point in a["points"]]
        if not all(0 <= x < width and 0 <= y < height for x, y in points):
            raise ToolError(INVALID_ARGUMENTS, f"Paint points must be within the {width} by {height} mask.")
        targets = {"colour": 0, "surface": 1, "linked": 2}
        target = targets[a.get("target", "colour")]
        if target and not dialog._dual:
            raise ToolError(UNAVAILABLE, "This paint mode has one mask target.")
        dialog.target.setCurrentIndex(target)
        for name in ("value", "brush_size", "hardness", "opacity"):
            if name in a:
                set_control(getattr(dialog, name), a[name])
        owner.update(dialog=dialog, width=width, height=height, painted=False)

        def completed():
            owner["painted"] = True

        dialog.stroke_points(points, completed)
        return {}

    def finish():
        dialog = owner["dialog"]
        if not owner["painted"]:
            raise ToolError(UNAVAILABLE, dialog.message.text())
        _click(dialog.buttons.button(QDialogButtonBox.StandardButton.Apply))
        if dialog.result() != QDialog.DialogCode.Accepted:
            raise ToolError(UNAVAILABLE, dialog.message.text())
        return {"applied": True, "width": owner["width"], "height": owner["height"]}

    def cleanup():
        panel = owner["panel"]
        controller = owner["controller"]
        if isValid(controller):
            controller.status_message.disconnect(owner["record"])
        if not isValid(panel):
            return
        dialog = getattr(panel, "_transparency_painter", None)
        if dialog is not None and isValid(dialog) and dialog.result() != QDialog.DialogCode.Accepted:
            dialog.reject()
        elif dialog is None and isValid(controller) and controller._lane == "transparency_mask":
            controller.cancel_operation("transparency_mask")

    try:
        result = act(call, prepare)
        if result:
            return result
        if read_when(call, paint_ready) is None:
            raise ToolError(UNAVAILABLE, "The transparency painter is still preparing.")
        result = act(call, stroke)
        if result:
            return result
        if read_when(call, lambda: True if not owner["dialog"]._io_active else None) is None:
            raise ToolError(UNAVAILABLE, "The transparency stroke is still preparing.")
        return act(call, finish)
    finally:
        if owner:
            call.context.ui_call(cleanup)


def _library(call):
    from cdmw.domain.output_paths import game_path_reason
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    a = call.arguments
    asked, captured = [], {}
    choose_member = answer_later(call, asked)

    def send():
        page = workflow(call.context)
        idle(page)
        shell = call.context.window.shell
        library = created_tool_widget(getattr(shell, "model_library_tab", None))
        if library is None:
            raise ToolError(UNAVAILABLE, "Open Model Library and find a model first.")
        if "row" in a:
            item = library.results_tree.topLevelItem(a["row"])
            if item is None:
                raise ToolError(INVALID_ARGUMENTS, "There is no such row in Model Library.")
            library.results_tree.setCurrentItem(item)
        payload = library._selected_payload()
        if not payload:
            raise ToolError(UNAVAILABLE, "Select a model first.")
        paths = [payload[key] for key in ("path", "asset_dir", "archive_path") if payload.get(key)]
        if payload.get("kind") == "mirror":
            paths.append(library._download_output_root())
        for path in paths:
            reason = game_path_reason(path, game_folder=call.context.game_folder())
            if reason:
                raise ToolError(REFUSED, reason)
        captured.update(library=library, page=page, resolved="")

        def resolved(path, _payload):
            captured["resolved"] = path

        library.use_in_new_item_studio_requested.connect(resolved)
        captured["slot"] = resolved
        library.use_selected_model_in_new_item_studio(choose_member=choose_member)
        return {}

    def read():
        library, page = captured["library"], captured["page"]
        if captured["resolved"] or (library._task_thread is None and library._pending_model_action_after_task is None):
            return {**_state(page), "resolved": captured["resolved"], "library_status": library.status_label.text()}
        return None

    try:
        result = act(call, send)
        if not result:
            result = read_when(call, read) or {"busy": True}
        if asked:
            result["asked"] = asked
        return result
    finally:
        if "slot" in captured:
            def disconnect():
                if isValid(captured["library"]):
                    captured["library"].use_in_new_item_studio_requested.disconnect(captured["slot"])
            call.context.ui_call(disconnect)


def _model(call):
    a, context = call.arguments, call.context
    action = a["action"]
    if action == "paint":
        return _paint(call)
    if action == "library":
        return _library(call)
    if action == "state":
        return context.ui_call(lambda: _state(workflow(context)))
    answers = {}
    if action == "import":
        required(a, "path")
        answers["file"] = a["path"]

    def change():
        page = workflow(context)
        idle(page)
        panel = page.model_panel
        if action == "import":
            if "policy" in a:
                set_control(panel.import_skin_policy, a["policy"])
            _click(panel.import_button)
        elif action == "component":
            required(a, "component")
            item = panel.components.item_for(tuple(a["component"]))
            if item is None:
                raise ValueError("There is no such model component.")
            panel.components.tree.setCurrentItem(item)
            panel.components._apply_selection()
            if "included" in a:
                panel.components.set_included(tuple(a["component"]), a["included"])
        elif action == "placement":
            _placement(panel, a)
        elif action in ("apply_placement", "fit", "discard_import"):
            _click({"apply_placement": panel.apply_button, "fit": panel.fit_button,
                    "discard_import": panel.clear_button}[action])
        elif action == "source":
            required(a, "source")
            _click(panel.use_template_button if a["source"] == "template" else panel.use_import_button)
            for name, control in (("plain_pbr", panel.plain_pbr), ("own_sheath", panel.own_sheath),
                                  ("keep_physics", panel.keep_physics)):
                if name in a:
                    set_control(control, a[name])
        elif action == "icon":
            set_control(panel.generate_icon if a.get("path") else panel.keep_icon, True)
            if a.get("path"):
                set_control(panel.icon_source, a["path"])
        elif action == "skinning":
            required(a, "skinning")
            _skinning(panel, a["skinning"])
        elif action == "sockets":
            _sockets(page, a)
        elif action == "body_visibility":
            _body(panel, a)
        elif action == "find_layers":
            _click(panel.body_visibility_editor.find_layers)
        elif action == "load_dyes":
            _click(panel.dyes.load)
        elif action in ("dye", "remove_dye"):
            _dye(panel.dyes, a, remove=action == "remove_dye")
        elif action == "transparency":
            _transparency_editor(panel, a, setting=True)
        return _state(page)

    def checked():
        try:
            return change()
        except ValueError as exc:
            raise ToolError(UNAVAILABLE, str(exc)) from None

    return act(call, checked, answers=answers)


def model_tool():
    return Tool(
        name="new_item.model", family="new_item", title="Edit the New Item model",
        description="Import a path or send a Model Library row, choose components and skin weights, enter "
                    "placement, and edit sockets, body visibility, dyes, icons and transparency. Paint uses "
                    "mask pixel coordinates and applies the stroke. State reports the active model operation.",
        input_schema=action_schema(_ACTIONS, {
            "path": PATH, "row": _INDEX, "policy": choice("preserve", "transfer", "reduce", "fold"),
            "component": {"type": "array", "items": TEXT, "minItems": 2, "maxItems": 2}, "included": BOOL,
            "offset": VEC3, "rotation": VEC3, "scale": VEC3, "uniform_scale": BOOL,
            "source": choice("template", "imported"), "plain_pbr": BOOL, "own_sheath": BOOL, "keep_physics": BOOL,
            "skinning": array(_SKIN), "customize": BOOL, "slots": array(_SLOT, limit=8),
            "keep_skin": BOOL, "keep_hair": BOOL, "keep_layers": array(TEXT), "all_worn": BOOL,
            "dye_mode": choice("map", "inherit", "clear"), "source_part": TEXT, "target_part": TEXT, "mask": PATH,
            "channels": {"type": "array", "items": INT, "minItems": 3, "maxItems": 3},
            "part": TEXT, "paint_mode": choice("translucency", "blending", "cutout"), "enabled": BOOL,
            "target": choice("colour", "surface", "linked"),
            "points": {"type": "array", "items": _POINT, "minItems": 1, "maxItems": 512},
            "value": INT, "brush_size": INT, "hardness": INT, "opacity": INT,
        }, default="state"),
        effect=EDIT, effect_of=lambda call: READ if call.arguments["action"] == "state" else EDIT,
        route="ui:ModelPanel,SocketEditor,TransparencyPaintDialog", handler=_model, runs_on=ON_CALL,
    )
