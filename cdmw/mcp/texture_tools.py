"""Typed MCP controls for the docked and rail Texture Editor instances."""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, ON_WORKER, Tool, object_schema

NO_TEXTURE = ("No texture is open in the Texture Editor: open one from the Mesh Editor's Textures panel "
              "(textures_list, then textures_open).")
MAX_POINTS = 20000
_PERCENT = {"type": "integer", "minimum": 0, "maximum": 100}


def _panel(context):
    from cdmw.mcp.mesh_tools import shown_document

    tab = shown_document(context)
    panel = getattr(tab, "_texture_tools_panel", None)
    return tab, (panel() if callable(panel) else None)


EDITOR = {"type": "string", "enum": ["docked", "tool"], "default": "docked"}
PATH = {"type": "string", "minLength": 1, "maxLength": 1024}


def texture_schema(properties=None, required=()):
    return object_schema({"editor": EDITOR, **(properties or {})}, required)


def shell(context):
    return getattr(getattr(context, "window", None), "shell", None)


def rail_editor(context):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    container = getattr(shell(context), "texture_editor_tab", None)
    return created_tool_widget(container)


def target(context, location):
    if location == "tool":
        return rail_editor(context)
    return getattr(_panel(context)[1], "editor", None)


def _editor(call, *, needs_document=True):
    location = call.arguments.get("editor", "docked")
    editor = target(call.context, location)
    if editor is None or not hasattr(editor, "document") or (needs_document and editor.document is None):
        raise ToolError(UNAVAILABLE, "Open a texture in the rail's Textures tool first." if location == "tool"
                        else NO_TEXTURE)
    busy = getattr(editor, "_busy", None)
    if callable(busy) and busy():
        raise ToolError(UNAVAILABLE, "The Texture Editor is busy; try again in a moment.")
    return editor


def _one_state(context, location):
    tab, panel = _panel(context) if location == "docked" else (None, rail_editor(context))
    editor = getattr(panel, "editor", None) if location == "docked" else panel
    document = getattr(editor, "document", None)
    busy = getattr(editor, "_busy", None)
    if panel is None or editor is None or document is None:
        return {"open": False, "panel_shown": bool(panel is not None and panel.isVisible()),
                "busy": bool(busy and busy()), "history_index": -1}
    live = getattr(tab, "_live_texture_updates", None)
    keeper = getattr(tab, "_live_texture_keeping", None)
    settings = getattr(editor, "current_tool_settings", None)
    return {
        "open": True, "panel_shown": bool(panel.isVisible()), "floating": bool(location == "docked" and panel.isFloating()),
        "title": str(getattr(document, "title", "") or ""),
        "source": str(getattr(getattr(document, "source_binding", None), "source_path", "") or ""),
        "width": int(document.width), "height": int(document.height),
        "layers": [{"id": layer.layer_id, "name": getattr(layer, "name", ""),
                    "visible": bool(getattr(layer, "visible", True)),
                    "opacity": getattr(layer, "opacity", 100), "blend": getattr(layer, "blend_mode", "normal"),
                    "locked": getattr(layer, "locked", False), "alpha_locked": getattr(layer, "alpha_locked", False),
                    "mask": getattr(layer, "mask_layer_id", None), "mask_enabled": getattr(layer, "mask_enabled", False),
                    "active": layer.layer_id == document.active_layer_id} for layer in document.layers],
        "adjustments": [{"id": layer.layer_id, "type": layer.adjustment_type,
                         "enabled": bool(getattr(layer, "enabled", True))} for layer in document.adjustment_layers],
        "tool": str(getattr(settings, "tool", "") or ""),
        "tools": sorted(getattr(editor, "tool_buttons", {}) or {}),
        "status": editor.status_label.text() if hasattr(editor, "status_label") else "",
        "selection": getattr(getattr(document, "selection", None), "mode", "none"),
        "quick_mask": getattr(document, "quick_mask_enabled", False),
        "mask_target": getattr(editor, "_editing_mask_target", False),
        "colour": str(getattr(settings, "color_hex", "") or ""),
        "history_index": int(getattr(editor, "history_index", -1)),
        "busy": bool(busy()) if callable(busy) else False,
        # What the panel says about sharing and keeping the edit, as its status line does.
        "notice": str(getattr(panel, "notice_text", "") or ""),
        "sharing": str(getattr(panel, "sharing_text", "") or ""),
        "kept": str(getattr(panel, "kept_text", "") or ""),
        "edited_textures": sorted(live.edited_textures()) if live is not None else [],
        "not_kept_yet": int(keeper.unkept_count()) if keeper is not None else 0,
    }


