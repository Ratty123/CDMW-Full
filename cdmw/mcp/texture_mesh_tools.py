"""Typed MCP tools between the Mesh Editor's 3D selection and its docked texture.

``textures.select_from_mesh`` turns the selected faces (or whole parts) into a selection on
the docked texture, as the panel's Select From Mesh Selection does. ``textures.mesh_at``
reads back which faces a texture pixel, or the current texture selection, covers.

The pixels are worked out off the UI thread; the snapshot and the selection change are made
on it. The rules are in :mod:`cdmw.services.mesh_texture_selection`.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

_DOCKED = {"type": "string", "enum": ["docked"], "default": "docked"}
_MODES = ["replace", "add", "subtract", "intersect"]
_ORIENTATION = ("U runs left to right and V 0 is the top row, as the 3D view samples the texture "
                "(flipped for a material that flips V). UVs outside 0-1 wrap, as the model repeats "
                "the texture; the UV page draws only 0-1.")


def _refused(exc: Exception) -> ToolError:
    return ToolError(UNAVAILABLE, str(exc))


def _snapshot(call, *, part_ids=None, every_face=False):
    """(panel, editor, snapshot, document key, size), read on the UI thread."""

    from cdmw.mcp.texture_tools import _editor, _panel
    from cdmw.services.mesh_texture_selection import TextureMeshRefusal
    from cdmw.ui.mesh_editor.texture_mesh_selection_flow import dock_snapshot

    def read():
        editor = _editor(call)
        tools = _panel(call.context)[1]
        try:
            snapshot, key = dock_snapshot(tools, part_ids=part_ids, every_face=every_face)
        except TextureMeshRefusal as exc:
            raise _refused(exc) from None
        return tools, editor, snapshot, key, (int(editor.document.width), int(editor.document.height))

    return call.context.ui_call(read)


def _part_rows(snapshot, counts):
    return [{"part": part, "name": snapshot.part_names.get(part, ""), "faces": int(count)}
            for part, count in sorted(counts.items())]


def _select_from_mesh(call) -> dict[str, object]:
    from cdmw.mcp.texture_tools import _act
    from cdmw.services.mesh_texture_selection import TextureMeshRefusal, build_texture_mesh_selection
    from cdmw.ui.mesh_editor.texture_mesh_selection_flow import MODE_NAMES, apply_selection, selection_mode

    a = call.arguments
    part_ids = a.get("part_ids")
    tools, editor, snapshot, key, size = _snapshot(call, part_ids=part_ids)
    try:
        selection = build_texture_mesh_selection(snapshot, *size, grow=int(a.get("grow") or 0))
    except TextureMeshRefusal as exc:
        raise _refused(exc) from None

    def apply() -> dict[str, object]:
        mode = str(a.get("mode") or selection_mode(editor))
        try:
            text = apply_selection(editor, key, snapshot, selection, mode)
        except TextureMeshRefusal as exc:
            raise _refused(exc) from None
        show = getattr(tools, "_show_mesh_selection", None)
        if callable(show):
            show(text, False)
        report = selection.report
        return {"texture": snapshot.texture, "lod": snapshot.lod_index, "mode": MODE_NAMES.get(mode, mode),
                "from": snapshot.source, "selected_pixels": selection.pixels, "faces": report.faces,
                "parts": _part_rows(snapshot, report.faces_by_part),
                "shared_faces": _part_rows(snapshot, selection.shared),
                "left_out": _part_rows(snapshot, snapshot.ignored),
                "wrapped_faces": report.wrapped_faces, "faces_under_a_pixel": report.faces_under_a_pixel,
                "skipped_faces": report.skipped_faces + report.too_many_repeats,
                "selection": editor.document.selection.mode, "status": text, "notes": list(selection.notes)}

    return _act(call, apply)


def _mesh_at(call) -> dict[str, object]:
    import numpy as np

    from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
    from cdmw.domain.textures.uv_selection import uv_faces_covering
    from cdmw.services.mesh_texture_selection import faces_answer

    a = call.arguments
    has_x, has_y = "x" in a, "y" in a
    if has_x != has_y:
        raise ToolError(INVALID_ARGUMENTS, "Give both x and y, or neither to read the texture selection.")
    tools, editor, snapshot, _key, (width, height) = _snapshot(call, every_face=True)
    answer: dict[str, object] = {"texture": snapshot.texture, "lod": snapshot.lod_index,
                                 "orientation": _ORIENTATION}
    if has_x:
        x, y = int(a["x"]), int(a["y"])
        if not (0 <= x < width and 0 <= y < height):
            raise ToolError(INVALID_ARGUMENTS, f"The pixel lies outside the texture ({width} x {height}).")
        faces = uv_faces_covering(width, height, snapshot.parts, pixel=(x, y))
        answer["pixel"] = [x, y]
    else:
        def read_mask():
            document = editor.document
            return build_texture_editor_selection_mask(document.width, document.height, document.selection)

        mask = call.context.ui_call(read_mask)
        if mask is None or not np.any(mask):
            raise ToolError(UNAVAILABLE, "The texture has no selection: give x and y, or select pixels first.")
        faces = uv_faces_covering(width, height, snapshot.parts, mask=mask)
        answer["selected_pixels"] = int(np.count_nonzero(mask))
    rows = faces_answer(snapshot, faces)
    answer.update({"faces": sum(row["faces"] for row in rows), "parts": rows})
    return answer


def texture_mesh_tools() -> list[Tool]:
    return [
        Tool(name="textures.select_from_mesh", family="textures", title="Select from the mesh selection",
             description="Select, on the docked texture, the pixels the Mesh Editor's selected faces cover, "
                         "as Select From Mesh Selection does: whole selected parts count with all their faces, "
                         "selected vertices with the faces they enclose. 'part_ids' selects whole parts instead. "
                         "'mode' (default: the selection Mode) combines it with the selection; 'grow' widens it "
                         "by pixels to cover seams. One Undo step. Refused when the faces do not use the open "
                         "texture. " + _ORIENTATION + " shared_faces counts faces outside the choice that share "
                         "the pixels (mirrored or overlapping UVs).",
             input_schema=object_schema({"editor": _DOCKED,
                                         "part_ids": {"type": "array", "minItems": 1, "maxItems": 512,
                                                      "items": {"type": "integer", "minimum": 0}},
                                         "mode": {"type": "string", "enum": _MODES},
                                         "grow": {"type": "integer", "minimum": 0, "maximum": 16}}),
             effect=EDIT, route="ui:MeshEditorTextureTools.select_from_mesh", handler=_select_from_mesh,
             runs_on=ON_WORKER),
        Tool(name="textures.mesh_at", family="textures", title="Faces under texture pixels",
             description="Which faces of the shown mesh cover a pixel ('x', 'y' in texture pixels) of the docked "
                         "texture, or, without them, any pixel of its current selection: by part, with face "
                         "numbers as mesh_geometry numbers them. Every face is listed where UVs are mirrored or "
                         "overlap. " + _ORIENTATION,
             input_schema=object_schema({"editor": _DOCKED, "x": {"type": "integer", "minimum": 0},
                                         "y": {"type": "integer", "minimum": 0}}),
             effect=READ, route="service:uv_faces_covering", handler=_mesh_at, runs_on=ON_WORKER),
    ]


__all__ = ["texture_mesh_tools"]
