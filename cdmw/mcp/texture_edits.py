"""Grouped texture operations, using the owning editor's controls and canvas signals."""

from __future__ import annotations

from PySide6.QtCore import Qt

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT
from cdmw.mcp.texture_tools import MAX_POINTS, PATH, _act, _editor, texture_schema
from cdmw.mcp.tools import ON_CALL, ON_WORKER, Tool


def choices(*values):
    return {"type": "string", "enum": list(values)}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


POINTS = {"type": "array", "minItems": 1, "maxItems": MAX_POINTS,
          "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer"}}}
TEXT = {"type": "string", "minLength": 1, "maxLength": 256}
BOOL = {"type": "boolean"}


def required(args, key):
    if key not in args:
        raise ToolError(INVALID_ARGUMENTS, f"{args['action']} requires {key}.")
    return args[key]


def enabled(control):
    if not control.isEnabled():
        raise ToolError(UNAVAILABLE, "This control is disabled in the Texture Editor.")
    return control


def select_combo(combo, value):
    index = combo.findData(value)
    if index < 0:
        values = [str(combo.itemData(i)) for i in range(combo.count())]
        raise ToolError(INVALID_ARGUMENTS, f"Choose one of {', '.join(values)}.")
    combo.setCurrentIndex(index)


def select_item(widget, layer_id):
    for index in range(widget.count()):
        item = widget.item(index)
        if item.data(Qt.UserRole) == layer_id:
            widget.setCurrentItem(item)
            return
    raise ToolError(NOT_FOUND, f"No layer has ID {layer_id}.")


def points_for(editor, args, *, minimum=1, maximum=MAX_POINTS):
    points = required(args, "points")
    if not minimum <= len(points) <= maximum:
        raise ToolError(INVALID_ARGUMENTS, f"{args['action']} takes {minimum} to {maximum} points.")
    if any(not (0 <= x < editor.document.width and 0 <= y < editor.document.height) for x, y in points):
        raise ToolError(INVALID_ARGUMENTS, "A point is outside the texture.")
    return [tuple(point) for point in points]


_LAYER_BUTTONS = {
    "add": "add_layer_button", "duplicate": "duplicate_layer_button", "remove": "remove_layer_button",
    "merge_down": "merge_layer_button", "move_up": "layer_up_button", "move_down": "layer_down_button",
    "mask_add": "layer_add_mask_button", "mask_invert": "layer_invert_mask_button",
    "mask_delete": "layer_delete_mask_button", "selection_to_mask": "selection_to_mask_button",
    "mask_to_selection": "selection_from_mask_button",
}
_LAYER_FLAGS = {
    "visibility": "layer_visible_checkbox", "lock": "layer_locked_checkbox", "alpha_lock": "layer_alpha_locked_checkbox",
    "mask_enable": "layer_mask_enabled_checkbox", "mask_target": "layer_edit_mask_checkbox",
}


_FLOAT_BUTTONS = {
    "float_copy": "transform_float_layer_button", "float_commit": "transform_commit_button",
    "float_cancel": "transform_cancel_button", "float_flip_h": "transform_flip_h_button",
    "float_flip_v": "transform_flip_v_button", "float_rotate_left": "transform_rotate_left_button",
    "float_rotate_right": "transform_rotate_right_button",
}
_CLIPBOARD = {"copy": "copy_content", "cut": "cut_selection_to_floating", "paste": "paste_content",
              "paste_centered": "paste_content_centered"}


