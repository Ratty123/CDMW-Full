"""The Texture Editor's tools, for the texture open beside the shown Mesh Editor document.

They drive the editor's own controls: opening a texture is the Textures
panel's double-click, a tool is chosen as its button chooses it, an
adjustment is added and set with the editor's list and sliders, a stroke is
committed as the canvas commits one (so it is one Undo step and reaches the
model live), Undo and Redo are the editor's. Every other Texture Editor
command (layers, selections, export) is in the registry: ``app.run_command``
with a ``texture_editor.`` id.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, Tool, object_schema

NO_TEXTURE = ("No texture is open in the Texture Editor: open one from the Mesh Editor's Textures panel "
              "(textures_list, then textures_open).")
MAX_POINTS = 20000
_PERCENT = {"type": "integer", "minimum": 0, "maximum": 100}


def _panel(context):
    from cdmw.mcp.mesh_tools import shown_document

    tab = shown_document(context)
    panel = getattr(tab, "_texture_tools_panel", None)
    return tab, (panel() if callable(panel) else None)


def _editor(context):
    """The editor with a texture open in it."""

    _tab, panel = _panel(context)
    editor = getattr(panel, "editor", None)
    if editor is None or getattr(editor, "document", None) is None:
        raise ToolError(UNAVAILABLE, NO_TEXTURE)
    busy = getattr(editor, "_busy", None)
    if callable(busy) and busy():
        raise ToolError(UNAVAILABLE, "The Texture Editor is busy; try again in a moment.")
    return editor


def _state(call) -> dict[str, object]:
    tab, panel = _panel(call.context)
    editor = getattr(panel, "editor", None)
    document = getattr(editor, "document", None)
    if panel is None or editor is None or document is None:
        return {"open": False, "panel_shown": bool(panel is not None and panel.isVisible())}
    live = getattr(tab, "_live_texture_updates", None)
    keeper = getattr(tab, "_live_texture_keeping", None)
    busy = getattr(editor, "_busy", None)
    settings = getattr(editor, "current_tool_settings", None)
    return {
        "open": True, "panel_shown": bool(panel.isVisible()), "floating": bool(panel.isFloating()),
        "title": str(getattr(document, "title", "") or ""),
        "source": str(getattr(getattr(document, "source_binding", None), "source_path", "") or ""),
        "width": int(document.width), "height": int(document.height),
        "layers": [{"id": layer.layer_id, "name": getattr(layer, "name", ""),
                    "visible": bool(getattr(layer, "visible", True)),
                    "active": layer.layer_id == document.active_layer_id} for layer in document.layers],
        "adjustments": [{"id": layer.layer_id, "type": layer.adjustment_type,
                         "enabled": bool(getattr(layer, "enabled", True))} for layer in document.adjustment_layers],
        "tool": str(getattr(settings, "tool", "") or ""),
        "tools": sorted(getattr(editor, "tool_buttons", {}) or {}),
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


def _act(call, function) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    outcome = run_action(call.context, function, None)
    result = outcome.get("result")
    rest = {key: value for key, value in outcome.items() if key != "result" and value}
    return {**(result if isinstance(result, dict) else {"done": True}), **rest}


def _open(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import NO_EDITOR, shown_document

    context = call.context
    wanted = str(call.arguments["texture"])

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
    a = call.arguments
    context = call.context

    def choose() -> dict[str, object]:
        editor = _editor(context)
        tool = str(a.get("tool") or "")
        if tool:
            if tool not in (getattr(editor, "tool_buttons", {}) or {}):
                raise ToolError(NOT_FOUND, f"The Texture Editor has no tool {tool}. textures_state lists them.")
            editor._set_active_tool(tool)
        if a.get("colour"):
            editor.paint_color_edit.setText(str(a["colour"]))
        for name, slider in (("size", "brush_size_slider"), ("hardness", "hardness_slider"),
                             ("opacity", "opacity_slider"), ("flow", "flow_slider")):
            if a.get(name) is not None:
                control = getattr(editor, slider)
                control.setValue(max(control.minimum(), min(control.maximum(), int(a[name]))))
        editor._handle_tool_settings_changed()
        settings = editor.current_tool_settings
        return {"tool": settings.tool, "colour": settings.color_hex, "size": editor.brush_size_slider.value()}

    return _act(call, choose)


def _adjust(call) -> dict[str, object]:
    a = call.arguments
    context = call.context

    def add() -> dict[str, object]:
        editor = _editor(context)
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
        for name, slider in (("a", "adjustment_param_a_slider"), ("b", "adjustment_param_b_slider"),
                             ("c", "adjustment_param_c_slider"), ("opacity", "adjustment_opacity_slider")):
            if a.get(name) is not None:
                getattr(editor, slider).setValue(int(a[name]))
        editor.preview_selected_adjustment_properties()
        editor.commit_selected_adjustment_properties()
        layer = editor.document.adjustment_layers[-1]
        return {"added": layer.adjustment_type, "id": layer.layer_id,
                "history_index": int(getattr(editor, "history_index", -1))}

    return _act(call, add)


def _stroke(call) -> dict[str, object]:
    a = call.arguments
    context = call.context

    def paint() -> dict[str, object]:
        editor = _editor(context)
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
        context = call.context

        def move() -> dict[str, object]:
            editor = _editor(context)
            getattr(editor, step)()
            return {"history_index": int(getattr(editor, "history_index", -1))}

        return _act(call, move)
    return handler


def texture_tools() -> list[Tool]:
    return [
        Tool(name="textures.state", family="textures", title="Texture Editor state",
             description="The texture open in the Texture Editor beside the shown Mesh Editor document: its "
                         "name, source file and size, its layers and adjustments, the chosen tool and the "
                         "tools there are, its place in the history, and what the panel says about sharing "
                         "and keeping the edit.",
             input_schema=object_schema(), effect=READ, route="ui:TextureEditorPanel", handler=_state,
             runs_on=ON_UI),
        Tool(name="textures.open", family="textures", title="Open a texture",
             description="Opens one of the shown mesh's textures in the Texture Editor, as a double-click on "
                         "its row in the Textures panel does: 'texture' is its texture_id or game path from "
                         "textures_list.",
             input_schema=object_schema({"texture": {"type": "string", "minLength": 1, "maxLength": 512}},
                                        ["texture"]),
             effect=EDIT, route="ui:open_texture_in_window", handler=_open, runs_on=ON_CALL),
        Tool(name="textures.tool", family="textures", title="Choose a tool",
             description="Chooses the Texture Editor's tool (paint, erase, fill ...) and its settings as the "
                         "tool buttons and sliders do: 'colour' (#RRGGBB), 'size' in pixels, 'hardness', "
                         "'opacity' and 'flow' in percent.",
             input_schema=object_schema({"tool": {"type": "string", "maxLength": 32},
                                         "colour": {"type": "string", "maxLength": 9},
                                         "size": {"type": "integer", "minimum": 1, "maximum": 4096},
                                         "hardness": _PERCENT, "opacity": _PERCENT, "flow": _PERCENT}),
             effect=EDIT, route="ui:TextureEditor._set_active_tool", handler=_tool, runs_on=ON_CALL),
        Tool(name="textures.adjust", family="textures", title="Add an adjustment",
             description="Adds an adjustment to the open texture with the editor's Add list (levels, "
                         "hue_saturation ...) and sets its sliders 'a', 'b', 'c' and 'opacity' as dragging "
                         "them does. One Undo step; the model shows it live.",
             input_schema=object_schema({"type": {"type": "string", "minLength": 1, "maxLength": 64},
                                         "a": {"type": "integer"}, "b": {"type": "integer"},
                                         "c": {"type": "integer"}, "opacity": _PERCENT}, ["type"]),
             effect=EDIT, route="ui:TextureEditor.add_adjustment_layer", handler=_adjust, runs_on=ON_CALL),
        Tool(name="textures.stroke", family="textures", title="Paint a stroke",
             description="One stroke on the open texture with the chosen tool (or 'tool'), along 'points' "
                         "([x, y] in texture pixels), committed as the canvas commits a stroke: one Undo "
                         "step, shown on the model live. Set the colour and size with textures_tool first.",
             input_schema=object_schema({"tool": {"type": "string", "maxLength": 32},
                                         "points": {"type": "array", "minItems": 1, "maxItems": MAX_POINTS,
                                                    "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                                              "items": {"type": "integer"}}}}, ["points"]),
             effect=EDIT, route="ui:TextureEditorCanvas.stroke_committed", handler=_stroke, runs_on=ON_CALL),
        Tool(name="textures.undo", family="textures", title="Undo (texture)",
             description="Undo in the Texture Editor.", input_schema=object_schema(), effect=EDIT,
             route="ui:TextureEditor.undo", handler=_history("undo"), runs_on=ON_CALL),
        Tool(name="textures.redo", family="textures", title="Redo (texture)",
             description="Redo in the Texture Editor.", input_schema=object_schema(), effect=EDIT,
             route="ui:TextureEditor.redo", handler=_history("redo"), runs_on=ON_CALL),
    ]


__all__ = ["texture_tools"]