def _state(call):
    states = {key: _one_state(call.context, key) for key in ("docked", "tool")}
    location = call.arguments.get("editor", "docked")
    return {**states[location], "editor": location, "editors": states}


def _act(call, function, answers=None) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    location = call.arguments.get("editor", "docked")

    def with_history():
        before = int(getattr(target(call.context, location), "history_index", -1))
        result = function() or {}
        after = int(getattr(target(call.context, location), "history_index", -1))
        return {**result, "editor": location, "history_before": before, "history_after": after,
                "history_index": after}

    outcome = run_action(call.context, with_history, answers)
    result = outcome.get("result")
    rest = {key: value for key, value in outcome.items() if key != "result" and value}
    return {**(result if isinstance(result, dict) else {"done": True}), **rest}


def _open(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import NO_EDITOR, shown_document

    context = call.context
    if call.arguments["editor"] == "tool":
        from cdmw.mcp.texture_files import open_rail
        return open_rail(call)
    if call.arguments.get("source", "mesh") != "mesh" or not call.arguments.get("texture"):
        raise ToolError(INVALID_ARGUMENTS, "The docked editor opens a mesh texture by texture ID or game path.")
    wanted = call.arguments["texture"]

    def open_it() -> dict[str, object]:
        tab = shown_document(context)
        if tab is None or not hasattr(tab, "open_texture_in_window"):
            raise ToolError(UNAVAILABLE, NO_EDITOR)
        dock = getattr(getattr(tab, "standalone_workspace", None), "textures_dock", None)
        rows = [row for group in getattr(dock, "groups", ()) or () for row in group.rows]
        key = wanted.replace("\\", "/").casefold()
        match = next((row for row in rows if row.texture_id == wanted), None) or next(
            (row for row in rows if str(row.game_path).replace("\\", "/").casefold() == key), None)
        if rows and match is None:
            raise ToolError(NOT_FOUND, f"The Textures panel has no texture {wanted}. textures_list lists them.")
        tab.open_texture_in_window(match.texture_id if match is not None else wanted)
        return {"opening": True, "texture": match.texture_id if match is not None else wanted}

    return _act(call, open_it)


def _tool(call) -> dict[str, object]:
    from cdmw.mcp.texture_edits import points_for, set_tool_options

    a = call.arguments

    def choose() -> dict[str, object]:
        editor = _editor(call)
        tool = str(a.get("tool") or "")
        if tool:
            if tool not in (getattr(editor, "tool_buttons", {}) or {}):
                raise ToolError(NOT_FOUND, f"The Texture Editor has no tool {tool}. textures_state lists them.")
            editor._set_active_tool(tool)
        if a.get("settings"):
            set_tool_options(editor, a["settings"])
        if "clone_source" in a:
            if a["clone_source"] is None:
                editor.clear_clone_source_point()
            else:
                point = points_for(editor, {"action": "clone_source", "points": [a["clone_source"]]})[0]
                editor.canvas.clone_source_picked.emit(point)
        if a.get("colour"):
            editor.paint_color_edit.setText(str(a["colour"]))
        for name, slider in (("size", "brush_size_slider"), ("hardness", "hardness_slider"),
                             ("opacity", "opacity_slider"), ("flow", "flow_slider")):
            if a.get(name) is not None:
                control = getattr(editor, slider)
                control.setValue(max(control.minimum(), min(control.maximum(), int(a[name]))))
        editor._handle_tool_settings_changed()
        if a.get("save_preset"):
            editor.save_current_brush_preset()
        if a.get("apply_recolor"):
            editor.apply_recolor_to_active_layer()
        settings = editor.current_tool_settings
        return {"tool": settings.tool, "colour": settings.color_hex, "size": editor.brush_size_slider.value()}

    return _act(call, choose, {"text": a["save_preset"]} if a.get("save_preset") else None)


_ADJUSTMENT_BUTTONS = {
    "duplicate": "adjustment_duplicate_button", "remove": "adjustment_remove_button", "reset": "adjustment_reset_button",
    "move_up": "adjustment_up_button", "move_down": "adjustment_down_button", "solo": "adjustment_solo_button",
    "mask_active": "adjustment_use_active_mask_button", "clear_mask": "adjustment_clear_mask_button",
}


def _adjust(call) -> dict[str, object]:
    from cdmw.mcp.texture_edits import enabled, required, select_combo, select_item

    a = call.arguments

    def adjust() -> dict[str, object]:
        editor = _editor(call)
        action = a["action"]
        if action == "add":
            required(a, "type")
            combo = editor.adjustment_add_combo
            index = combo.findData(str(a["type"]))
            if index < 0:
                kinds = [str(combo.itemData(row)) for row in range(combo.count())]
                raise ToolError(NOT_FOUND, f"The adjustments are: {', '.join(kinds)}.")
            before = len(editor.document.adjustment_layers)
            combo.setCurrentIndex(index)
            editor.add_adjustment_layer()
            if len(editor.document.adjustment_layers) == before:
                raise ToolError(UNAVAILABLE, "The Texture Editor did not add the adjustment.")
        else:
            if "id" in a:
                select_item(editor.adjustments_list, a["id"])
            if not editor._current_adjustment_id():
                raise ToolError(UNAVAILABLE, "Choose an adjustment first.")
            if action in _ADJUSTMENT_BUTTONS:
                enabled(getattr(editor, _ADJUSTMENT_BUTTONS[action])).click()
                return {"action": action}
            if action == "enable":
                editor.adjustment_enabled_checkbox.setChecked(required(a, "enabled"))
                return {"action": action}
            if "mode" in a:
                select_combo(enabled(editor.adjustment_mode_combo), a["mode"])
                if not any(k in a for k in ("a", "b", "c", "opacity")):
                    editor.commit_selected_adjustment_properties()
        sliders = [(getattr(editor, slider), int(a[name])) for name, slider in (
            ("a", "adjustment_param_a_slider"), ("b", "adjustment_param_b_slider"),
            ("c", "adjustment_param_c_slider"), ("opacity", "adjustment_opacity_slider")) if a.get(name) is not None]
        if sliders:
            # Set together, then committed once: the sliders' change is one more Undo step,
            # as releasing a dragged slider makes it. With none given the add stands alone.
            for control, _value in sliders:
                control.blockSignals(True)
            try:
                for control, value in sliders:
                    control.setValue(value)
            finally:
                for control, _value in sliders:
                    control.blockSignals(False)
            editor.preview_selected_adjustment_properties()
            editor.commit_selected_adjustment_properties()
        if action != "add":
            return {"action": action, "id": editor._current_adjustment_id()}
        layer = editor.document.adjustment_layers[-1]
        return {"added": layer.adjustment_type, "id": layer.layer_id,
                "history_index": int(getattr(editor, "history_index", -1))}

    return _act(call, adjust)


def _stroke(call) -> dict[str, object]:
    a = call.arguments

    def paint() -> dict[str, object]:
        editor = _editor(call)
        width, height = int(editor.document.width), int(editor.document.height)
        points = []
        for point in a["points"]:
            x, y = int(point[0]), int(point[1])
            if not (0 <= x < width and 0 <= y < height):
                raise ToolError(INVALID_ARGUMENTS, f"A point lies outside the texture ({width} x {height}).")
            points.append((x, y))
        tool = str(a.get("tool") or editor.current_tool_settings.tool)
        if tool not in (getattr(editor, "tool_buttons", {}) or {}):
            raise ToolError(NOT_FOUND, f"The Texture Editor has no tool {tool}.")
        if tool != editor.current_tool_settings.tool:
            editor._set_active_tool(tool)
        before = int(getattr(editor, "history_index", -1))
        editor.canvas.stroke_committed.emit({"tool": tool, "points": points})
        return {"tool": tool, "points": len(points), "history_index": int(getattr(editor, "history_index", -1)),
                "changed": int(getattr(editor, "history_index", -1)) != before}

    return _act(call, paint)


def _history(step: str):
    def handler(call) -> dict[str, object]:
        def move() -> dict[str, object]:
            editor = _editor(call)
            getattr(editor, step)()
            return {"history_index": int(getattr(editor, "history_index", -1))}

        return _act(call, move)
    return handler


def _history_list(call):
    from cdmw.mcp.texture_edits import enabled, required

    def change():
        editor = _editor(call)
        if call.arguments["action"] == "clear":
            enabled(editor.history_clear_button).click()
        else:
            index = required(call.arguments, "index")
            if index >= editor.history_list.count():
                raise ToolError(NOT_FOUND, "The Texture Editor has no such history entry.")
            if index != editor.history_index:
                editor.history_list.setCurrentRow(index)
                enabled(editor.history_restore_button).click()
        return {"steps": editor.history_list.count()}

    return _act(call, change)


def _close_panel(call) -> dict[str, object]:
    """The docked Texture Editor's own Close Editor button: the panel hides; its texture and edits stay."""

    def close() -> dict[str, object]:
        _tab, dock = _panel(call.context)
        button = getattr(dock, "close_button", None)
        if dock is None or button is None or dock.isHidden():
            raise ToolError(UNAVAILABLE, "The Mesh Editor's Texture Editor panel is not open.")
        target_now = getattr(dock, "target", None)
        button.click()
        return {"closed": True, "shown": not dock.isHidden(),
                "texture": str(getattr(target_now, "display_name", "") or ""),
                "message": "The Texture Editor panel is hidden; the texture and its edits stay. textures_open "
                           "shows it again."}

    return _act(call, close)


def texture_tools() -> list[Tool]:
    from cdmw.mcp.texture_edits import POINTS, TEXT, TOOL_SETTINGS, edit_tools
    from cdmw.mcp.texture_files import file_tools
    from cdmw.mcp.texture_mesh_tools import texture_mesh_tools
    from cdmw.mcp.texture_pixels import pixel_tools

    return [
        *edit_tools(), *pixel_tools(), *file_tools(), *texture_mesh_tools(),
        Tool(name="textures.state", family="textures", title="Texture Editor state",
             description="Read the selected editor's texture, layers, tool, history and sharing state. "
                         "The editors field reports docked and tool independently.",
             input_schema=texture_schema(), effect=READ, route="ui:TextureEditorPanel", handler=_state,
             runs_on=ON_UI),
        Tool(name="textures.open", family="textures", title="Open a texture",
             description="Opens one of the shown mesh's textures in the Texture Editor, as a double-click on "
                         "its row in the Textures panel does: 'texture' is its texture_id or game path from "
                         "textures_list. With editor=tool, choose source=file, project or archive and pass its path as texture.",
             input_schema=texture_schema({"texture": PATH, "package": PATH, "source": {"type": "string", "enum":
                                         ["mesh", "file", "archive", "project"]}}, ["texture"]),
             effect=EDIT, route="ui:open_texture_in_window", handler=_open, runs_on=ON_WORKER),
        Tool(name="textures.tool", family="textures", title="Choose a tool",
             description="Chooses the Texture Editor's tool (paint, erase, fill ...) and its settings as the "
                         "tool buttons and sliders do: 'colour' (#RRGGBB), 'size' in pixels, 'hardness', "
                         "'opacity' and 'flow' in percent.",
             input_schema=texture_schema({"tool": {"type": "string", "maxLength": 32},
                                         "colour": {"type": "string", "maxLength": 9},
                                         "size": {"type": "integer", "minimum": 1, "maximum": 4096},
                                         "hardness": _PERCENT, "opacity": _PERCENT, "flow": _PERCENT,
                                         "settings": TOOL_SETTINGS, "clone_source": {**POINTS["items"], "type": ["array", "null"]},
                                         "save_preset": TEXT, "apply_recolor": {"type": "boolean"}}),
             effect=EDIT, route="ui:TextureEditor._set_active_tool", handler=_tool, runs_on=ON_CALL),
        Tool(name="textures.adjust", family="textures", title="Add an adjustment",
             description="Add an adjustment or choose an existing one by ID to update, move, mask or remove. "
                         "Adding records one Undo step. Setting its sliders together records one more.",
             input_schema=texture_schema({"action": {"type": "string", "default": "add",
                                                    "enum": ["add", "update", "enable", *_ADJUSTMENT_BUTTONS]},
                                         "id": TEXT, "mode": TEXT, "enabled": {"type": "boolean"},
                                         "type": {"type": "string", "minLength": 1, "maxLength": 64},
                                         "a": {"type": "integer"}, "b": {"type": "integer"},
                                         "c": {"type": "integer"}, "opacity": _PERCENT}),
             effect=EDIT, route="ui:TextureEditor.add_adjustment_layer", handler=_adjust, runs_on=ON_CALL),
        Tool(name="textures.stroke", family="textures", title="Paint a stroke",
             description="One stroke on the open texture with the chosen tool (or 'tool'), along 'points' "
                         "([x, y] in texture pixels), committed as the canvas commits a stroke: one Undo "
                         "step, shown on the model live. Set the colour and size with textures_tool first.",
             input_schema=texture_schema({"tool": {"type": "string", "maxLength": 32},
                                         "points": {"type": "array", "minItems": 1, "maxItems": MAX_POINTS,
                                                    "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                                              "items": {"type": "integer"}}}}, ["points"]),
             effect=EDIT, route="ui:TextureEditorCanvas.stroke_committed", handler=_stroke, runs_on=ON_CALL),
        Tool(name="textures.history", family="textures", title="Restore or clear texture history",
             description="Restore a history entry by index or clear the history where the editor allows it.",
             input_schema=texture_schema({"action": {"type": "string", "enum": ["restore", "clear"]},
                                          "index": {"type": "integer", "minimum": 0}}, ["action"]),
             effect=DESTRUCTIVE, effect_of=lambda call: DESTRUCTIVE if call.arguments["action"] == "clear" else EDIT,
             route="ui:TextureEditor.restore_selected_history/clear_history", handler=_history_list, runs_on=ON_CALL),
        Tool(name="textures.close_panel", family="textures", title="Close the Texture Editor panel",
             description="Closes the Mesh Editor's docked Texture Editor panel, as its Close Editor button does: "
                         "the panel hides, and the open texture and its edits stay (shown on the model, kept "
                         "for Build Mod). textures_open shows it again. The mesh is not closed.",
             input_schema=object_schema(), effect=READ, route="ui:MeshEditorTextureTools.close_button",
             handler=_close_panel, runs_on=ON_CALL),
        Tool(name="textures.undo", family="textures", title="Undo (texture)",
             description="Undo in the Texture Editor.", input_schema=texture_schema(), effect=EDIT,
             route="ui:TextureEditor.undo", handler=_history("undo"), runs_on=ON_CALL),
        Tool(name="textures.redo", family="textures", title="Redo (texture)",
             description="Redo in the Texture Editor.", input_schema=texture_schema(), effect=EDIT,
             route="ui:TextureEditor.redo", handler=_history("redo"), runs_on=ON_CALL),
    ]


__all__ = ["texture_tools"]