def _layer(editor, args):
    action = args["action"]
    if action == "active" or "layer" in args:
        select_item(editor.layers_list, required(args, "layer"))
    if action in _FLOAT_BUTTONS:
        enabled(getattr(editor, _FLOAT_BUTTONS[action])).click()
    elif action in _CLIPBOARD:
        getattr(editor, _CLIPBOARD[action])()
    elif action == "float_transform":
        button = enabled(editor.transform_apply_button)
        if "scale" in args:
            editor.transform_scale_spin.setValue(args["scale"])
        if "rotation" in args:
            editor.transform_rotation_spin.setValue(args["rotation"])
        button.click()
    elif action in _LAYER_BUTTONS:
        enabled(getattr(editor, _LAYER_BUTTONS[action])).click()
    elif action in _LAYER_FLAGS:
        enabled(getattr(editor, _LAYER_FLAGS[action])).setChecked(required(args, "enabled"))
    elif action == "rename":
        enabled(editor.layer_name_edit).setText(required(args, "name"))
        editor.layer_name_edit.editingFinished.emit()
    elif action == "blend":
        select_combo(enabled(editor.layer_blend_mode_combo), required(args, "mode"))
    elif action == "opacity":
        enabled(editor.layer_opacity_slider).setValue(required(args, "opacity"))
    return {"active_layer": editor.document.active_layer_id}


_SELECT_BUTTONS = {"all": "selection_select_all_button", "clear": "selection_clear_button",
                   "copy_to_layer": "selection_copy_layer_button"}


def _select(editor, args):
    action = args["action"]
    if action in _SELECT_BUTTONS:
        enabled(getattr(editor, _SELECT_BUTTONS[action])).click()
    elif action in ("rect", "lasso"):
        points = points_for(editor, args, minimum=2 if action == "rect" else 3,
                            maximum=2 if action == "rect" else MAX_POINTS)
        payload = {"mode": action, "points": points}
        if action == "rect":
            (x, y), (x2, y2) = points
            payload["rect"] = (min(x, x2), min(y, y2), abs(x2-x), abs(y2-y))
        editor._set_active_tool("select_rect" if action == "rect" else "lasso")
        editor.canvas.selection_committed.emit(payload)
    elif action == "feather":
        from PySide6.QtCore import QSignalBlocker
        slider = enabled(editor.selection_feather_slider)
        with QSignalBlocker(slider):
            slider.setValue(required(args, "radius"))
        editor.commit_selection_settings()
    elif action in ("grow", "shrink"):
        button = enabled(getattr(editor, f"selection_{action}_button"))
        if "amount" in args:
            editor.selection_refine_spin.setValue(args["amount"])
        button.click()
    else:
        control = enabled(getattr(editor, f"selection_{action}_checkbox"))
        control.setChecked(args.get("enabled", not control.isChecked()))
    return {"selection": editor.document.selection.mode, "quick_mask": editor.document.quick_mask_enabled}


def _fill(editor, args):
    action = args["action"]
    if action == "clear_stamp":
        editor.clear_custom_brush_tip()
        return
    if action == "load_stamp":
        editor.load_custom_brush_tip()
        return
    tool = {"solid": "gradient", "stamp": "paint", "pattern": "paint", "noise": "paint"}.get(action, action)
    if "points" in args or action != "solid":
        points = points_for(editor, args, minimum=2 if tool == "gradient" else 1,
                            maximum=2 if tool == "gradient" else 1 if tool == "fill" else MAX_POINTS)
    else:
        points = [(0, 0), (editor.document.width - 1, editor.document.height - 1)]
    if action == "stamp" and not editor.custom_brush_tip_path_edit.text():
        raise ToolError(UNAVAILABLE, "Load an image stamp first.")
    editor._set_active_tool(tool)
    if action == "stamp":
        select_combo(editor.brush_tip_combo, "image_stamp")
    if action in ("noise", "pattern"):
        select_combo(editor.brush_pattern_combo, "grain" if action == "noise" else args.get("pattern", "hatch"))
    if "colour" in args:
        editor.paint_color_edit.setText(args["colour"])
    if action == "solid" or "secondary" in args:
        editor.secondary_color_edit.setText(editor.paint_color_edit.text() if action == "solid" else args["secondary"])
    if "gradient" in args:
        select_combo(editor.gradient_type_combo, args["gradient"])
    if "contiguous" in args:
        editor.fill_contiguous_checkbox.setChecked(args["contiguous"])
    if "tolerance" in args:
        editor.fill_tolerance_slider.setValue(args["tolerance"])
    editor._handle_tool_settings_changed()
    editor.canvas.stroke_committed.emit({"tool": tool, "points": points})


