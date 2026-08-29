"""Mesh editor action descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MESH_EDIT_MODES
from cdmw.domain.mesh.authoring_capability import (
    FREE_EDIT_PROVEN_ACTIONS,
    MeshOutputPolicy,
    PROVEN_AUTHORING_LOD,
    action_authoring_capability,
    output_policy_state,
)

_NON_NATIVE_EDITOR_SESSION_COMMANDS = frozenset(
    {"set_mode", "select", "triangulate_display", "quadrangulate_display"}
)
NATIVE_EDITOR_SESSION_COMMANDS = frozenset(MESH_EDIT_ACTIONS) - _NON_NATIVE_EDITOR_SESSION_COMMANDS

LEGACY_PART_SELECTION_ACTION_KEYS = frozenset(
    {"select_vertex", "select_edge", "select_face"}
)
#: Topology actions with no exact-writer route, kept off the rail rather than
#: shown greyed out. That was asked as a product question and answered: eleven
#: permanently disabled buttons cost the reader more attention than they return,
#: since none of them becomes available by anything the reader can do. The
#: reasons still exist and are still tested -- `action_authoring_capability`
#: answers for every key here -- so a future decision to surface them needs new
#: strings and a rail change, not new analysis.
_UNAUTHORABLE_TOPOLOGY_ACTION_KEYS = frozenset(
    {"loop_cut", "edge_split", "bridge", "extrude", "inset", "merge", "weld", "fill", "copy", "paste", "layer_delete"}
)
#: The legacy per-element select actions are hidden for an unrelated reason: the
#: single Select tool replaced them, so they are superseded rather than blocked
#: and carry no authoring limit.
_USER_HIDDEN_ACTION_KEYS = LEGACY_PART_SELECTION_ACTION_KEYS | _UNAUTHORABLE_TOPOLOGY_ACTION_KEYS
_SESSION_HIDDEN_ACTION_KEYS = LEGACY_PART_SELECTION_ACTION_KEYS
READ_ONLY_VISIBLE_ACTION_KEYS = frozenset({"select_parts"})


def mesh_editor_action_authoring_blocker(
    action_key: object,
    *,
    deletes_parts: bool = False,
    mesh_format: object = "pac",
    lod_index: int = PROVEN_AUTHORING_LOD,
    output_policy: MeshOutputPolicy | str = MeshOutputPolicy.EXACT_GAME_ASSET,
    free_edit_destination: object = "",
    free_edit_destination_ready: bool = False,
    native_capabilities: object | None = None,
) -> str:
    """Why a direct-authoring action cannot produce an exact Mesh Editor output."""

    key = str(action_key or "").strip().lower().replace("-", "_")
    key = {
        "duplicate_selection": "duplicate",
        "subdivide_selection": "subdivide",
        "refine": "refine_smooth",
    }.get(key, key)
    try:
        normalized_policy = MeshOutputPolicy(
            str(getattr(output_policy, "value", output_policy) or "")
        )
    except ValueError:
        normalized_policy = MeshOutputPolicy.READ_ONLY
    if (
        normalized_policy is MeshOutputPolicy.READ_ONLY
        and key in READ_ONLY_VISIBLE_ACTION_KEYS
    ):
        return ""
    if key == "toggle_visibility" and normalized_policy is not MeshOutputPolicy.EXACT_GAME_ASSET:
        return ""
    capability = action_authoring_capability(
        key,
        mesh_format=mesh_format,
        lod_index=lod_index,
        output_policy=output_policy,
        free_edit_destination_ready=free_edit_destination_ready,
        native_capabilities=native_capabilities,
    )
    if capability is not None and not capability.authorable:
        return " ".join(part for part in (capability.reason, capability.detail) if str(part).strip())
    if (
        deletes_parts
        and key == "delete"
        and normalized_policy is MeshOutputPolicy.EXACT_GAME_ASSET
    ):
        return "Deleting whole parts changes the protected PAC submesh table and has no exact writeback route."
    if key == "toggle_visibility":
        return "Part visibility editing has no stored output authority in direct authoring."
    if capability is not None:
        return ""
    state = output_policy_state(
        mesh_format,
        lod_index=lod_index,
        requested_policy=output_policy,
        output_destination=free_edit_destination,
        destination_ready=free_edit_destination_ready,
    )
    if not state.authoring_enabled:
        action = mesh_editor_actions_by_key().get(key)
        if action is not None and action.command in (
            NATIVE_EDITOR_SESSION_COMMANDS | {"set_mode", "undo", "redo"}
        ):
            return state.reason
    return ""


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
    #: Which element kind the action operates on: vertex, edge, face, or part.
    #: Deliberately not the drag gesture. The two shared the name
    #: `selection_mode` and met in one controller field, where an action that
    #: declared `edge` was normalised onto `brush` and reset a reader's Lasso.
    element_type: str = ""
    params: tuple[tuple[str, object], ...] = field(default_factory=tuple)
    requires_selection: bool = False

    @property
    def selection_mode(self) -> str:
        """The element type, under the name a Qt button property still uses."""

        return self.element_type


_SHORTCUTS = {
    "mode_object": "Ctrl+1",
    "mode_edit": "Ctrl+2",
    "mode_sculpt": "Ctrl+3",
    "select_parts": "1",
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
    "copy": "Ctrl+C",
    "paste": "Ctrl+V",
    "layer_delete": "Ctrl+Shift+Delete",
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
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
}

_TOOLTIPS = {
    "mode_object": "Object mode for whole-part editing.",
    "mode_edit": "Edit mode for element selection, transforms, UV, and topology tools.",
    "mode_sculpt": "Sculpt mode for brush-based surface edits.",
    "select_parts": "Select mesh vertices, wires, or faces in the viewport. Whole parts are selected only in Parts & Routing.",
    "transform_move": "Move selected mesh elements or explicit PARTS rows.",
    "transform_rotate": "Rotate selected mesh elements or explicit PARTS rows.",
    "transform_scale": "Scale selected mesh elements or explicit PARTS rows.",
    "brush_grab": "Grab selected vertices or the initially hit mesh region.",
    "brush_smooth": "Smooth selected vertices or the initially hit mesh region.",
    "brush_inflate": "Inflate selected vertices or the initially hit mesh region.",
    "brush_pinch": "Pinch selected vertices or the initially hit mesh region.",
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
    "copy": "Copy complete selected faces into the Mesh Editor's internal clipboard.",
    "paste": "Paste the Mesh Editor's immutable internal selection copy as one geometry layer.",
    "layer_delete": "Delete one copied geometry layer as a single history action.",
    "remove_doubles": "Merge duplicate vertices within a tiny distance threshold.",
    "delete_loose_vertices": "Delete vertices not referenced by valid faces.",
    "compact_orphans": "Compact orphan vertices and invalid face references.",
    "fix_winding": "Flip triangle winding when it disagrees with vertex normals.",
    "fill_holes": "Fill simple three- or four-edge boundary holes.",
    "refine_smooth": "Subdivide selected detail, then smooth the affected vertices for less pointy surfaces.",
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
        element_type=action.element_type,
        params=action.params,
        requires_selection=action.requires_selection,
    )


MESH_EDITOR_ACTIONS = tuple(_with_palette_metadata(action) for action in (
    MeshEditorAction("mode_object", "Object", "set_mode", "mode", mode="object"),
    MeshEditorAction("mode_edit", "Edit", "set_mode", "mode", mode="edit"),
    MeshEditorAction("mode_sculpt", "Sculpt", "set_mode", "mode", mode="sculpt"),
    # The historical key is retained for settings and dynamic callers; it now
    # arms element Select. Whole-part selection belongs only to the part lists.
    MeshEditorAction("select_parts", "Select", "select", "selection"),
    MeshEditorAction("transform_move", "Move", "transform", "transform", requires_selection=True),
    MeshEditorAction("transform_rotate", "Rotate", "transform", "transform", params=(("rotate", (0.0, 0.0, 15.0)),), requires_selection=True),
    MeshEditorAction("transform_scale", "Scale", "transform", "transform", params=(("scale", (1.1, 1.1, 1.1)),), requires_selection=True),
    MeshEditorAction("brush_grab", "Grab", "brush", "sculpt", mode="sculpt", params=(("tool", "grab"),)),
    MeshEditorAction("brush_smooth", "Smooth", "brush", "sculpt", mode="sculpt", params=(("tool", "smooth"),)),
    MeshEditorAction("brush_inflate", "Inflate", "brush", "sculpt", mode="sculpt", params=(("tool", "inflate"),)),
    MeshEditorAction("brush_pinch", "Pinch", "brush", "sculpt", mode="sculpt", params=(("tool", "pinch"),)),
    MeshEditorAction("delete", "Delete", "delete", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("dissolve", "Dissolve", "dissolve", "topology", mode="edit", requires_selection=True),
    MeshEditorAction(
        "subdivide",
        "Subdivide",
        "subdivide",
        "topology",
        mode="edit",
        params=(("max_faces_per_submesh", 200_000), ("recompute_normals", True)),
        requires_selection=True,
    ),
    MeshEditorAction(
        "refine_smooth",
        "Refine Smooth",
        "refine_smooth",
        "topology",
        mode="edit",
        params=(
            ("max_faces_per_submesh", 200_000),
            ("recompute_normals", True),
            ("smooth_iterations", 2),
            ("smooth_strength", 0.5),
        ),
        requires_selection=True,
    ),
    MeshEditorAction("split", "Split", "split", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("separate", "Separate", "separate", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("duplicate", "Duplicate", "duplicate", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("copy", "Copy", "copy", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("paste", "Paste", "paste", "topology", mode="edit"),
    MeshEditorAction("layer_delete", "Delete Layer", "layer_delete", "topology", mode="edit"),
    MeshEditorAction("mirror", "Mirror", "mirror", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("extrude", "Extrude", "extrude", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("inset", "Inset", "inset", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("loop_cut", "Loop Cut", "loop_cut", "topology", mode="edit", element_type="edge", requires_selection=True),
    MeshEditorAction("edge_split", "Edge Split", "edge_split", "topology", mode="edit", element_type="edge", requires_selection=True),
    MeshEditorAction("merge", "Merge", "merge", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("weld", "Weld", "weld", "topology", mode="edit", requires_selection=True),
    MeshEditorAction("bridge", "Bridge", "bridge", "topology", mode="edit", element_type="edge", requires_selection=True),
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
    MeshEditorAction("undo", "Undo", "undo", "history"),
    MeshEditorAction("redo", "Redo", "redo", "history"),
))

MESH_EDITOR_VISIBLE_ACTIONS = tuple(
    action for action in MESH_EDITOR_ACTIONS if action.key not in _USER_HIDDEN_ACTION_KEYS
)
MESH_EDITOR_SESSION_ACTIONS = tuple(
    action for action in MESH_EDITOR_ACTIONS if action.key not in _SESSION_HIDDEN_ACTION_KEYS
)


def visible_actions_for_session(
    mesh_format: object,
    lod_index: int,
    output_policy: MeshOutputPolicy | str,
    writer_capabilities: object | None = None,
    native_capabilities: object | None = None,
    *,
    free_edit_destination_ready: bool = False,
) -> tuple[MeshEditorAction, ...]:
    """Filter the real action registry by active output and native capability."""

    try:
        policy = MeshOutputPolicy(str(getattr(output_policy, "value", output_policy) or ""))
    except ValueError:
        policy = MeshOutputPolicy.READ_ONLY
    writer = _normalized_capability_names(writer_capabilities)
    native = _normalized_capability_names(native_capabilities)
    if policy is MeshOutputPolicy.READ_ONLY:
        return tuple(
            action for action in MESH_EDITOR_SESSION_ACTIONS
            if action.key in READ_ONLY_VISIBLE_ACTION_KEYS
        )
    if policy is MeshOutputPolicy.EXACT_GAME_ASSET:
        if writer is None:
            return tuple(MESH_EDITOR_VISIBLE_ACTIONS)
        return tuple(
            action
            for action in MESH_EDITOR_VISIBLE_ACTIONS
            if action.command in {"set_mode", "select", "undo", "redo"}
            or action.key in writer
            or action.command in writer
        )
    visible: list[MeshEditorAction] = []
    for action in MESH_EDITOR_SESSION_ACTIONS:
        if action.key in _UNAUTHORABLE_TOPOLOGY_ACTION_KEYS and action.key not in FREE_EDIT_PROVEN_ACTIONS:
            continue
        if (
            native is not None
            and action.command in NATIVE_EDITOR_SESSION_COMMANDS
            and action.key not in native
            and action.command not in native
        ):
            continue
        visible.append(action)
    return tuple(visible)


def _normalized_capability_names(values: object | None) -> set[str] | None:
    if values is None:
        return None
    try:
        return {str(value or "").strip().lower() for value in values}
    except TypeError:
        return set()


def mesh_editor_actions_by_key() -> dict[str, MeshEditorAction]:
    actions = {action.key: action for action in MESH_EDITOR_ACTIONS}
    select_parts = actions["select_parts"]
    actions.update({key: select_parts for key in LEGACY_PART_SELECTION_ACTION_KEYS})
    return actions


def mesh_editor_actions_for_category(category: str) -> tuple[MeshEditorAction, ...]:
    normalized = str(category or "").strip().lower()
    return tuple(action for action in MESH_EDITOR_ACTIONS if action.category == normalized)


def normalize_mesh_selection_shape(value: object, *, default: str = "brush") -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "select_vertex": "brush",
        "select_edge": "brush",
        "select_face": "brush",
        "vertex": "brush",
        "edge": "brush",
        "face": "brush",
        "paint": "brush",
        "box": "rectangle",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"brush", "rectangle", "lasso"} else default


def normalize_mesh_element_type(value: object, *, default: str = "vertex") -> str:
    """Which element kind a value names, never a drag gesture.

    The counterpart to `normalize_mesh_selection_shape`, and the reason the two
    are separate functions: that one folds `edge` onto `brush`, which is correct
    for a gesture field and destroys an element type. A gesture arriving here
    falls back rather than being reinterpreted, for the same reason.
    """

    normalized = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "select_vertex": "vertex",
        "select_edge": "edge",
        "select_face": "face",
        "select_part": "part",
        "select_parts": "part",
        "vertices": "vertex",
        "edges": "edge",
        "faces": "face",
        "parts": "part",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"vertex", "edge", "face", "part"} else default


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
    "MESH_EDITOR_VISIBLE_ACTIONS",
    "MESH_EDITOR_SESSION_ACTIONS",
    "LEGACY_PART_SELECTION_ACTION_KEYS",
    "NATIVE_EDITOR_SESSION_COMMANDS",
    "MeshEditorAction",
    "mesh_editor_actions_by_key",
    "visible_actions_for_session",
    "mesh_editor_actions_for_category",
    "normalize_mesh_selection_shape",
    "validate_mesh_editor_actions",
]
