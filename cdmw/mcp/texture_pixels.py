"""Bounded lossless PNG transfer at the Texture Editor document boundary."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, TOO_LARGE, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.texture_edits import TEXT, integer
from cdmw.mcp.texture_tools import PATH, _act, _editor, texture_schema
from cdmw.mcp.tools import ON_CALL, ON_WORKER, Tool

MAX_REGION_PIXELS = 1024 * 1024
MAX_PNG_BYTES = 6 * 1024 * 1024
MAX_IMPORT_PIXELS = 4096 * 4096


def _read_png(args):
    import numpy as np
    from PIL import Image

    if ("path" in args) == ("data" in args):
        raise ToolError(INVALID_ARGUMENTS, "Supply exactly one PNG path or base64 data.")
    try:
        if "path" in args:
            with Path(args["path"]).open("rb") as stream:
                data = stream.read(MAX_PNG_BYTES + 1)
        else:
            data = base64.b64decode(args["data"], validate=True)
        if len(data) > MAX_PNG_BYTES:
            raise ToolError(TOO_LARGE, "The PNG exceeds 6 MiB.")
        with Image.open(BytesIO(data), formats=["PNG"]) as image:
            if image.width * image.height > MAX_IMPORT_PIXELS:
                raise ToolError(TOO_LARGE, "The PNG exceeds 16 megapixels.")
            return np.array(image.convert("RGBA"))
    except (FileNotFoundError, IsADirectoryError):
        raise ToolError(NOT_FOUND, "The PNG file could not be opened.") from None
    except (OSError, ValueError, binascii.Error, Image.DecompressionBombError) as exc:
        raise ToolError(INVALID_ARGUMENTS, f"Invalid PNG: {exc}") from None


def _read(call):
    from PIL import Image
    from cdmw.mcp.server import ImageResult
    from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels
    from cdmw.ui.texture_workflow.editor_session import texture_editor_document_composite_revision
    from cdmw.ui.texture_workflow.editor_view_state import texture_editor_composite_render_state

    args = call.arguments
    picture = call.tool.name == "view.texture_image"

    def snapshot():
        editor = _editor(call)
        document = editor.document
        layer = args.get("layer")
        pixels = None
        if layer is not None:
            pixels = editor.layer_pixels.get(layer)
            if pixels is None:
                raise ToolError(NOT_FOUND, f"No raster layer has ID {layer}.")
        w, h = (pixels.shape[1], pixels.shape[0]) if pixels is not None else (document.width, document.height)
        x, y = args.get("x", 0), args.get("y", 0)
        width, height = args.get("width", w), args.get("height", h)
        if x + width > w or y + height > h:
            raise ToolError(INVALID_ARGUMENTS, "The requested region extends outside the image.")
        if not picture and width * height > MAX_REGION_PIXELS:
            raise ToolError(TOO_LARGE, "Read at most 1,048,576 pixels per region.")
        facts = {"editor": args["editor"], "layer": layer, "x": x, "y": y, "width": width, "height": height}
        if pixels is None:
            revision = texture_editor_document_composite_revision(document, has_floating_pixels=editor._floating_pixels is not None)
            if editor._composite_cache_revision == revision and editor._composite_dirty_bounds is None:
                pixels = editor._composite_cache
        if pixels is not None:
            return facts, pixels[y:y+height, x:x+width].copy(), None, None, None
        floating = editor._floating_pixels
        return facts, None, document, copy_texture_editor_layer_pixels(editor.layer_pixels), (
            floating.copy() if floating is not None else None)

    facts, pixels, document, layers, floating = call.context.ui_call(snapshot)
    if pixels is None:
        bounds = tuple(facts[k] for k in ("x", "y", "width", "height"))
        if floating is None and not picture:
            from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers_region
            pixels = flatten_texture_editor_layers_region(document, layers, bounds)
        else:
            pixels = texture_editor_composite_render_state(document, layers, floating, revision=0,
                        composite_cache=None, composite_cache_revision=-1, dirty_bounds=None).rgba
            x, y, w, h = bounds
            pixels = pixels[y:y+h, x:x+w]
    image = Image.fromarray(pixels)
    if picture:
        side = args.get("max_side", 1024)
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, "PNG")
    if picture:
        return ImageResult(output.getvalue(), {**facts, "width": image.width, "height": image.height})
    return {**facts, "mime_type": "image/png", "data": base64.b64encode(output.getvalue()).decode("ascii")}


def prepare_document_change(call, prepare, *, raster=False):
    """Run the editor's pixel operation off-thread, then commit to the same live revision."""
    from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels

    def snapshot():
        editor = _editor(call)
        if editor.document.floating_selection is not None:
            raise ToolError(UNAVAILABLE, "Commit or cancel the floating selection first.")
        if raster and (editor.document.quick_mask_enabled or editor._editing_mask_target):
            raise ToolError(UNAVAILABLE, "Leave mask editing before importing raster pixels.")
        return editor, editor.document, editor.history_index, copy_texture_editor_layer_pixels(editor.layer_pixels)

    owner, document, index, layers = call.context.ui_call(snapshot)
    call.check_cancelled()
    try:
        change, result = prepare(document, layers)
    except ValueError as exc:
        raise ToolError(INVALID_ARGUMENTS, str(exc)) from None

    def commit():
        editor = _editor(call)
        if editor is not owner or editor.document is not document or editor.history_index != index:
            raise ToolError(UNAVAILABLE, "The texture changed while the edit was being prepared. Try again.")
        call.check_cancelled()
        if change is not None:
            # Reuse live buffers for untouched layers. Worker snapshots are read-only.
            for key, original in editor.layer_pixels.items():
                if change.layer_pixels.get(key) is layers[key]:
                    change.layer_pixels[key] = original
            editor._apply_document_pixels_change_state(change)
        return {**result, "layer": editor.document.active_layer_id}
    return _act(call, commit)


