"""Pure mesh-edit selection, mode, and status state helpers."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, MutableMapping


def _mesh_edit_choice(raw_value: object, fallback: object, allowed_values: Iterable[object]) -> str:
    fallback_text = str(fallback).strip().lower()
    value = str(raw_value or fallback_text).strip().lower()
    allowed = {str(item).strip().lower() for item in allowed_values}
    return value if value in allowed else fallback_text


def mesh_edit_scope_mode(raw_mode: object) -> str:
    mode = str(raw_mode or "all").strip().lower()
    return "selected" if mode == "selected" else "all"


def mesh_edit_tool(raw_tool: object, fallback: object = "grab") -> str:
    return _mesh_edit_choice(raw_tool, fallback, {"grab", "smooth", "inflate", "pinch", "remove", "vertex"})


def mesh_edit_target_mode_for_tool(tool: str) -> str:
    return "vertex" if mesh_edit_tool(tool) == "vertex" else "brush"


def mesh_edit_revision_initial_state() -> dict[str, int]:
    return {"value": 0}


def source_geometry_revision_initial_state() -> dict[str, int]:
    return {"value": 0}


def mesh_edit_pending_live_normals_initial_state() -> dict[str, bool]:
    return {"include": False}


def mesh_edit_selection_mode(raw_mode: object) -> str:
    mode = str(raw_mode or "brush").strip().lower()
    return mode if mode in {"brush", "lasso", "rectangle"} else "brush"


def mesh_edit_selection_depth_mode(raw_mode: object) -> str:
    mode = str(raw_mode or "visible").strip().lower()
    return "xray" if mode == "xray" else "visible"


def mesh_edit_action_control_text() -> dict[str, str]:
    return {
        "edit_mode": "Edit Mesh",
        "edit_mode_tooltip": "Enable viewport mesh editing for visible replacement source geometry. Delete Faces can cut triangles; sculpt tools keep topology fixed.",
        "scope_combo_tooltip": "Choose whether brush edits affect every visible editable source part or only the part below.",
        "part_combo_tooltip": "Used only when Scope is set to Selected part only.",
        "initial_status": "Enable Edit Mesh to edit visible replacement source geometry.",
        "no_editable_parts": "No editable parts",
        "scope_label": "Scope",
        "part_label": "Part",
        "tool_label": "Tool",
        "remove_mode_label": "Remove Mode",
        "radius_label": "Radius",
        "strength_label": "Strength",
        "falloff_label": "Falloff",
        "iterations_label": "Iterations",
        "selection_label": "Selection",
        "depth_label": "Depth",
        "mirror_checkbox": "Mirror X",
        "show_vertices_checkbox": "Vertex dots",
        "clear_selection": "Clear Selection",
        "select_part": "Select Whole Part",
        "invert_selection": "Invert Selection",
        "grow_selection": "Grow Selection",
        "shrink_selection": "Shrink Selection",
        "smooth_selection": "Smooth / Feather Selection",
        "subdivide_selection": "Subdivide Selection",
        "split_selection": "Split Selection To Part",
        "delete_faces": "Delete Selected Faces",
        "undo": "Undo",
        "redo": "Redo",
        "reset_scope": "Reset Scope",
        "full_reset_mesh": "Full Reset Mesh",
        "delete_mode_tooltip": "Remove Faces behavior. On release makes one cut at mouse-up; During drag cuts continuously.",
        "iterations_tooltip": "Smooth/Relax passes per brush sample.",
        "selection_mode_tooltip": "Selection mode for the Select Vertices tool.",
        "selection_depth_tooltip": "Visible Only selects the front surface; X-Ray can select vertices behind it.",
        "select_part_tooltip": "Select every vertex in the current editable Mesh Editing scope.",
        "invert_selection_tooltip": "Invert the selected vertices inside the current editable Mesh Editing scope.",
        "subdivide_selection_tooltip": "Add local triangle density around selected vertices, then keep sculpting.",
        "split_selection_tooltip": "Move selected faces into a new replacement source part.",
        "delete_faces_tooltip": "Delete triangles touched by selected Mesh Editing vertices. Cut boundaries are left open.",
    }


def mesh_edit_dialog_title() -> str:
    return "Mesh Editing"


def mesh_edit_blocked_title() -> str:
    return "Mesh Edit Blocked"


def mesh_edit_delete_faces_text() -> dict[str, str]:
    return {
        "morph_blocker": "Bake or reset Morph Sliders before removing faces.",
        "select_faces": "Select faces or vertices before deleting faces.",
        "no_brush_faces": "No faces touched the Mesh Editing brush.",
        "no_selected_vertices": "No faces touched the selected Mesh Editing vertices.",
    }


def mesh_edit_subdivide_text() -> dict[str, str]:
    return {
        "morph_blocker": "Bake or reset Morph Sliders before subdividing mesh detail.",
        "select_vertices": "Select vertices before subdividing mesh detail.",
        "no_selected_vertices": "No faces touched the selected Mesh Editing vertices.",
    }


def mesh_edit_split_text() -> dict[str, str]:
    return {
        "morph_blocker": "Bake or reset Morph Sliders before splitting mesh faces.",
        "select_faces": "Select faces or vertices before splitting mesh faces.",
        "no_selected_faces": "No faces are selected for splitting.",
        "multiple_parts": "Select faces from one source part before splitting.",
    }


def mesh_edit_live_delete_status(removed_faces: int) -> str:
    removed = int(removed_faces)
    if removed:
        return f"Deleted {removed:,} face(s) with Mesh Editing."
    return "Finished Mesh Editing cut."


def mesh_edit_deleted_faces_status(removed_faces: int) -> str:
    return f"Deleted {int(removed_faces):,} face(s) with Mesh Editing."


def mesh_edit_deleted_selection_status(removed_faces: int) -> str:
    return f"Deleted {int(removed_faces):,} face(s) from Mesh Editing selection."


def mesh_edit_subdivided_selection_status(added_faces: int) -> str:
    return f"Subdivided {int(added_faces):,} new face(s) for Mesh Editing detail."


def mesh_edit_split_selection_status(moved_faces: int) -> str:
    return f"Split {int(moved_faces):,} face(s) into a new replacement source part."


def mesh_edit_topology_changed_status(action: str) -> str:
    labels = {
        "remove_faces": "Remove Faces changed topology. Use Reset Scope to restore Morph Slider compatibility.",
        "subdivide_selection": "Subdivide Selection changed topology. Use Reset Scope to restore Morph Slider compatibility.",
        "split_selection": "Split Selection changed topology. Use Reset Scope to restore Morph Slider compatibility.",
    }
    return labels.get(str(action or "").strip(), "")


def mesh_edit_source_index(raw_index: object, fallback: int = -1) -> int:
    try:
        return int(raw_index)
    except (TypeError, ValueError):
        return int(fallback)


def mesh_edit_source_has_editable_geometry(
    source: object,
    *,
    is_marker_source: Callable[[object], bool],
) -> bool:
    if is_marker_source(source):
        return False
    return bool(getattr(source, "vertices", None)) and bool(getattr(source, "faces", None))


def mesh_edit_source_index_is_editable(
    mesh: object | None,
    source_index: object,
    *,
    is_marker_source: Callable[[object], bool],
    is_enabled_renderable: Callable[[int], bool] | None = None,
) -> bool:
    if mesh is None:
        return False
    index = mesh_edit_source_index(source_index)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if index < 0 or index >= len(submeshes):
        return False
    if is_enabled_renderable is not None and not is_enabled_renderable(index):
        return False
    return mesh_edit_source_has_editable_geometry(submeshes[index], is_marker_source=is_marker_source)


def mesh_edit_source_indices(mesh: object | None, is_source_index_editable: Callable[[int], bool]) -> tuple[int, ...]:
    if mesh is None:
        return ()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    return tuple(index for index in range(len(submeshes)) if is_source_index_editable(index))


def mesh_edit_allowed_source_indices(
    mesh: object | None,
    *,
    scope_mode: object,
    selected_scope_source_index: object,
    is_source_index_editable: Callable[[int], bool],
) -> tuple[int, ...]:
    if mesh_edit_scope_mode(scope_mode) == "selected":
        source_index = mesh_edit_source_index(selected_scope_source_index)
        return (source_index,) if is_source_index_editable(source_index) else ()
    return mesh_edit_source_indices(mesh, is_source_index_editable)


def mesh_edit_reset_scope_source_indices(
    working_mesh: object | None,
    base_mesh: object | None,
    *,
    scope_mode: object,
    selected_scope_source_index: object,
    is_base_source_index_editable: Callable[[int], bool],
) -> tuple[int, ...]:
    if working_mesh is None or base_mesh is None:
        return ()
    working_count = len(tuple(getattr(working_mesh, "submeshes", ()) or ()))
    base_count = len(tuple(getattr(base_mesh, "submeshes", ()) or ()))
    if mesh_edit_scope_mode(scope_mode) == "selected":
        raw_indices = (mesh_edit_source_index(selected_scope_source_index),)
    else:
        raw_indices = tuple(range(base_count))
    indices: list[int] = []
    for raw_index in raw_indices:
        source_index = mesh_edit_source_index(raw_index)
        if 0 <= source_index < working_count and source_index < base_count and is_base_source_index_editable(source_index):
            indices.append(source_index)
    return tuple(indices)


def mesh_edit_full_reset_source_indices(
    working_mesh: object | None,
    base_mesh: object | None,
    *,
    is_base_source_index_editable: Callable[[int], bool],
) -> tuple[int, ...]:
    if working_mesh is None or base_mesh is None:
        return ()
    working_count = len(tuple(getattr(working_mesh, "submeshes", ()) or ()))
    base_count = len(tuple(getattr(base_mesh, "submeshes", ()) or ()))
    return tuple(
        source_index
        for source_index in range(base_count)
        if source_index < working_count and is_base_source_index_editable(source_index)
    )


def mesh_edit_should_restore_deleted_output(working_source: object, base_source: object) -> bool:
    return not bool(getattr(working_source, "faces", None)) and bool(getattr(base_source, "faces", None))


def mesh_edit_safe_scale(raw_scale: object) -> float:
    try:
        scale = float(raw_scale or 1.0)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    return scale if abs(scale) > 1e-8 else 1.0


def mesh_edit_preview_to_source_vector(vector: Iterable[object], raw_scale: object) -> tuple[float, float, float]:
    values = tuple(vector)
    scale = mesh_edit_safe_scale(raw_scale)
    return (float(values[0]) / scale, float(values[1]) / scale, float(values[2]) / scale)


def mesh_edit_preview_to_source_point(
    point: Iterable[object],
    *,
    normalization_center: Iterable[object],
    normalization_scale: object,
) -> tuple[float, float, float]:
    center = tuple(normalization_center or (0.0, 0.0, 0.0))
    delta = mesh_edit_preview_to_source_vector(point, normalization_scale)
    return (delta[0] + float(center[0]), delta[1] + float(center[1]), delta[2] + float(center[2]))


def mesh_edit_source_to_preview_point(
    point: Iterable[object],
    *,
    normalization_center: Iterable[object],
    normalization_scale: object,
) -> tuple[float, float, float]:
    values = tuple(point)
    center = tuple(normalization_center or (0.0, 0.0, 0.0))
    scale = mesh_edit_safe_scale(normalization_scale)
    return (
        (float(values[0]) - float(center[0])) * scale,
        (float(values[1]) - float(center[1])) * scale,
        (float(values[2]) - float(center[2])) * scale,
    )


def mesh_edit_vector3_or_zero(value: Iterable[object]) -> tuple[float, float, float]:
    try:
        values = tuple(value)
        return (float(values[0]), float(values[1]), float(values[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return (0.0, 0.0, 0.0)


def mesh_edit_distance_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def mesh_edit_has_inverse_transform_context(
    *,
    original_mesh: object | None,
    replacement_mesh: object | None,
    source_index: object,
) -> bool:
    return bool(original_mesh is not None and replacement_mesh is not None and mesh_edit_source_index(source_index) >= 0)


def mesh_edit_mesh_totals(mesh: object | None) -> dict[str, object]:
    if mesh is None:
        return {"total_vertices": 0, "total_faces": 0, "has_uvs": False}
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    return {
        "total_vertices": sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes),
        "total_faces": sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes),
        "has_uvs": any(bool(getattr(submesh, "uvs", None)) for submesh in submeshes),
    }


def mesh_edit_editing_requested(
    *,
    checkbox_checked: bool,
    mesh_edit_supported: bool,
    mesh_edit_tab_active: bool,
) -> bool:
    return bool(checkbox_checked and mesh_edit_supported and mesh_edit_tab_active)


def mesh_edit_editing_active(*, editing_requested: bool, can_edit: bool) -> bool:
    return bool(editing_requested and can_edit)


def mesh_edit_pruned_index_groups(
    groups: Mapping[int, Iterable[int]],
    allowed_source_indices: Iterable[int],
) -> dict[int, set[int]]:
    allowed = {int(index) for index in allowed_source_indices}
    return {
        int(source_index): set(indices)
        for source_index, indices in mesh_edit_index_groups_as_sets(groups).items()
        if int(source_index) in allowed
    }


def mesh_edit_reset_available(
    base_mesh: object | None,
    *,
    is_base_source_index_editable: Callable[[int], bool],
) -> bool:
    if base_mesh is None:
        return False
    source_count = len(tuple(getattr(base_mesh, "submeshes", ()) or ()))
    return any(is_base_source_index_editable(index) for index in range(source_count))


def mesh_edit_part_enabled_snapshot(
    mesh: object | None,
    source_part_adjustments: Mapping[object, object],
) -> dict[int, bool]:
    source_count = 0
    if mesh is not None:
        source_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
    valid_adjustment_indices: list[int] = []
    for raw_index in source_part_adjustments.keys():
        index = mesh_edit_source_index(raw_index)
        if index >= 0:
            valid_adjustment_indices.append(index)
    source_count = max(source_count, *(index + 1 for index in valid_adjustment_indices), 0)
    snapshot: dict[int, bool] = {}
    for source_index in range(source_count):
        adjustment = source_part_adjustments.get(source_index)
        snapshot[source_index] = True if adjustment is None else bool(getattr(adjustment, "enabled", False))
    return snapshot


def mesh_edit_enabled_snapshot_items(snapshot: Mapping[object, object]) -> tuple[tuple[int, bool], ...]:
    items: list[tuple[int, bool]] = []
    for raw_source_index, enabled in dict(snapshot or {}).items():
        source_index = mesh_edit_source_index(raw_source_index)
        if source_index >= 0:
            items.append((source_index, bool(enabled)))
    return tuple(items)


def mesh_edit_can_edit_scope(
    *,
    mesh_edit_supported: bool,
    scope_mode: str,
    selected_scope_source_index: int,
    allowed_source_count: int,
    current_tool: str,
    morph_slider_has_nonzero_values: bool,
) -> tuple[bool, str]:
    if not mesh_edit_supported:
        return False, "Mesh Editing needs a parsed static mesh source with triangle geometry."
    if mesh_edit_scope_mode(scope_mode) == "selected" and int(selected_scope_source_index) < 0:
        return False, "Choose a part or switch Scope to All editable parts."
    if int(allowed_source_count) <= 0:
        if mesh_edit_scope_mode(scope_mode) == "selected":
            return False, "The selected mesh-edit part is hidden, disabled, or has no editable triangles."
        return False, "No visible editable source parts are available."
    if mesh_edit_tool(current_tool) == "remove" and bool(morph_slider_has_nonzero_values):
        return False, "Bake or reset Morph Sliders before removing faces."
    return True, f"Drag in the Replacement Preview to edit {int(allowed_source_count):,} part(s)."


def mesh_edit_sorted_index_groups(
    groups: object,
    *,
    allowed_source_indices: Iterable[int] | None = None,
    mesh: object | None = None,
) -> dict[int, list[int]]:
    if not isinstance(groups, Mapping):
        return {}
    allowed_indices = None if allowed_source_indices is None else {int(index) for index in allowed_source_indices}
    submesh_count = None
    if mesh is not None:
        submesh_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
    normalized: dict[int, list[int]] = {}
    for raw_source_index, raw_indices in groups.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if allowed_indices is not None and source_index not in allowed_indices:
            continue
        if submesh_count is not None and not 0 <= source_index < submesh_count:
            continue
        if not raw_indices:
            continue
        indices: set[int] = set()
        for raw_index in tuple(raw_indices or ()):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indices.add(index)
        if indices:
            normalized[source_index] = sorted(indices)
    return normalized


def mesh_edit_optional_sorted_indices(values: object) -> tuple[int, ...] | None:
    if not isinstance(values, set):
        return None
    return tuple(sorted(int(index) for index in values))


def mesh_edit_topology_source_indices(*sources: object) -> tuple[int, ...]:
    indices: set[int] = set()
    for source in sources:
        if isinstance(source, set):
            iterable = source
        else:
            try:
                iterable = tuple(source or ())  # type: ignore[arg-type]
            except TypeError:
                continue
        for raw_index in iterable:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indices.add(index)
    return tuple(sorted(indices))


def mesh_edit_mapping_keys(indices_by_source: object) -> tuple[int, ...]:
    if not isinstance(indices_by_source, Mapping):
        return ()
    result: set[int] = set()
    for raw_index in indices_by_source.keys():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            result.add(index)
    return tuple(sorted(result))


def mesh_edit_index_group_count(groups: object) -> int:
    return sum(len(indices) for indices in mesh_edit_sorted_index_groups(groups).values())


def mesh_edit_has_index_groups(groups: object) -> bool:
    return mesh_edit_index_group_count(groups) > 0


def mesh_edit_tool_context(
    current_tool: str,
    selection_mode: str,
    selected_count: int,
    *,
    editing_active: bool,
) -> dict[str, bool]:
    tool = str(current_tool or "").strip().lower()
    select_tool = tool == "vertex"
    sculpt_tool = tool in {"grab", "smooth", "inflate", "pinch"}
    remove_tool = tool == "remove"
    brush_selection_tool = select_tool and str(selection_mode or "").strip().lower() == "brush"
    return {
        "brush_selection_tool": brush_selection_tool,
        "remove_tool": remove_tool,
        "sculpt_tool": sculpt_tool,
        "select_tool": select_tool,
        "selection_active": bool(editing_active and int(selected_count) > 0),
        "selection_actions_visible": bool(select_tool or int(selected_count) > 0),
        "smooth_tool": tool == "smooth",
    }


def mesh_edit_control_status_text(
    reason: str,
    selected_count: int,
    revision: int,
    *,
    editing_active: bool,
) -> str:
    if not editing_active:
        return str(reason)
    selected_text = f" Selected vertices {int(selected_count):,}." if int(selected_count) else ""
    return f"{reason}{selected_text} Edited revision {int(revision)}."


def mesh_edit_selection_status_text(
    reason: str,
    selected_vertex_count: int,
    selected_face_count: int,
    revision: int,
) -> str:
    return (
        f"{reason} Selected vertices {int(selected_vertex_count):,}; "
        f"faces {int(selected_face_count):,}. Edited revision {int(revision)}."
    )


def mesh_edit_index_groups_as_sets(
    groups: object,
    *,
    allowed_source_indices: Iterable[int] | None = None,
    mesh: object | None = None,
) -> dict[int, set[int]]:
    return {
        source_index: set(indices)
        for source_index, indices in mesh_edit_sorted_index_groups(
            groups,
            allowed_source_indices=allowed_source_indices,
            mesh=mesh,
        ).items()
    }


def mesh_edit_all_vertices_by_source(mesh: object | None, source_indices: Iterable[int]) -> dict[int, set[int]]:
    if mesh is None:
        return {}
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    selection: dict[int, set[int]] = {}
    for raw_source_index in source_indices:
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        vertex_count = len(getattr(submeshes[source_index], "vertices", ()) or ())
        if vertex_count > 0:
            selection[source_index] = set(range(vertex_count))
    return selection


def mesh_edit_inverted_vertex_selection(
    all_vertices_by_source: Mapping[int, Iterable[int]],
    selected_vertices_by_source: Mapping[int, Iterable[int]],
) -> dict[int, set[int]]:
    inverted: dict[int, set[int]] = {}
    selected_normalized = mesh_edit_index_groups_as_sets(selected_vertices_by_source)
    for raw_source_index, raw_vertices in all_vertices_by_source.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        vertices: set[int] = set()
        for raw_vertex_index in tuple(raw_vertices or ()):
            try:
                vertex_index = int(raw_vertex_index)
            except (TypeError, ValueError):
                continue
            if vertex_index >= 0:
                vertices.add(vertex_index)
        inverted_vertices = vertices - selected_normalized.get(source_index, set())
        if inverted_vertices:
            inverted[source_index] = inverted_vertices
    return inverted


def mesh_edit_selected_vertex_points(
    mesh: object | None,
    selected_vertices_by_source: Mapping[int, Iterable[int]],
) -> list[tuple[float, float, float]]:
    if mesh is None:
        return []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    points: list[tuple[float, float, float]] = []
    for source_index, vertices in mesh_edit_sorted_index_groups(selected_vertices_by_source, mesh=mesh).items():
        submesh = submeshes[source_index]
        submesh_vertices = tuple(getattr(submesh, "vertices", ()) or ())
        for vertex_index in vertices:
            if vertex_index < len(submesh_vertices):
                vertex = submesh_vertices[vertex_index]
                points.append((float(vertex[0]), float(vertex[1]), float(vertex[2])))
    return points


def mesh_edit_selection_region_default_amount(
    mesh: object | None,
    selected_vertices_by_source: Mapping[int, Iterable[int]],
    *,
    fallback: float = 0.01,
) -> float:
    points = mesh_edit_selected_vertex_points(mesh, selected_vertices_by_source)
    if not points:
        return float(fallback)
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    min_z = min(point[2] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    max_z = max(point[2] for point in points)
    diagonal = math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2)
    return max(0.001, diagonal * 0.08)


def mesh_edit_merge_index_groups(
    target: MutableMapping[int, set[int]],
    source: Mapping[int, Iterable[int]],
) -> None:
    for source_index, indices in source.items():
        target.setdefault(int(source_index), set()).update(int(index) for index in indices if int(index) >= 0)


__all__ = [
    "mesh_edit_action_control_text",
    "mesh_edit_all_vertices_by_source",
    "mesh_edit_blocked_title",
    "mesh_edit_can_edit_scope",
    "mesh_edit_control_status_text",
    "mesh_edit_deleted_faces_status",
    "mesh_edit_deleted_selection_status",
    "mesh_edit_delete_faces_text",
    "mesh_edit_dialog_title",
    "mesh_edit_has_index_groups",
    "mesh_edit_index_group_count",
    "mesh_edit_index_groups_as_sets",
    "mesh_edit_inverted_vertex_selection",
    "mesh_edit_mapping_keys",
    "mesh_edit_merge_index_groups",
    "mesh_edit_live_delete_status",
    "mesh_edit_optional_sorted_indices",
    "mesh_edit_enabled_snapshot_items",
    "mesh_edit_editing_active",
    "mesh_edit_editing_requested",
    "mesh_edit_full_reset_source_indices",
    "mesh_edit_mesh_totals",
    "mesh_edit_part_enabled_snapshot",
    "mesh_edit_pending_live_normals_initial_state",
    "mesh_edit_pruned_index_groups",
    "mesh_edit_reset_scope_source_indices",
    "mesh_edit_reset_available",
    "mesh_edit_preview_to_source_point",
    "mesh_edit_preview_to_source_vector",
    "mesh_edit_revision_initial_state",
    "mesh_edit_scope_mode",
    "mesh_edit_selection_depth_mode",
    "mesh_edit_selection_mode",
    "mesh_edit_selected_vertex_points",
    "mesh_edit_selection_region_default_amount",
    "mesh_edit_selection_status_text",
    "mesh_edit_allowed_source_indices",
    "mesh_edit_distance_or_zero",
    "mesh_edit_source_has_editable_geometry",
    "mesh_edit_source_index",
    "mesh_edit_source_index_is_editable",
    "mesh_edit_source_indices",
    "mesh_edit_source_to_preview_point",
    "source_geometry_revision_initial_state",
    "mesh_edit_should_restore_deleted_output",
    "mesh_edit_subdivide_text",
    "mesh_edit_subdivided_selection_status",
    "mesh_edit_split_selection_status",
    "mesh_edit_split_text",
    "mesh_edit_topology_changed_status",
    "mesh_edit_has_inverse_transform_context",
    "mesh_edit_sorted_index_groups",
    "mesh_edit_target_mode_for_tool",
    "mesh_edit_tool",
    "mesh_edit_tool_context",
    "mesh_edit_topology_source_indices",
    "mesh_edit_vector3_or_zero",
]