_TRANSFORM_BUTTONS = {
    "crop": "image_crop_selection_button", "trim": "image_trim_button", "flip_h": "image_flip_h_button",
    "flip_v": "image_flip_v_button", "rotate_left": "image_rotate_left_button", "rotate_right": "image_rotate_right_button",
}
_CHANNEL = {
    "pack": ("channel_pack_combo", "channel_pack_button"), "unpack": ("channel_extract_combo", "channel_extract_button"),
    "channel_to_selection": ("channel_selection_combo", "channel_selection_from_button"),
    "selection_to_channel": ("channel_selection_to_combo", "channel_selection_to_button"),
    "copy_channel": ("channel_copy_combo", "channel_copy_button"), "paste_channel": ("channel_paste_combo", "channel_paste_button"),
}


def _derive(editor, args):
    action = args["action"]
    if action in _CHANNEL:
        combo, button = _CHANNEL[action]
        control = enabled(getattr(editor, button))
        select_combo(getattr(editor, combo), required(args, "channel"))
        control.click()
    elif action == "swap_channels":
        a, b = required(args, "channel"), required(args, "other_channel")
        select_combo(editor.channel_swap_a_combo, a)
        select_combo(editor.channel_swap_b_combo, b)
        enabled(editor.channel_swap_button).click()
    elif action == "channel_enabled":
        channel, checked = required(args, "channel"), required(args, "enabled")
        enabled(getattr(editor, f"channel_{channel}_checkbox")).setChecked(checked)
    elif action in _TRANSFORM_BUTTONS:
        enabled(getattr(editor, _TRANSFORM_BUTTONS[action])).click()
    else:
        combo = {"mips": editor.native_dds_mip_combo, "format": editor.native_dds_format_combo,
                 "preset": editor.native_dds_preset_combo}[action]
        select_combo(combo, required(args, "value"))
        return {"value": combo.currentData(), "applies_on": "DDS export"}


def _resize(call):
    from cdmw.mcp.texture_pixels import prepare_document_change
    from cdmw.ui.texture_workflow.editor_document_state import (
        texture_editor_resized_canvas_state,
        texture_editor_resized_image_state,
    )

    args = call.arguments
    width, height = required(args, "width"), required(args, "height")

    def prepare(document, layers):
        if args["action"] == "resize":
            change = texture_editor_resized_image_state(document, layers, width, height)
        else:
            change = texture_editor_resized_canvas_state(document, layers, width, height, anchor=args.get("anchor", "top_left"))
        return change, {"width": width, "height": height}
    return prepare_document_change(call, prepare)