def _write(call):
    from cdmw.ui.texture_workflow.editor_document_state import texture_editor_png_change

    args = call.arguments
    name = args.get("name", "Imported pixels") if call.tool.name == "textures.import_pixels" else None

    def prepare(document, layers):
        rgba = _read_png(args)
        change = texture_editor_png_change(document, layers, rgba, args.get("x", 0), args.get("y", 0),
                                          new_layer_name=name)
        return change, {"width": rgba.shape[1], "height": rgba.shape[0]}
    return prepare_document_change(call, prepare, raster=True)


def pixel_tools():
    position = {"x": integer(0, 65535), "y": integer(0, 65535)}
    inputs = {**position, "path": PATH, "data": {"type": "string", "minLength": 1, "maxLength": MAX_PNG_BYTES*4//3}}
    return [
        Tool("textures.read_region", "textures", "Read a rectangle of the open composite or a raw layer as base64 PNG. "
             "Coordinates are local to the chosen image. Limit 1,048,576 pixels.",
             texture_schema({**position, "width": integer(1, 65536), "height": integer(1, 65536), "layer": TEXT},
                            ["width", "height"]), READ, "ui:TextureEditor.composite", _read, ON_WORKER),
        Tool("view.texture_image", "view", "Picture of the open composite or the raw raster layer with the given ID.",
             texture_schema({"layer": TEXT, "max_side": integer(1, 1024)}), READ, "ui:TextureEditor.composite", _read, ON_CALL),
        Tool("textures.write_region", "textures", "Write a PNG to the active layer at canvas x,y, in one Undo step. "
             "Accepts a PNG path or base64 data.", texture_schema(inputs, ["x", "y"]), EDIT,
             "ui:TextureEditor._apply_document_pixels_change_state", _write, ON_WORKER),
        Tool("textures.import_pixels", "textures", "Import a PNG path or base64 data as a named raster layer at x,y.",
             texture_schema({**inputs, "name": TEXT}), EDIT, "ui:TextureEditor._apply_document_pixels_change_state",
             _write, ON_WORKER),
    ]
