"""Mesh editor action descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MESH_EDIT_MODES

_NON_NATIVE_EDITOR_SESSION_COMMANDS = frozenset(
    {"set_mode", "select", "triangulate_display", "quadrangulate_display"}
)
NATIVE_EDITOR_SESSION_COMMANDS = frozenset(MESH_EDIT_ACTIONS) - _NON_NATIVE_EDITOR_SESSION_COMMANDS


@dataclass(frozen=True, slots=True)
class MeshEditorAction:
    key: str
    text: str
    command: str
    category: str
    icon_key: str = ""
    shortcut: str = ""
    tooltip: str = ""
    mode: str = ""
    selection_mode: str = ""
    params: tuple[tuple[str, object], ...] = field(default_factory=tuple)
    requires_selection: bool = False


_SHORTCUTS = {
    "mode_object": "Ctrl+1",
    "mode_edit": "Ctrl+2",
    "mode_sculpt": "Ctrl+3",
    "select_vertex": "1",
    "select_edge": "2",
    "select_face": "3",
    "transform_move": "G",
    "transform_rotate": "R",
    "transform_scale": "S",
    "brush_grab": "Shift+G",
    "brush_smooth": "Shift+S",
    "brush_inflate": "Shift+I",
    "brush_pinch": "Shift+P",
    "delete": "Delete",
    "dissolve": "Ctrl+Delete",
    "subdivide": "Ctrl+E",
    "refine_smooth": "Ctrl+Shift+E",
    "split": "Y",
    "separate": "Shift+Y",
    "duplicate": "Shift+D",
    "mirror": "Ctrl+M",
    "extrude": "E",
    "inset": "I",
    "loop_cut": "Ctrl+R",
    "edge_split": "Alt+Y",
    "merge": "M",
    "weld": "Ctrl+W",
    "bridge": "Ctrl+B",
    "fill": "F",
    "remove_doubles": "Ctrl+Alt+W",
    "delete_loose_vertices": "Alt+Delete",
    "compact_orphans": "Ctrl+Alt+Delete",
    "fix_winding": "Ctrl+Alt+N",
    "fill_holes": "Ctrl+F",
    "recalculate_normals": "Shift+N",
    "generate_tangents": "Ctrl+Shift+N",
    "flip_normals": "Alt+N",
    "sharpen_normals": "Ctrl+Alt+H",
    "soften_normals": "Ctrl+Alt+S",
    "weighted_normals": "Ctrl+Alt+Shift+S",
    "copy_normals": "Ctrl+Alt+Shift+N",
    "uv_transform": "U",
    "uv_flip_u": "Shift+U",
    "uv_flip_v": "Shift+V",
    "uv_rotate_90": "Alt+U",
    "uv_island_transform": "Ctrl+U",
    "uv_normalize": "Ctrl+Alt+U",
    "uv_align_u": "Ctrl+Shift+U",
    "uv_align_v": "Ctrl+Shift+V",
    "uv_planar_project": "Ctrl+P",
    "uv_box_project": "Ctrl+Alt+B",
    "uv_cylindrical_project": "Ctrl+Alt+C",
    "uv_auto_unwrap": "Ctrl+Alt+P",
    "uv_pack": "Alt+P",
    "uv_snap_grid": "Ctrl+Alt+G",
    "uv_snap_pixels": "Ctrl+Shift+P",
    "material_assign": "Shift+M",
    "material_copy": "Alt+M",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
}

_TOOLTIPS = {
    "mode_object": "Object mode for whole-part editing.",
    "mode_edit": "Edit mode for vertex, edge, face, UV, and topology tools.",
    "mode_sculpt": "Sculpt mode for brush-based surface edits.",
    "select_vertex": "Select vertices.",
    "select_edge": "Select edges.",
    "select_face": "Select faces.",
    "transform_move": "Move selected mesh elements.",
    "transform_rotate": "Rotate selected mesh elements.",
    "transform_scale": "Scale selected mesh elements.",
    "brush_grab": "Grab selected or brushed vertices.",
    "brush_smooth": "Smooth selected or brushed vertices.",
    "brush_inflate": "Inflate selected or brushed vertices.",
    "brush_pinch": "Pinch selected or brushed vertices.",
    "uv_island_transform": "Transform the connected UV island from the current selection.",
    "uv_rotate_90": "Rotate selected UVs around the texture center.",
    "uv_normalize": "Normalize selected UVs into the 0-1 texture tile.",
    "uv_align_u": "Align selected UVs to the left edge of their selection bounds.",
    "uv_align_v": "Align selected UVs to the bottom edge of their selection bounds.",
    "uv_planar_project": "Project selected vertices onto a basic XY planar UV layout.",
    "uv_box_project": "Project selected vertices with a basic normal-driven box UV layout.",
    "uv_cylindrical_project": "Project selected vertices around a basic vertical cylinder UV layout.",
    "uv_auto_unwrap": "Auto unwrap selected parts with native xatlas when safe, falling back to planar UVs.",
    "uv_pack": "Pack selected UV islands into the 0-1 texture tile.",
    "uv_snap_grid": "Snap selected UVs to a coarse edit grid.",
    "uv_snap_pixels": "Snap selected UVs to texture-pixel increments.",
    "generate_tangents": "Generate per-vertex tangents from mesh UVs.",
    "sharpen_normals": "Set selected vertices to selected face normals for hard-edge inspection.",
    "soften_normals": "Re-average normals on selected parts.",
    "copy_normals": "Copy normals from the original/source mesh onto the current selection.",
    "remove_doubles": "Merge duplicate vertices within a tiny distance threshold.",
    "delete_loose_vertices": "Delete vertices not referenced by valid faces.",
    "compact_orphans": "Compact orphan vertices and invalid face references.",
    "fix_winding": "Flip triangle winding when it disagrees with vertex normals.",
    "fill_holes": "Fill simple three- or four-edge boundary holes.",
    "refine_smooth": "Subdivide selected detail, then smooth the affected vertices for less pointy surfaces.",
    "material_assign": "Assign material and texture metadata to selected parts or faces.",
    "material_copy": "Copy material routing metadata from another part into selected parts or faces.",
    "weighted_normals": "Weight vertex normals by face area for smoother lighting without changing mesh shape.",
}


def _with_palette_metadata(action: MeshEditorAction) -> MeshEditorAction:
    return MeshEditorAction(
        key=action.key,
        text=action.text,
        command=action.command,
        category=action.category,
        icon_key=action.icon_key or action.key,
        shortcut=action.shortcut or _SHORTCUTS.get(action.key, ""),
        tooltip=action.tooltip or _TOOLTIPS.get(action.key, action.text),
        mode=action.mode,
        selection_mode=action.selection_mode,
        params=action.params,
        requires_selection=action.requires_selection,
    )


MESH_EDITOR_ACTIONS = tuple(_with_palette_metadata(action) for action in (
    MeshEditorAction("mode_object", "Object", "set_mode", "mode", mode="object"),
    MeshEditorAction("mode_edit", "Edit", "set_mode", "mode", mode="edit"),
    MeshEditorAction("mode_sculpt", "Sculpt", "set_mode", "mode", mode="sculpt"),
    MeshEditorAction("select_vertex", "Vertex", "select", "selection", selection_mode="vertex"),
    MeshEditorAction("select_edge", "Edge", "select", "selection", selection_mode="edge"),
    MeshEditorAction("select_face", "Face", "select", "selection", selection_mode="face"),
    MeshEditorAction("transform_move", "Move", "transform", "transform", requires_selection=True),
    MeshEditorAction("transform_rotate", "Rotate", "transform", "transform", params=(("rotate", (0.0, 0.0, 15.0)),), requires_selection=True),
    MeshEditorAction("transform_scale", "Scale", "transform", "transform", params=(("scale", (1.1, 1.1, 1.1)),), requires_selection=True),
    MeshEditorAction("brush_grab", "Grab", "brush", "sculpt", mode="sculpt", params=(("tool", "grab"),)),
    MeshEditorAction("brush_smooth", "Smooth", "brush", "sculpt", mode="sculpt", params=(("tool", "smooth"),)),
    MeshEditorAction("brush_inflate", "Inflate", "brush", "sculpt", mode="sculpt", params=(("tool", "inflate"),)),
    MeshEditorAction("brush_pinch", "Pinch", "brush", "sculpt", mode="sculpt", params=(("tool", "pinch"),)),
    MeshEditorAction("delete", "Delete", "delete", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("dissolve", "Dissolve", "dissolve", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("subdivide", "Subdivide", "subdivide", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("refine_smooth", "Refine Smooth", "refine_smooth", "topology", mode="edit", params=(("smooth_iterations", 2), ("smooth_strength", 0.5)), requires_selection=True),
    MeshEditorAction("split", "Split", "split", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("separate", "Separate", "separate", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("duplicate", "Duplicate", "duplicate", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("mirror", "Mirror", "mirror", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("extrude", "Extrude", "extrude", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("inset", "Inset", "inset", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("loop_cut", "Loop Cut", "loop_cut", "topology", mode="edit", selection_mode="edge", requires_selection=True),
    MeshEditorAction("edge_split", "Edge Split", "edge_split", "topology", mode="edit", selection_mode="edge", requires_selection=True),
    MeshEditorAction("merge", "Merge", "merge", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("weld", "Weld", "weld", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("bridge", "Bridge", "bridge", "topology", mode="edit", selection_mode="edge", requires_selection=True),
    MeshEditorAction("fill", "Fill", "fill", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("remove_doubles", "Remove Doubles", "remove_doubles", "cleanup", mode="edit"),
    MeshEditorAction("delete_loose_vertices", "Delete Loose", "delete_loose_vertices", "cleanup", mode="edit"),
    MeshEditorAction("compact_orphans", "Compact Orphans", "compact_orphans", "cleanup", mode="edit"),
    MeshEditorAction("fix_winding", "Fix Winding", "fix_winding", "cleanup", mode="edit"),
    MeshEditorAction("fill_holes", "Fill Holes", "fill_holes", "cleanup", mode="edit"),
    MeshEditorAction("recalculate_normals", "Recalculate Normals", "recalculate_normals", "normals", mode="edit", requires_selection=True),
    MeshEditorAction("generate_tangents", "Generate Tangents", "generate_tangents", "normals", icon_key="recalculate_normals", mode="edit", requires_selection=True),
    MeshEditorAction("flip_normals", "Flip Normals", "flip_normals", "normals", mode="edit", requires_selection=True),
    MeshEditorAction("sharpen_normals", "Sharpen Normals", "sharpen_normals", "normals", icon_key="edge_split", mode="edit", requires_selection=True),
    MeshEditorAction("soften_normals", "Soften Normals", "soften_normals", "normals", icon_key="recalculate_normals", mode="edit", requires_selection=True),
    MeshEditorAction("weighted_normals", "Weighted Normals", "weighted_normals", "normals", icon_key="recalculate_normals", mode="edit", requires_selection=True),
    MeshEditorAction("copy_normals", "Copy Normals", "copy_normals", "normals", icon_key="material_copy", mode="edit", requires_selection=True),
    MeshEditorAction("uv_transform", "Transform UV", "uv_transform", "uv", mode="edit", requires_selection=True),
    MeshEditorAction("uv_flip_u", "Flip U", "uv_transform", "uv", mode="edit", params=(("flip_u", True),), requires_selection=True),
    MeshEditorAction("uv_flip_v", "Flip V", "uv_transform", "uv", mode="edit", params=(("flip_v", True),), requires_selection=True),
    MeshEditorAction("uv_rotate_90", "Rotate UV", "uv_transform", "uv", mode="edit", params=(("rotate", 90.0), ("pivot", (0.5, 0.5))), requires_selection=True),
    MeshEditorAction("uv_island_transform", "UV Island", "uv_transform", "uv", mode="edit", params=(("uv_island", True),), requires_selection=True),
    MeshEditorAction("uv_normalize", "Normalize", "uv_transform", "uv", mode="edit", params=(("normalize", True),), requires_selection=True),
    MeshEditorAction("uv_align_u", "Align U", "uv_transform", "uv", mode="edit", params=(("align_u", "min"),), requires_selection=True),
    MeshEditorAction("uv_align_v", "Align V", "uv_transform", "uv", mode="edit", params=(("align_v", "min"),), requires_selection=True),
    MeshEditorAction("uv_planar_project", "Planar UV", "uv_transform", "uv", mode="edit", params=(("projection", "planar"), ("plane", "xy")), requires_selection=True),
    MeshEditorAction("uv_box_project", "Box UV", "uv_transform", "uv", mode="edit", params=(("projection", "box"),), requires_selection=True),
    MeshEditorAction("uv_cylindrical_project", "Cylinder UV", "uv_transform", "uv", mode="edit", params=(("projection", "cylindrical"), ("axis", "z")), requires_selection=True),
    MeshEditorAction("uv_auto_unwrap", "Auto UV", "uv_transform", "uv", mode="edit", params=(("auto_uv", True), ("allow_topology_change", True)), requires_selection=True),
    MeshEditorAction("uv_pack", "Pack UV", "uv_transform", "uv", mode="edit", params=(("pack", True),), requires_selection=True),
    MeshEditorAction("uv_snap_grid", "Snap Grid", "uv_transform", "uv", mode="edit", params=(("snap_grid", 0.125),), requires_selection=True),
    MeshEditorAction("uv_snap_pixels", "Snap Pixel", "uv_transform", "uv", mode="edit", params=(("pixel_snap", True), ("texture_size", (1024.0, 1024.0))), requires_selection=True),
    MeshEditorAction("material_assign", "Assign Material", "material_assign", "material", mode="edit", requires_selection=True),
    MeshEditorAction("material_copy", "Copy Material", "material_copy", "material", mode="edit", requires_selection=True),
    MeshEditorAction("undo", "Undo", "undo", "history"),
    MeshEditorAction("redo", "Redo", "redo", "history"),
))


def mesh_editor_actions_by_key() -> dict[str, MeshEditorAction]:
    return {action.key: action for action in MESH_EDITOR_ACTIONS}


def mesh_editor_actions_for_category(category: str) -> tuple[MeshEditorAction, ...]:
    normalized = str(category or "").strip().lower()
    return tuple(action for action in MESH_EDITOR_ACTIONS if action.category == normalized)


def validate_mesh_editor_actions() -> None:
    keys = [action.key for action in MESH_EDITOR_ACTIONS]
    if len(keys) != len(set(keys)):
        raise ValueError("Mesh Editor action keys must be unique.")
    valid_commands = set(MESH_EDIT_ACTIONS) | {"undo", "redo"}
    invalid_commands = sorted({action.command for action in MESH_EDITOR_ACTIONS if action.command not in valid_commands})
    if invalid_commands:
        raise ValueError(f"Unsupported Mesh Editor action commands: {invalid_commands!r}")
    invalid_modes = sorted({action.mode for action in MESH_EDITOR_ACTIONS if action.mode and action.mode not in MESH_EDIT_MODES})
    if invalid_modes:
        raise ValueError(f"Unsupported Mesh Editor action modes: {invalid_modes!r}")
    missing_icons = sorted(action.key for action in MESH_EDITOR_ACTIONS if not action.icon_key)
    if missing_icons:
        raise ValueError(f"Mesh Editor actions missing icon metadata: {missing_icons!r}")
    missing_tooltips = sorted(action.key for action in MESH_EDITOR_ACTIONS if not action.tooltip)
    if missing_tooltips:
        raise ValueError(f"Mesh Editor actions missing tooltip metadata: {missing_tooltips!r}")


__all__ = [
    "MESH_EDITOR_ACTIONS",
    "NATIVE_EDITOR_SESSION_COMMANDS",
    "MeshEditorAction",
    "mesh_editor_actions_by_key",
    "mesh_editor_actions_for_category",
    "validate_mesh_editor_actions",
]