def edit_tools():
    def grouped(name, description, actions, arguments, operation, route):
        def handle(call):
            args = call.arguments
            if operation is _derive and args["action"] in ("resize", "canvas_size"):
                return _resize(call)
            answers = {"file": required(args, "path")} if args["action"] == "load_stamp" else None
            return _act(call, lambda: operation(_editor(call), args), answers)
        return Tool(name=f"textures.{name}", family="textures", title=f"Texture {name}", description=description,
                    input_schema=texture_schema({"action": choices(*actions), **arguments}, ["action"]),
                    effect=EDIT, handler=handle, route="ui:" + route, runs_on=ON_WORKER if operation is _derive else ON_CALL)

    colours = {"colour": TEXT, "secondary": TEXT, "gradient": choices("linear", "radial"), "points": POINTS}
    return [
        grouped("layer", "Edit the active raster layer or its mask. Use active with a layer ID to change target.",
                [*_LAYER_BUTTONS, *_LAYER_FLAGS, *_FLOAT_BUTTONS, *_CLIPBOARD, "float_transform", "active", "rename", "opacity", "blend"],
                {"scale": integer(10, 400), "rotation": integer(-180, 180), "layer": TEXT, "enabled": BOOL, "name": TEXT, "mode": choices("normal", "multiply", "screen", "overlay"),
                 "opacity": integer(0, 100)}, _layer, "TextureEditorLayerUiMixin"),
        grouped("select", "Create or refine a selection. Rect uses two corners. Lasso uses three or more points.",
                [*_SELECT_BUTTONS, "rect", "lasso", "invert", "grow", "shrink", "quick_mask", "feather"],
                {"points": POINTS, "amount": integer(1, 64), "radius": integer(0, 32), "enabled": BOOL}, _select, "TextureEditorSelectionUiMixin"),
        grouped("fill", "Bucket at one point, gradient between two points, or paint through an image stamp. "
                "load_stamp takes a path. stamp uses the current brush size and colour.",
                ["fill", "gradient", "load_stamp", "clear_stamp", "stamp"],
                {**colours, "path": PATH, "tolerance": integer(0, 255), "contiguous": BOOL}, _fill,
                "TextureEditorCanvas.stroke_committed"),
        grouped("generate", "Solid or gradient fill, or a grain or patterned brush stroke along points.",
                ["solid", "gradient", "noise", "pattern"],
                {**colours, "pattern": choices("hatch", "crosshatch", "speckle", "grain")}, _fill,
                "TextureEditorCanvas.stroke_committed"),
        grouped("derive", "Resize or transform the document, pack luma, unpack a channel, or select DDS export settings. "
                "mips and format set the export controls without changing document history.",
                [*_CHANNEL, *_TRANSFORM_BUTTONS, "resize", "canvas_size", "mips", "format", "preset", "swap_channels", "channel_enabled"],
                {"other_channel": choices("red", "green", "blue", "alpha"), "enabled": BOOL,
                 "channel": choices("red", "green", "blue", "alpha"), "width": integer(1, 16384),
                 "height": integer(1, 16384), "anchor": choices("center", "top_left"), "value": {"type": "string"}},
                _derive, "TextureEditorDocumentUiMixin/TextureEditorChannelUiMixin"),
    ]



# The brush and selection settings are the same controls for every canvas tool.
_COMBOS = ("brush_preset", "brush_tip", "brush_pattern", "symmetry_mode", "size_step_mode",
           "paint_blend_mode", "sharpen_mode", "soften_mode", "dodge_burn_mode", "gradient_type",
           "selection_mode", "recolor_mode")
_CHECKS = ("fill_contiguous", "sample_visible_layers", "clone_aligned", "lasso_snap", "recolor_preserve_luma")
_SLIDERS = {"roundness": (10, 100), "angle": (-180, 180), "smoothing": (0, 100), "spacing": (1, 100),
            "fill_tolerance": (0, 255), "strength": (0, 100), "smudge_strength": (1, 100),
            "dodge_burn_exposure": (1, 100), "patch_blend": (1, 100), "lasso_snap_radius": (2, 24),
            "lasso_snap_sensitivity": (1, 100), "recolor_tolerance": (0, 255), "recolor_strength": (1, 100)}
_COLOURS = ("secondary_color", "recolor_source", "recolor_target")

TOOL_SETTINGS = {"type": "object", "additionalProperties": False, "properties": {
    **dict.fromkeys(_COMBOS, TEXT), **dict.fromkeys(_CHECKS, BOOL),
    **{name: integer(*limits) for name, limits in _SLIDERS.items()}, **dict.fromkeys(_COLOURS, TEXT)}}


def set_tool_options(editor, options):
    # Validate all choices before applying the preset, which itself changes several controls.
    for name in _COMBOS:
        if name in options and getattr(editor, name + "_combo").findData(options[name]) < 0:
            raise ToolError(INVALID_ARGUMENTS, f"Unknown {name}: {options[name]}.")
    for name in _COMBOS:
        if name in options:
            select_combo(getattr(editor, name + "_combo"), options[name])
    for names, suffix, setter in ((_CHECKS, "_checkbox", "setChecked"), (_SLIDERS, "_slider", "setValue"),
                                  (_COLOURS, "_edit", "setText")):
        for name in names:
            if name in options:
                getattr(getattr(editor, name + suffix), setter)(options[name])
