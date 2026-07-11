from __future__ import annotations

from array import array
from types import SimpleNamespace

from cdmw.modding.mesh_deformer import clone_mesh_for_editing, split_faces_to_submesh
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload import (
    _mesh_edit_i32_payload_values,
    mesh_edit_cleanup_native_vertex_group_descriptors,
    mesh_edit_all_live_vertices_for_sources,
    mesh_edit_live_vertex_update_groups,
    mesh_edit_native_live_vertex_update_groups,
    mesh_edit_payload_choice,
    mesh_edit_payload_edge_groups,
    mesh_edit_payload_float,
    mesh_edit_payload_has_drag_motion,
    mesh_edit_payload_int,
    mesh_edit_payload_native_vertex_groups,
    mesh_edit_payload_selected_indices,
    mesh_edit_payload_vector3,
    mesh_edit_payload_vertex_groups,
    mesh_edit_payload_vertex_weights,
    mesh_edit_queue_live_vertex_updates,
    mesh_edit_requested_source_indices,
    mesh_edit_stroke_id,
    mesh_edit_triangle_replace_groups,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_state import (
    mesh_edit_action_control_text,
    mesh_edit_all_vertices_by_source,
    mesh_edit_blocked_title,
    mesh_edit_can_edit_scope,
    mesh_edit_control_status_text,
    mesh_edit_deleted_faces_status,
    mesh_edit_deleted_selection_status,
    mesh_edit_delete_faces_text,
    mesh_edit_distance_or_zero,
    mesh_edit_dialog_title,
    mesh_edit_has_index_groups,
    mesh_edit_has_inverse_transform_context,
    mesh_edit_index_group_count,
    mesh_edit_index_groups_as_sets,
    mesh_edit_inverted_vertex_selection,
    mesh_edit_mapping_keys,
    mesh_edit_merge_index_groups,
    mesh_edit_live_delete_status,
    mesh_edit_optional_sorted_indices,
    mesh_edit_editing_active,
    mesh_edit_editing_requested,
    mesh_edit_enabled_snapshot_items,
    mesh_edit_full_reset_source_indices,
    mesh_edit_mesh_totals,
    mesh_edit_part_enabled_snapshot,
    mesh_edit_preview_to_source_point,
    mesh_edit_preview_to_source_vector,
    mesh_edit_pruned_index_groups,
    mesh_edit_reset_available,
    mesh_edit_reset_scope_source_indices,
    mesh_edit_allowed_source_indices,
    mesh_edit_scope_mode,
    mesh_edit_selection_depth_mode,
    mesh_edit_selection_mode,
    mesh_edit_selected_vertex_points,
    mesh_edit_selection_region_default_amount,
    mesh_edit_selection_status_text,
    mesh_edit_source_has_editable_geometry,
    mesh_edit_source_index,
    mesh_edit_source_index_is_editable,
    mesh_edit_source_indices,
    mesh_edit_source_to_preview_point,
    mesh_edit_should_restore_deleted_output,
    mesh_edit_refined_selection_status,
    mesh_edit_split_selection_status,
    mesh_edit_split_text,
    mesh_edit_subdivide_text,
    mesh_edit_subdivided_selection_status,
    mesh_edit_topology_changed_status,
    mesh_edit_sorted_index_groups,
    mesh_edit_target_mode_for_tool,
    mesh_edit_tool,
    mesh_edit_topology_source_indices,
    mesh_edit_tool_context,
    mesh_edit_vector3_or_zero,
)


def _source_values(group: dict[str, object], json_key: str) -> list[int]:
    if json_key == "source_vertex_indices":
        start_key, count_key = "source_vertex_start", "source_vertex_count"
    elif json_key == "source_face_indices":
        start_key, count_key = "source_face_start", "source_face_count"
    else:
        start_key, count_key = "", ""
    if start_key:
        try:
            raw_start = group.get(start_key, -1)
            raw_count = group.get(count_key, 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            start, count = -1, 0
        if start >= 0 and count > 0:
            return list(range(start, start + count))
    return [int(value) for value in group.get(json_key, [])] if isinstance(group.get(json_key), list) else []


def test_mesh_edit_i32_payload_values_preserves_range_descriptors() -> None:
    values = _mesh_edit_i32_payload_values(
        {"source_vertex_start": 10, "source_vertex_count": 3},
        "source_vertex_indices",
        "source_vertex_indices_binary",
    )

    assert isinstance(values, range)
    assert list(values) == [10, 11, 12]


def test_mesh_edit_action_control_text_preserves_copy() -> None:
    text = mesh_edit_action_control_text()

    assert text["edit_mode"] == "Edit Mesh"
    assert "Enable viewport mesh editing" in text["edit_mode_tooltip"]
    assert "brush edits affect" in text["scope_combo_tooltip"]
    assert text["part_combo_tooltip"] == "Used only when Scope is set to Selected part only."
    assert text["initial_status"] == "Enable Edit Mesh to edit visible replacement source geometry."
    assert text["no_editable_parts"] == "No editable parts"
    assert text["scope_label"] == "Scope"
    assert text["part_label"] == "Part"
    assert text["radius_label"] == "Radius"
    assert text["strength_label"] == "Strength"
    assert text["falloff_label"] == "Falloff"
    assert text["iterations_label"] == "Iterations"
    assert text["selection_label"] == "Selection"
    assert text["depth_label"] == "Depth"
    assert text["mirror_checkbox"] == "Mirror X"
    assert text["show_vertices_checkbox"] == "Vertex dots"
    assert text["clear_selection"] == "Clear Selection"
    assert text["select_part"] == "Select Whole Part"
    assert text["invert_selection"] == "Invert Selection"
    assert text["grow_selection"] == "Grow Selection"
    assert text["shrink_selection"] == "Shrink Selection"
    assert text["smooth_selection"] == "Smooth / Feather Selection"
    assert text["subdivide_selection"] == "Subdivide Selection"
    assert text["refine_smooth_selection"] == "Refine Smooth Selection"
    assert text["split_selection"] == "Split Selection To Part"
    assert text["delete_faces"] == "Delete Selected Faces"
    assert text["undo"] == "Undo"
    assert text["redo"] == "Redo"
    assert text["reset_scope"] == "Reset Scope"
    assert text["full_reset_mesh"] == "Full Reset Mesh"
    assert "mouse-up" in text["delete_mode_tooltip"]
    assert "Smooth/Relax passes" in text["iterations_tooltip"]
    assert "Select Vertices" in text["selection_mode_tooltip"]
    assert "X-Ray" in text["selection_depth_tooltip"]
    assert "editable Mesh Editing scope" in text["select_part_tooltip"]
    assert "editable Mesh Editing scope" in text["invert_selection_tooltip"]
    assert "triangle density" in text["subdivide_selection_tooltip"]
    assert "smooth the new detail" in text["refine_smooth_selection_tooltip"]
    assert "new replacement source part" in text["split_selection_tooltip"]
    assert "Cut boundaries" in text["delete_faces_tooltip"]


def test_mesh_edit_prompt_and_status_text_preserves_copy() -> None:
    assert mesh_edit_dialog_title() == "Mesh Editing"
    assert mesh_edit_blocked_title() == "Mesh Edit Blocked"

    delete_text = mesh_edit_delete_faces_text()
    assert delete_text["morph_blocker"] == "Bake or reset Morph Sliders before removing faces."
    assert delete_text["select_faces"] == "Select faces or vertices before deleting faces."
    assert delete_text["no_brush_faces"] == "No faces touched the Mesh Editing brush."
    assert delete_text["no_selected_vertices"] == "No faces touched the selected Mesh Editing vertices."
    assert mesh_edit_live_delete_status(0) == "Finished Mesh Editing cut."
    assert mesh_edit_live_delete_status(12) == "Deleted 12 face(s) with Mesh Editing."
    assert mesh_edit_deleted_faces_status(1200) == "Deleted 1,200 face(s) with Mesh Editing."
    assert mesh_edit_deleted_selection_status(5) == "Deleted 5 face(s) from Mesh Editing selection."

    subdivide_text = mesh_edit_subdivide_text()
    assert subdivide_text["morph_blocker"] == "Bake or reset Morph Sliders before subdividing mesh detail."
    assert subdivide_text["select_vertices"] == "Select vertices or faces before subdividing mesh detail."
    assert subdivide_text["no_selected_vertices"] == "No faces touched the selected Mesh Editing elements."
    assert mesh_edit_subdivided_selection_status(9) == "Subdivided 9 new face(s) for Mesh Editing detail."
    assert mesh_edit_refined_selection_status(9) == "Refined and smoothed 9 new face(s) for Mesh Editing detail."
    split_text = mesh_edit_split_text()
    assert split_text["morph_blocker"] == "Bake or reset Morph Sliders before splitting mesh faces."
    assert split_text["select_faces"] == "Select faces or vertices before splitting mesh faces."
    assert split_text["no_selected_faces"] == "No faces are selected for splitting."
    assert "one source part" in split_text["multiple_parts"]
    assert mesh_edit_split_selection_status(4) == "Split 4 face(s) into a new replacement source part."
    assert mesh_edit_topology_changed_status("remove_faces") == (
        "Remove Faces changed topology. Use Reset Scope to restore Morph Slider compatibility."
    )
    assert mesh_edit_topology_changed_status("subdivide_selection") == (
        "Subdivide Selection changed topology. Use Reset Scope to restore Morph Slider compatibility."
    )
    assert mesh_edit_topology_changed_status("refine_smooth_selection") == (
        "Refine Smooth Selection changed topology. Use Reset Scope to restore Morph Slider compatibility."
    )
    assert mesh_edit_topology_changed_status("split_selection") == (
        "Split Selection changed topology. Use Reset Scope to restore Morph Slider compatibility."
    )
    assert mesh_edit_topology_changed_status("unknown") == ""


def test_mesh_edit_stroke_id_normalizes_payload() -> None:
    assert mesh_edit_stroke_id({"stroke_id": "7"}) == 7
    assert mesh_edit_stroke_id({"stroke_id": "bad"}) == 0
    assert mesh_edit_stroke_id(object()) == 0


def test_mesh_edit_payload_keeps_state_helper_compatibility_exports() -> None:
    from cdmw.ui.archive_browser import static_replacement_mesh_edit_payload as payload

    assert payload.mesh_edit_scope_mode("selected") == "selected"
    assert payload.mesh_edit_index_group_count({0: [1, 2, 2]}) == 2


def test_mesh_edit_payload_has_drag_motion_uses_three_component_delta() -> None:
    assert mesh_edit_payload_has_drag_motion({"delta": (0.0, 0.0, 2e-10)}) is True
    assert mesh_edit_payload_has_drag_motion({"delta": (0.0, 0.0, 0.0)}) is False
    assert mesh_edit_payload_has_drag_motion({"delta": ("bad",)}) is False


def test_mesh_edit_payload_choice_normalizes_allowed_values() -> None:
    assert mesh_edit_payload_choice({"tool": " Smooth "}, "tool", "grab", {"grab", "smooth"}) == "smooth"
    assert mesh_edit_payload_choice({"tool": "bad"}, "tool", "grab", {"grab", "smooth"}) == "grab"
    assert mesh_edit_payload_choice({}, "delete_mode", "Release", {"release", "live"}) == "release"


def test_mesh_edit_mode_and_tool_helpers_normalize_combo_values() -> None:
    assert mesh_edit_scope_mode("selected") == "selected"
    assert mesh_edit_scope_mode("bad") == "all"
    assert mesh_edit_tool(" smooth ") == "smooth"
    assert mesh_edit_tool("bad") == "grab"
    assert mesh_edit_target_mode_for_tool("vertex") == "vertex"
    assert mesh_edit_target_mode_for_tool("grab") == "brush"
    assert mesh_edit_selection_mode("rectangle") == "rectangle"
    assert mesh_edit_selection_mode("bad") == "brush"
    assert mesh_edit_selection_depth_mode("xray") == "xray"
    assert mesh_edit_selection_depth_mode("bad") == "visible"


def test_mesh_edit_source_index_helpers_filter_marker_disabled_and_scope() -> None:
    sources = [
        SimpleNamespace(vertices=[0], faces=[0], marker=False),
        SimpleNamespace(vertices=[], faces=[0], marker=False),
        SimpleNamespace(vertices=[0], faces=[0], marker=True),
        SimpleNamespace(vertices=[0], faces=[0], marker=False),
    ]
    mesh = SimpleNamespace(submeshes=sources)

    def is_marker_source(source: object) -> bool:
        return bool(getattr(source, "marker", False))

    def is_enabled_renderable(source_index: int) -> bool:
        return source_index != 3

    assert mesh_edit_source_index("2") == 2
    assert mesh_edit_source_index("bad", fallback=4) == 4
    assert mesh_edit_source_has_editable_geometry(sources[0], is_marker_source=is_marker_source)
    assert not mesh_edit_source_has_editable_geometry(sources[1], is_marker_source=is_marker_source)
    assert not mesh_edit_source_has_editable_geometry(sources[2], is_marker_source=is_marker_source)
    assert mesh_edit_source_index_is_editable(
        mesh,
        0,
        is_marker_source=is_marker_source,
        is_enabled_renderable=is_enabled_renderable,
    )
    assert not mesh_edit_source_index_is_editable(
        mesh,
        3,
        is_marker_source=is_marker_source,
        is_enabled_renderable=is_enabled_renderable,
    )
    assert mesh_edit_source_indices(
        mesh,
        lambda source_index: mesh_edit_source_index_is_editable(
            mesh,
            source_index,
            is_marker_source=is_marker_source,
            is_enabled_renderable=None,
        ),
    ) == (0, 3)
    assert mesh_edit_allowed_source_indices(
        mesh,
        scope_mode="selected",
        selected_scope_source_index=3,
        is_source_index_editable=lambda source_index: source_index == 3,
    ) == (3,)
    assert mesh_edit_allowed_source_indices(
        mesh,
        scope_mode="all",
        selected_scope_source_index=-1,
        is_source_index_editable=lambda source_index: source_index in {0, 3},
    ) == (0, 3)


def test_mesh_edit_reset_source_indices_respect_scope_bounds_and_base_editability() -> None:
    working_mesh = SimpleNamespace(submeshes=[object(), object(), object()])
    base_mesh = SimpleNamespace(submeshes=[object(), object(), object(), object()])

    assert mesh_edit_reset_scope_source_indices(
        working_mesh,
        base_mesh,
        scope_mode="selected",
        selected_scope_source_index="2",
        is_base_source_index_editable=lambda source_index: source_index in {0, 2},
    ) == (2,)
    assert mesh_edit_reset_scope_source_indices(
        working_mesh,
        base_mesh,
        scope_mode="selected",
        selected_scope_source_index="3",
        is_base_source_index_editable=lambda source_index: True,
    ) == ()
    assert mesh_edit_reset_scope_source_indices(
        working_mesh,
        base_mesh,
        scope_mode="all",
        selected_scope_source_index=-1,
        is_base_source_index_editable=lambda source_index: source_index in {0, 2, 3},
    ) == (0, 2)
    assert mesh_edit_full_reset_source_indices(
        working_mesh,
        base_mesh,
        is_base_source_index_editable=lambda source_index: source_index != 1,
    ) == (0, 2)


def test_mesh_edit_should_restore_deleted_output_only_when_working_faces_are_empty() -> None:
    assert mesh_edit_should_restore_deleted_output(
        SimpleNamespace(faces=[]),
        SimpleNamespace(faces=[0]),
    )
    assert not mesh_edit_should_restore_deleted_output(
        SimpleNamespace(faces=[0]),
        SimpleNamespace(faces=[0]),
    )
    assert not mesh_edit_should_restore_deleted_output(
        SimpleNamespace(faces=[]),
        SimpleNamespace(faces=[]),
    )


def test_mesh_edit_coordinate_conversion_helpers_use_safe_scale_and_center() -> None:
    assert mesh_edit_preview_to_source_vector((2.0, 4.0, 6.0), 2.0) == (1.0, 2.0, 3.0)
    assert mesh_edit_preview_to_source_vector((2.0, 4.0, 6.0), 0.0) == (2.0, 4.0, 6.0)
    assert mesh_edit_preview_to_source_point(
        (2.0, 4.0, 6.0),
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
    ) == (11.0, 22.0, 33.0)
    assert mesh_edit_source_to_preview_point(
        (11.0, 22.0, 33.0),
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
    ) == (2.0, 4.0, 6.0)


def test_mesh_edit_inverse_transform_input_helpers_normalize_bad_values() -> None:
    assert mesh_edit_vector3_or_zero(("1", 2, 3.5)) == (1.0, 2.0, 3.5)
    assert mesh_edit_vector3_or_zero(("bad",)) == (0.0, 0.0, 0.0)
    assert mesh_edit_distance_or_zero("4.5") == 4.5
    assert mesh_edit_distance_or_zero(object()) == 0.0
    assert mesh_edit_has_inverse_transform_context(
        original_mesh=object(),
        replacement_mesh=object(),
        source_index="0",
    )
    assert not mesh_edit_has_inverse_transform_context(
        original_mesh=None,
        replacement_mesh=object(),
        source_index="0",
    )
    assert not mesh_edit_has_inverse_transform_context(
        original_mesh=object(),
        replacement_mesh=object(),
        source_index="-1",
    )


def test_mesh_edit_mesh_totals_and_enabled_snapshot_helpers_normalize_state() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1], faces=[0], uvs=[]),
            SimpleNamespace(vertices=[0], faces=[0, 1], uvs=[0]),
        ]
    )
    adjustments = {
        1: SimpleNamespace(enabled=False),
        3: SimpleNamespace(enabled=True),
        "bad": SimpleNamespace(enabled=False),
    }

    assert mesh_edit_mesh_totals(mesh) == {"total_vertices": 3, "total_faces": 3, "has_uvs": True}
    assert mesh_edit_part_enabled_snapshot(mesh, adjustments) == {0: True, 1: False, 2: True, 3: True}
    assert mesh_edit_enabled_snapshot_items({0: True, "2": False, "bad": True}) == ((0, True), (2, False))


def test_mesh_edit_control_state_helpers_prune_selection_and_reset_availability() -> None:
    base_mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert mesh_edit_editing_requested(
        checkbox_checked=True,
        mesh_edit_supported=True,
        mesh_edit_tab_active=True,
    )
    assert not mesh_edit_editing_requested(
        checkbox_checked=True,
        mesh_edit_supported=False,
        mesh_edit_tab_active=True,
    )
    assert mesh_edit_editing_active(editing_requested=True, can_edit=True)
    assert not mesh_edit_editing_active(editing_requested=True, can_edit=False)
    assert mesh_edit_pruned_index_groups({0: {1}, 2: {3}, 9: {4}}, (0, 2)) == {0: {1}, 2: {3}}
    assert mesh_edit_reset_available(
        base_mesh,
        is_base_source_index_editable=lambda source_index: source_index == 2,
    )
    assert not mesh_edit_reset_available(
        base_mesh,
        is_base_source_index_editable=lambda _source_index: False,
    )


def test_mesh_edit_can_edit_scope_returns_existing_user_messages() -> None:
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=False,
        scope_mode="all",
        selected_scope_source_index=0,
        allowed_source_count=1,
        current_tool="grab",
        morph_slider_has_nonzero_values=False,
    ) == (False, "Mesh Editing needs a parsed static mesh source with triangle geometry.")
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=True,
        scope_mode="selected",
        selected_scope_source_index=-1,
        allowed_source_count=1,
        current_tool="grab",
        morph_slider_has_nonzero_values=False,
    ) == (False, "Choose a part or switch Scope to All editable parts.")
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=True,
        scope_mode="selected",
        selected_scope_source_index=1,
        allowed_source_count=0,
        current_tool="grab",
        morph_slider_has_nonzero_values=False,
    ) == (False, "The selected mesh-edit part is hidden, disabled, or has no editable triangles.")
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=True,
        scope_mode="all",
        selected_scope_source_index=1,
        allowed_source_count=0,
        current_tool="grab",
        morph_slider_has_nonzero_values=False,
    ) == (False, "No visible editable source parts are available.")
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=True,
        scope_mode="all",
        selected_scope_source_index=1,
        allowed_source_count=2,
        current_tool="remove",
        morph_slider_has_nonzero_values=True,
    ) == (False, "Bake or reset Morph Sliders before removing faces.")
    assert mesh_edit_can_edit_scope(
        mesh_edit_supported=True,
        scope_mode="all",
        selected_scope_source_index=1,
        allowed_source_count=2,
        current_tool="grab",
        morph_slider_has_nonzero_values=False,
    ) == (True, "Drag in the Replacement Preview to edit 2 part(s).")


def test_mesh_edit_payload_scalar_and_vector_helpers_normalize_values() -> None:
    payload = {
        "center": ("1.5", 2, 3.25),
        "bad_vector": ("bad",),
        "radius": "-4",
        "strength": "2.5",
        "smooth_iterations": "7",
    }

    assert mesh_edit_payload_vector3(payload, "center") == (1.5, 2.0, 3.25)
    assert mesh_edit_payload_vector3(payload, "bad_vector", (4.0, 5.0, 6.0)) == (4.0, 5.0, 6.0)
    assert mesh_edit_payload_float(payload, "radius", minimum=0.0) == 0.0
    assert mesh_edit_payload_float(payload, "strength", minimum=0.0, maximum=1.0) == 1.0
    assert mesh_edit_payload_int(payload, "smooth_iterations", 3) == 7
    assert mesh_edit_payload_int({"smooth_iterations": "bad"}, "smooth_iterations", 3) == 3


def test_mesh_edit_payload_vertex_weights_clamps_and_filters_by_selected_vertices() -> None:
    group = {
        "source_vertex_weights": (
            (1, "0.25"),
            (1, "0.75"),
            (2, "4.0"),
            (3, "-2.0"),
            ("bad", 1.0),
        )
    }

    assert mesh_edit_payload_vertex_weights(group, (1, 2, 3)) == {1: 0.75, 2: 1.0}


def test_mesh_edit_payload_vertex_groups_maps_editor_ids_and_filters_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1]),
            SimpleNamespace(vertices=[0, 1, 2]),
            SimpleNamespace(vertices=[0]),
        ]
    )
    payload = {
        "groups": [
            {
                "source_submesh_index": 9,
                "source_vertex_indices": (0, "2", 8),
                "source_vertex_weights": ((2, "0.4"), (8, "1.0")),
            },
            {"source_submesh_index": 2, "source_vertex_indices": (0,)},
            {"source_submesh_index": "bad", "source_vertex_indices": (0,)},
        ]
    }

    def source_indices_for_editor_id(editor_id: int) -> tuple[int, ...]:
        return (1,) if editor_id == 9 else ()

    assert mesh_edit_payload_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(1, 2),
        source_indices_for_editor_id=source_indices_for_editor_id,
    ) == [(1, [0, 2], {2: 0.4}), (2, [0], {})]


def test_mesh_edit_payload_vertex_groups_reads_source_ranges() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[0, 1, 2, 3], faces=[0, 1, 2])])
    payload = {
        "groups": [
            {
                "source_submesh_index": 0,
                "source_vertex_start": 1,
                "source_vertex_count": 3,
                "source_face_start": 1,
                "source_face_count": 2,
            }
        ]
    }

    assert mesh_edit_payload_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
    ) == [(0, [1, 2, 3], {})]
    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
        payload_index_key="source_face_indices",
        mesh_collection_attr="faces",
    ) == {0: {1, 2}}


def test_mesh_edit_payload_selected_indices_reads_selected_ranges() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[0, 1, 2, 3], faces=[0, 1, 2])])
    payload = {
        "groups": [
            {
                "source_submesh_index": 0,
                "selected_vertex_start": 1,
                "selected_vertex_count": 2,
                "selected_face_start": 0,
                "selected_face_count": 2,
            }
        ]
    }

    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
        payload_index_key="selected_vertices",
        mesh_collection_attr="vertices",
    ) == {0: {1, 2}}
    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
        payload_index_key="selected_faces",
        mesh_collection_attr="faces",
    ) == {0: {0, 1}}


def test_mesh_edit_payload_vertex_groups_reads_binary_indices_and_weights(tmp_path) -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[0, 1, 2, 3])])

    def descriptor(name: str, values: tuple[float | int, ...], *, kind: str) -> dict[str, object]:
        path = tmp_path / name
        data = array("f" if kind == "f32" else "i", values)
        with path.open("wb") as handle:
            data.tofile(handle)
        return {
            "path": str(path),
            "count": len(values),
            "components": 1,
            "type": kind,
            "delete_after": True,
        }

    payload = {
        "groups": [
            {
                "source_submesh_index": 0,
                "source_vertex_indices_binary": descriptor("vertices.bin", (0, 2, 9), kind="i32"),
                "source_vertex_weights_binary": descriptor("weights.bin", (0.25, 0.5, 1.0), kind="f32"),
                "source_vertex_weights": ((2, "0.9"),),
            }
        ]
    }

    assert mesh_edit_payload_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
    ) == [(0, [0, 2], {2: 0.9})]
    assert not (tmp_path / "vertices.bin").exists()
    assert not (tmp_path / "weights.bin").exists()

    payload = {
        "groups": [
            {
                "source_submesh_index": 0,
                "source_vertex_indices_binary": descriptor("vertices2.bin", (0, 2), kind="i32"),
                "source_vertex_weights_binary": descriptor("weights2.bin", (0.25, 0.5), kind="f32"),
            }
        ]
    }
    assert mesh_edit_payload_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (editor_id,),
    ) == [(0, [0, 2], {0: 0.25, 2: 0.5})]
    assert not (tmp_path / "vertices2.bin").exists()
    assert not (tmp_path / "weights2.bin").exists()


def test_mesh_edit_payload_native_vertex_groups_passes_descriptors_without_reading(tmp_path) -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[0, 1, 2]), SimpleNamespace(vertices=[0, 1, 2])])
    vertices_path = tmp_path / "vertices.bin"
    weights_path = tmp_path / "weights.bin"
    vertices_b_path = tmp_path / "vertices_b.bin"
    vertices_path.write_bytes(array("i", (0, 2)).tobytes())
    weights_path.write_bytes(array("f", (0.25, 1.0)).tobytes())
    vertices_b_path.write_bytes(array("i", (1,)).tobytes())
    payload = {
        "groups": [
            {
                "source_submesh_index": 7,
                "source_vertex_indices_binary": {
                    "path": str(vertices_path),
                    "count": 2,
                    "components": 1,
                    "type": "i32",
                    "delete_after": True,
                },
                "source_vertex_weights_binary": {
                    "path": str(weights_path),
                    "count": 2,
                    "components": 1,
                    "type": "f32",
                    "delete_after": True,
                },
            },
            {
                "source_submesh_index": 8,
                "source_vertex_indices_binary": {
                    "path": str(vertices_b_path),
                    "count": 1,
                    "components": 1,
                    "type": "i32",
                    "delete_after": True,
                },
            },
        ]
    }

    groups = mesh_edit_payload_native_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(0, 1),
        source_indices_for_editor_id=lambda editor_id: {7: (0,), 8: (1,)}.get(editor_id, ()),
    )

    assert groups == [
        {
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {
                "path": str(vertices_path),
                "count": 2,
                "components": 1,
                "type": "i32",
                "delete_after": True,
            },
            "source_vertex_weights_binary": {
                "path": str(weights_path),
                "count": 2,
                "components": 1,
                "type": "f32",
                "delete_after": True,
            },
        },
        {
            "source_submesh_index": 1,
            "source_vertex_indices_binary": {
                "path": str(vertices_b_path),
                "count": 1,
                "components": 1,
                "type": "i32",
                "delete_after": True,
            },
        },
    ]
    assert vertices_path.exists()
    assert weights_path.exists()
    assert vertices_b_path.exists()

    mesh_edit_cleanup_native_vertex_group_descriptors(groups)
    assert not vertices_path.exists()
    assert not weights_path.exists()
    assert not vertices_b_path.exists()


def test_mesh_edit_payload_native_vertex_groups_preserves_source_ranges() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[0, 1, 2, 3])])
    payload = {
        "groups": [
            {
                "source_submesh_index": 7,
                "source_vertex_start": 1,
                "source_vertex_count": 2,
            }
        ]
    }

    groups = mesh_edit_payload_native_vertex_groups(
        payload,
        mesh,
        allowed_source_indices=(0,),
        source_indices_for_editor_id=lambda editor_id: (0,) if editor_id == 7 else (),
    )

    assert groups == [
        {
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"start": 1, "count": 2, "components": 1, "type": "i32_range"},
        }
    ]


def test_mesh_edit_payload_selected_indices_filters_by_allowed_source_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1, 2], faces=[0]),
            SimpleNamespace(vertices=[0], faces=[0, 1, 2]),
        ]
    )
    payload = {
        "groups": [
            {"source_submesh_index": 8, "source_vertex_indices": (0, "2", 9), "source_face_indices": (0, 2, 7)},
            {"source_submesh_index": "bad", "source_vertex_indices": (0,)},
        ]
    }

    def source_indices_for_editor_id(editor_id: int) -> tuple[int, ...]:
        return (0, 1) if editor_id == 8 else ()

    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(1,),
        source_indices_for_editor_id=source_indices_for_editor_id,
        payload_index_key="source_vertex_indices",
        mesh_collection_attr="vertices",
    ) == {1: {0}}
    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(1,),
        source_indices_for_editor_id=source_indices_for_editor_id,
        payload_index_key="source_face_indices",
        mesh_collection_attr="faces",
    ) == {1: {0, 2}}


def test_mesh_edit_payload_selection_reads_binary_descriptors(tmp_path) -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1, 2, 3], faces=[0]),
            SimpleNamespace(vertices=[0, 1, 2], faces=[0, 1, 2]),
        ]
    )

    def descriptor(name: str, values: tuple[int, ...], *, components: int = 1) -> dict[str, object]:
        path = tmp_path / name
        data = array("i", values)
        with path.open("wb") as handle:
            data.tofile(handle)
        return {
            "path": str(path),
            "count": len(values) // components,
            "components": components,
            "type": "i32",
            "delete_after": True,
        }

    payload = {
        "groups": [
            {
                "source_submesh_index": 8,
                "source_vertex_indices_binary": descriptor("vertices.bin", (0, 2, 9)),
                "source_edges_binary": descriptor("edges.bin", (0, 2, 2, 2, 1, 2), components=2),
                "source_face_indices_binary": descriptor("faces.bin", (0, 2, 7)),
            }
        ]
    }

    def source_indices_for_editor_id(editor_id: int) -> tuple[int, ...]:
        return (1,) if editor_id == 8 else ()

    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(1,),
        source_indices_for_editor_id=source_indices_for_editor_id,
        payload_index_key="source_vertex_indices",
        mesh_collection_attr="vertices",
    ) == {1: {0, 2}}
    assert mesh_edit_payload_edge_groups(
        payload,
        mesh,
        allowed_source_indices=(1,),
        source_indices_for_editor_id=source_indices_for_editor_id,
    ) == {1: {(0, 2), (1, 2)}}
    assert mesh_edit_payload_selected_indices(
        payload,
        mesh,
        allowed_source_indices=(1,),
        source_indices_for_editor_id=source_indices_for_editor_id,
        payload_index_key="source_face_indices",
        mesh_collection_attr="faces",
    ) == {1: {0, 2}}
    assert not (tmp_path / "vertices.bin").exists()
    assert not (tmp_path / "edges.bin").exists()
    assert not (tmp_path / "faces.bin").exists()


def test_mesh_edit_requested_source_indices_filters_deduplicates_and_sorts() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert mesh_edit_requested_source_indices(mesh, (2, "1", 2, -1, 4, "bad")) == (1, 2)
    assert mesh_edit_requested_source_indices(None, (0,)) == ()


def test_mesh_edit_all_live_vertices_for_sources_returns_ranges_for_valid_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1]),
            SimpleNamespace(vertices=[]),
            SimpleNamespace(vertices=[0, 1, 2]),
        ]
    )

    assert mesh_edit_all_live_vertices_for_sources(mesh, (2, 0, 9, "bad")) == {
        0: range(0, 2),
        2: range(0, 3),
    }


def test_mesh_edit_all_live_vertices_native_generator_uses_all_descriptor(monkeypatch) -> None:
    from pathlib import Path

    from cdmw.modding import mesh_native_core

    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])])
    captured: dict[str, object] = {}

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-vertex-update-groups-json"
        assert timeout_seconds == 5.0
        captured["payload"] = payload
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        assert submesh_payload["changed_all_vertices"] is True
        assert "changed_vertices_binary" not in submesh_payload
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "preview_vertex_update_groups",
            "groups": [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0, 1],
                    "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                }
            ],
        }

    monkeypatch.setattr(mesh_native_core, "find_native_mesh_core_binary", lambda: Path("native.exe"))
    monkeypatch.setattr(mesh_native_core, "_ensure_native_mesh_session_submesh", lambda *_args, **_kwargs: "session-0")
    monkeypatch.setattr(mesh_native_core, "_run_native_mesh_core_job", native_job)

    groups = mesh_native_core.build_native_mesh_preview_vertex_update_groups(
        mesh,
        mesh_edit_all_live_vertices_for_sources(mesh, (0,)),
    )

    assert captured["payload"]
    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "normals": [],
            "uvs": [],
        }
    ]


def test_mesh_edit_queue_live_vertex_updates_preserves_descriptor() -> None:
    descriptor = {
        "changed_vertices_binary": {
            "path": "changed.bin",
            "count": 2,
            "components": 1,
            "type": "i32",
        }
    }
    pending: dict[int, object] = {}

    mesh_edit_queue_live_vertex_updates(pending, {0: descriptor})

    assert pending == {0: descriptor}


def test_mesh_edit_contiguous_live_vertices_native_generator_uses_range_descriptor(monkeypatch) -> None:
    from pathlib import Path

    from cdmw.modding import mesh_native_core

    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[(0.0, 0.0, 0.0)] * 4)])
    captured: dict[str, object] = {}

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-vertex-update-groups-json"
        captured["payload"] = payload
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        assert submesh_payload["changed_vertex_start"] == 1
        assert submesh_payload["changed_vertex_count"] == 2
        assert "changed_vertices_binary" not in submesh_payload
        assert "changed_all_vertices" not in submesh_payload
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "preview_vertex_update_groups",
            "groups": [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_start": 1,
                    "source_vertex_count": 2,
                    "positions": [1.0, 0.0, 0.0, 2.0, 0.0, 0.0],
                }
            ],
        }

    monkeypatch.setattr(mesh_native_core, "find_native_mesh_core_binary", lambda: Path("native.exe"))
    monkeypatch.setattr(mesh_native_core, "_ensure_native_mesh_session_submesh", lambda *_args, **_kwargs: "session-0")
    monkeypatch.setattr(mesh_native_core, "_run_native_mesh_core_job", native_job)

    groups = mesh_native_core.build_native_mesh_preview_vertex_update_groups(mesh, {0: range(1, 3)})

    assert captured["payload"]
    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 1,
            "source_vertex_count": 2,
            "positions": [1.0, 0.0, 0.0, 2.0, 0.0, 0.0],
            "normals": [],
            "uvs": [],
        }
    ]


def test_mesh_edit_sparse_live_vertices_native_generator_uses_binary_descriptor(monkeypatch) -> None:
    from pathlib import Path

    from cdmw.modding import mesh_native_core

    class NoLenIndices:
        def __iter__(self):
            return iter((2, 0, 9, -1))

    mesh = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[(0.0, 0.0, 0.0)] * 4)])
    captured: dict[str, object] = {}

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-vertex-update-groups-json"
        captured["payload"] = payload
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        assert "changed_vertices" not in submesh_payload
        assert "changed_vertex_start" not in submesh_payload
        descriptor = submesh_payload["changed_vertices_binary"]
        values = array("i")
        values.frombytes(Path(str(descriptor["path"])).read_bytes())
        assert list(values) == [2, 0]
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "preview_vertex_update_groups",
            "groups": [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices_binary": descriptor,
                    "positions": [0.0, 0.0, 0.0, 2.0, 0.0, 0.0],
                }
            ],
        }

    monkeypatch.setattr(mesh_native_core, "find_native_mesh_core_binary", lambda: Path("native.exe"))
    monkeypatch.setattr(mesh_native_core, "_ensure_native_mesh_session_submesh", lambda *_args, **_kwargs: "session-0")
    monkeypatch.setattr(mesh_native_core, "_run_native_mesh_core_job", native_job)

    groups = mesh_native_core.build_native_mesh_preview_vertex_update_groups(mesh, {0: NoLenIndices()})

    assert captured["payload"]
    assert groups[0]["source_vertex_indices_binary"]["count"] == 2


def test_mesh_edit_queue_live_vertex_updates_merges_nonnegative_vertices() -> None:
    class NoLenIndices:
        def __iter__(self):
            return iter((3, -1, "bad"))

    pending = {1: {2}}

    mesh_edit_queue_live_vertex_updates(pending, {1: NoLenIndices(), 2: ("4",)})

    assert pending == {1: {2, 3}, 2: {4}}


def test_mesh_edit_queue_live_vertex_updates_preserves_full_ranges() -> None:
    pending: dict[int, set[int] | range] = {1: {2}}

    mesh_edit_queue_live_vertex_updates(pending, {0: range(0, 4), 1: range(0, 3)})
    mesh_edit_queue_live_vertex_updates(pending, {0: (2,), 2: (5,)})

    assert pending == {0: range(0, 4), 1: range(0, 3), 2: {5}}


def test_mesh_edit_queue_live_vertex_updates_preserves_compact_ranges_until_union() -> None:
    pending: dict[int, set[int] | range] = {}

    mesh_edit_queue_live_vertex_updates(pending, {0: range(2, 5)})
    mesh_edit_queue_live_vertex_updates(pending, {0: range(2, 5)})

    assert pending == {0: range(2, 5)}

    mesh_edit_queue_live_vertex_updates(pending, {0: (6,)})

    assert pending == {0: {2, 3, 4, 6}}


def test_mesh_edit_live_vertex_update_groups_builds_positions_and_normals(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: False)
    mesh = SimpleNamespace(submeshes=[object(), object()])
    transformed = {
        1: SimpleNamespace(
            vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
            normals=[(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)],
        )
    }

    groups = mesh_edit_live_vertex_update_groups(
        mesh,
        {1: (1, 0, 1, 8), 3: (0,)},
        transformed,
        source_to_preview_point=lambda point: (point[0] + 10.0, point[1] + 20.0, point[2] + 30.0),
        include_normals=True,
        allow_python_fallback=True,
    )

    assert len(groups) == 1
    assert groups[0]["source_submesh_index"] == 1
    assert _source_values(groups[0], "source_vertex_indices") == [0, 1]
    assert "source_vertex_indices" not in groups[0]
    assert groups[0]["positions"] == [11.0, 22.0, 33.0, 14.0, 25.0, 36.0]
    assert groups[0]["normals"] == [0.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    assert native_mesh_core_fallback_counts() == {"static_preview_vertex_update": 1}
    clear_native_mesh_core_fallback_counts()


def test_large_static_preview_python_fallback_blocks_when_native_available(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: True)
    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_triangle_groups", lambda *_args, **_kwargs: None)
    mesh = SimpleNamespace(total_vertices=10_001, total_faces=1, submeshes=[object()])
    transformed = {
        0: SimpleNamespace(
            vertices=[(0.0, 0.0, 0.0)] * 10_001,
            normals=[(0.0, 0.0, 1.0)] * 10_001,
            faces=[(0, 1, 2)],
        )
    }

    live_groups = mesh_edit_live_vertex_update_groups(
        mesh,
        {0: range(0, 10_001)},
        transformed,
        source_to_preview_point=lambda point: point,
        include_normals=True,
    )
    triangle_groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        transformed,
        source_to_preview_point=lambda point: point,
    )

    assert live_groups == []
    assert triangle_groups == []
    assert native_mesh_core_fallback_counts() == {
        "static_preview_vertex_update.blocked": 1,
        "static_preview_triangle_group.blocked": 1,
    }
    clear_native_mesh_core_fallback_counts()


def test_large_static_preview_python_fallback_blocks_before_iterating_payloads(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    class NoIterSequence:
        def __init__(self, length: int) -> None:
            self.length = length

        def __len__(self) -> int:
            return self.length

        def __iter__(self):
            raise AssertionError("large Python preview fallback iterated payload")

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: True)
    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_triangle_groups", lambda *_args, **_kwargs: None)
    mesh = SimpleNamespace(total_vertices=10_001, total_faces=10_001, submeshes=[object()])
    transformed = {
        0: SimpleNamespace(
            vertices=NoIterSequence(10_001),
            normals=NoIterSequence(10_001),
            faces=NoIterSequence(10_001),
        )
    }

    live_groups = mesh_edit_live_vertex_update_groups(
        mesh,
        {0: NoIterSequence(10_001)},
        transformed,
        source_to_preview_point=lambda point: point,
        include_normals=True,
    )
    triangle_groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        transformed,
        source_to_preview_point=lambda point: point,
    )

    assert live_groups == []
    assert triangle_groups == []
    assert native_mesh_core_fallback_counts() == {
        "static_preview_vertex_update.blocked": 1,
        "static_preview_triangle_group.blocked": 1,
    }
    clear_native_mesh_core_fallback_counts()


def test_large_static_live_preview_blocks_small_changes_before_tuple_conversion(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    class NoIterSequence:
        def __len__(self) -> int:
            return 10_001

        def __iter__(self):
            raise AssertionError("large transformed vertices converted before fallback block")

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: True)
    mesh = SimpleNamespace(total_vertices=10_001, total_faces=1, submeshes=[object()])
    transformed = {0: SimpleNamespace(vertices=NoIterSequence(), normals=NoIterSequence())}

    groups = mesh_edit_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        transformed,
        source_to_preview_point=lambda point: point,
        include_normals=True,
    )

    assert groups == []
    assert native_mesh_core_fallback_counts() == {"static_preview_vertex_update.blocked": 1}
    clear_native_mesh_core_fallback_counts()


def test_large_static_live_preview_blocks_from_submesh_length_before_tuple_conversion(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    class NoIterSequence:
        def __len__(self) -> int:
            return 10_001

        def __iter__(self):
            raise AssertionError("large transformed vertices converted before fallback block")

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: True)
    mesh = SimpleNamespace(submeshes=[object()])
    transformed = {0: SimpleNamespace(vertices=NoIterSequence(), normals=NoIterSequence())}

    groups = mesh_edit_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        transformed,
        source_to_preview_point=lambda point: point,
        include_normals=True,
    )

    assert groups == []
    assert native_mesh_core_fallback_counts() == {"static_preview_vertex_update.blocked": 1}
    clear_native_mesh_core_fallback_counts()


def test_mesh_edit_native_live_vertex_update_groups_uses_source_space_payload() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0, 1],
        "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (1, 0, 1)},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        include_normals=True,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
            "position_space": "source",
            "normalization_center": [10.0, 20.0, 30.0],
            "normalization_scale": 2.0,
        }
    ]
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_forwards_binary_payloads() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
        "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
        "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0, 1)},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        include_normals=True,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "position_space": "source",
            "normalization_center": [10.0, 20.0, 30.0],
            "normalization_scale": 2.0,
        }
    ]
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_consumes_native_before_scanning_changed_ids() -> None:
    class CountOnlyIndices:
        def __len__(self) -> int:
            return 2

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("python changed-id scan")

    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32"},
        "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
        "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64"},
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: CountOnlyIndices()},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        include_normals=True,
    )

    assert groups[0]["source_vertex_indices_binary"] == {"path": "ids.bin", "count": 2, "components": 1, "type": "i32"}
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_keeps_large_ranges_compact() -> None:
    class LengthOnlyVertices:
        def __len__(self) -> int:
            return 10_001

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("large native range should not iterate Python vertices")

    submesh = SimpleNamespace(vertices=LengthOnlyVertices())
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_start": 0,
        "source_vertex_count": 10_001,
        "positions_binary": {"path": "positions.bin", "count": 10_001, "components": 3, "type": "f64"},
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: range(0, 10_001)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 10_001,
            "positions_binary": {"path": "positions.bin", "count": 10_001, "components": 3, "type": "f64"},
            "position_space": "source",
            "normalization_center": [0.0, 0.0, 0.0],
            "normalization_scale": 1.0,
        }
    ]
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_uses_affine_payload() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0, 1],
        "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    }
    mesh = SimpleNamespace(submeshes=[submesh])
    transform = [float(value) for value in range(12)]

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0, 1)},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        position_transform_by_source={0: transform},
        allow_source_space=False,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "position_space": "source_affine",
            "position_transform": transform,
        }
    ]
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_uses_normal_transform_payload() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0, 1],
        "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
    }
    mesh = SimpleNamespace(submeshes=[submesh])
    position_transform = [float(value) for value in range(12)]
    normal_transform = [1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0]

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0, 1)},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        include_normals=True,
        position_transform_by_source={0: position_transform},
        normal_transform_by_source={0: normal_transform},
        allow_source_space=False,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
            "position_space": "source_affine",
            "position_transform": position_transform,
            "normal_transform": normal_transform,
        }
    ]
    assert not hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_blocks_affine_normals_without_transform() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0],
        "positions": [1.0, 2.0, 3.0],
        "normals": [0.0, 1.0, 0.0],
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    assert mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
        include_normals=True,
        position_transform_by_source={0: [float(value) for value in range(12)]},
        allow_source_space=False,
    ) == []
    assert hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_blocks_source_space_when_required() -> None:
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0)])
    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0],
        "positions": [1.0, 2.0, 3.0],
    }
    mesh = SimpleNamespace(submeshes=[submesh])

    assert mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
        allow_source_space=False,
    ) == []
    assert hasattr(submesh, "cdmw_native_preview_vertex_update_group")


def test_mesh_edit_native_live_vertex_update_groups_uses_native_generator_before_python_pack(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0)])
    mesh = SimpleNamespace(submeshes=[submesh])
    native_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0],
        "positions": [1.0, 2.0, 3.0],
        "normals": [0.0, 0.0, 1.0],
    }

    def native_groups(mesh_arg, changed_vertices_by_submesh):
        assert mesh_arg is mesh
        assert changed_vertices_by_submesh == {0: range(0, 1)}
        return [native_group]

    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_vertex_update_groups", native_groups)

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        include_normals=True,
    )

    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0],
            "positions": [1.0, 2.0, 3.0],
            "normals": [0.0, 0.0, 1.0],
            "position_space": "source",
            "normalization_center": [10.0, 20.0, 30.0],
            "normalization_scale": 2.0,
        }
    ]


def test_mesh_edit_native_live_vertex_update_groups_forwards_full_range_to_native_generator(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    mesh = SimpleNamespace(submeshes=[submesh])
    captured: dict[str, object] = {}
    native_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_start": 0,
        "source_vertex_count": 2,
        "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
    }

    def native_groups(mesh_arg, changed_vertices_by_submesh):
        assert mesh_arg is mesh
        captured["changed"] = changed_vertices_by_submesh
        return [native_group]

    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_vertex_update_groups", native_groups)

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: range(0, 2)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
    )

    assert captured["changed"] == {0: range(0, 2)}
    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 2,
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
            "position_space": "source",
            "normalization_center": [0.0, 0.0, 0.0],
            "normalization_scale": 1.0,
        }
    ]


def test_mesh_edit_native_live_vertex_update_groups_forwards_descriptor_to_native_generator(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    descriptor = {
        "source_vertex_indices_binary": {
            "path": "changed.bin",
            "count": 2,
            "components": 1,
            "type": "i32",
        }
    }
    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    mesh = SimpleNamespace(submeshes=[submesh])
    captured: dict[str, object] = {}
    native_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices_binary": descriptor["source_vertex_indices_binary"],
        "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
    }

    def native_groups(mesh_arg, changed_vertices_by_submesh):
        assert mesh_arg is mesh
        captured["changed"] = changed_vertices_by_submesh
        return [native_group]

    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_vertex_update_groups", native_groups)

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: descriptor},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
    )

    assert captured["changed"] == {0: descriptor}
    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": descriptor["source_vertex_indices_binary"],
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
            "position_space": "source",
            "normalization_center": [0.0, 0.0, 0.0],
            "normalization_scale": 1.0,
        }
    ]


def test_mesh_edit_native_live_vertex_update_groups_retries_missing_native_payload(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0)])
    mesh = SimpleNamespace(submeshes=[submesh])
    calls: list[dict[int, object]] = []
    invalidated: list[tuple[int, ...]] = []
    native_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_start": 0,
        "source_vertex_count": 1,
        "positions_binary": {"path": "positions.bin", "count": 1, "components": 3, "type": "f64"},
    }

    def native_groups(mesh_arg, changed_vertices_by_submesh):
        assert mesh_arg is mesh
        calls.append(dict(changed_vertices_by_submesh))
        return [] if len(calls) == 1 else [native_group]

    def invalidate(mesh_arg, source_indices):
        assert mesh_arg is mesh
        invalidated.append(tuple(source_indices))

    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_vertex_update_groups", native_groups)
    monkeypatch.setattr(mesh_native_core, "invalidate_native_mesh_session_submeshes", invalidate)

    groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
    )

    assert calls == [{0: range(0, 1)}, {0: range(0, 1)}]
    assert invalidated == [(0,)]
    assert groups == [
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 1,
            "positions_binary": {"path": "positions.bin", "count": 1, "components": 3, "type": "f64"},
            "position_space": "source",
            "normalization_center": [0.0, 0.0, 0.0],
            "normalization_scale": 1.0,
        }
    ]


def test_mesh_edit_native_live_vertex_update_groups_falls_back_on_missing_native_payload(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    submesh = SimpleNamespace(vertices=[(1.0, 2.0, 3.0)])
    mesh = SimpleNamespace(submeshes=[submesh])
    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_vertex_update_groups", lambda *_args, **_kwargs: None)

    assert mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: (0,)},
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
    ) == []


def test_mesh_edit_triangle_replace_groups_builds_full_triangle_payload(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: False)
    mesh = SimpleNamespace(submeshes=[object(), object()])
    transformed = {
        1: SimpleNamespace(
            vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)],
            normals=[(0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)],
            faces=[(0, 1, 2), (2, 9, 0), ("bad", 1, 2)],
        )
    }

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (1, 8, "bad"),
        transformed,
        source_to_preview_point=lambda point: (point[0] + 1.0, point[1] + 2.0, point[2] + 3.0),
        allow_python_fallback=True,
    )

    assert len(groups) == 1
    assert groups[0]["source_submesh_index"] == 1
    assert groups[0]["material_source_submesh_index"] == 1
    assert groups[0]["material_name"] == "part_1"
    assert groups[0]["texture_name"] == ""
    assert _source_values(groups[0], "source_vertex_indices") == [0, 1, 2]
    assert _source_values(groups[0], "source_face_indices") == [0]
    assert "source_vertex_indices" not in groups[0]
    assert "source_face_indices" not in groups[0]
    assert groups[0]["positions"] == [2.0, 4.0, 6.0, 5.0, 7.0, 9.0, 8.0, 10.0, 12.0]
    assert groups[0]["indices"] == [0, 1, 2]
    assert groups[0]["normals"] == [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0]
    assert native_mesh_core_fallback_counts() == {"static_preview_triangle_group": 1}
    clear_native_mesh_core_fallback_counts()


def test_mesh_edit_triangle_replace_groups_consumes_native_source_payload() -> None:
    submesh = SimpleNamespace(
        material="body_mat",
        texture="body_d.dds",
        cdmw_native_preview_triangle_group={
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1, 2],
            "source_face_indices": [0],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
            "normals": [0.0, 0.0, 1.0] * 3,
            "uvs": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
            "indices": [0, 1, 2],
        },
    )
    submesh.preview_texture_dds_path = "body_d.dds"
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {},
        source_to_preview_point=lambda point: point,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        allow_source_space=True,
    )

    assert groups[0]["preview_backend"] == "cdmw_mesh_core"
    assert groups[0]["position_space"] == "source"
    assert groups[0]["normalization_center"] == [1.0, 2.0, 3.0]
    assert groups[0]["normalization_scale"] == 0.5
    assert groups[0]["positions"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert groups[0]["material_name"] == "body_mat"
    assert groups[0]["preview_texture_dds_path"] == "body_d.dds"
    assert not hasattr(submesh, "cdmw_native_preview_triangle_group")


def test_mesh_edit_triangle_replace_groups_uses_native_generator_before_python_pack(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    submesh = SimpleNamespace(material="body_mat", texture="body_d.dds")
    mesh = SimpleNamespace(submeshes=[submesh])
    native_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": [0, 1, 2],
        "source_face_indices": [0],
        "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        "normals": [0.0, 0.0, 1.0] * 3,
        "uvs": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
        "indices": [0, 1, 2],
    }

    def native_groups(mesh_arg, *, source_indices):
        assert mesh_arg is mesh
        assert source_indices == (0,)
        return [native_group]

    monkeypatch.setattr(mesh_native_core, "build_native_mesh_preview_triangle_groups", native_groups)

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {0: SimpleNamespace(vertices=[(9.0, 9.0, 9.0)], faces=[(0, 0, 0)])},
        source_to_preview_point=lambda _point: (_ for _ in ()).throw(AssertionError("python triangle packing")),
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        allow_source_space=True,
    )

    assert groups[0]["preview_backend"] == "cdmw_mesh_core"
    assert groups[0]["position_space"] == "source"
    assert groups[0]["positions"] == native_group["positions"]
    assert groups[0]["material_name"] == "body_mat"


def test_mesh_edit_triangle_replace_groups_consumes_native_binary_payload() -> None:
    submesh = SimpleNamespace(
        material="body_mat",
        texture="body_d.dds",
        cdmw_native_preview_triangle_group={
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "source_vertices.bin", "count": 3, "components": 1, "type": "i32", "delete_after": True},
            "source_face_indices_binary": {"path": "source_faces.bin", "count": 1, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 3, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 3, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 3, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 3, "components": 1, "type": "i32", "delete_after": True},
        },
    )
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {},
        source_to_preview_point=lambda point: point,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        allow_source_space=True,
    )

    assert groups[0]["preview_backend"] == "cdmw_mesh_core"
    assert groups[0]["position_space"] == "source"
    assert groups[0]["positions_binary"]["path"] == "positions.bin"
    assert groups[0]["indices_binary"]["path"] == "indices.bin"
    assert "positions" not in groups[0]
    assert groups[0]["material_name"] == "body_mat"
    assert not hasattr(submesh, "cdmw_native_preview_triangle_group")


def test_mesh_edit_static_preview_consumers_prefer_descriptors_before_json_ids() -> None:
    class IterationForbiddenList(list):
        def __iter__(self):  # type: ignore[override]
            raise AssertionError("descriptor-backed static preview group parsed JSON source ids")

    def descriptor(path: str, count: int, *, components: int = 1, kind: str = "i32") -> dict[str, object]:
        return {"path": path, "count": count, "components": components, "type": kind}

    submesh = SimpleNamespace(
        material="body_mat",
        texture="body_d.dds",
        vertices=[(0.0, 0.0, 0.0)] * 3,
        normals=[(0.0, 0.0, 1.0)] * 3,
        cdmw_native_preview_triangle_group={
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": IterationForbiddenList([0, 1, 2]),
            "source_face_indices": IterationForbiddenList([0]),
            "indices": IterationForbiddenList([0, 1, 2]),
            "source_vertex_indices_binary": descriptor("tri-source-vertices.bin", 3),
            "source_face_indices_binary": descriptor("tri-source-faces.bin", 1),
            "positions_binary": descriptor("tri-positions.bin", 3, components=3, kind="f64"),
            "normals_binary": descriptor("tri-normals.bin", 3, components=3, kind="f64"),
            "uvs_binary": descriptor("tri-uvs.bin", 3, components=2, kind="f64"),
            "indices_binary": descriptor("tri-indices.bin", 3),
        },
    )
    mesh = SimpleNamespace(submeshes=[submesh])

    triangle_groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {},
        source_to_preview_point=lambda point: point,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        allow_source_space=True,
    )

    assert "source_vertex_indices_binary" in triangle_groups[0]
    assert "source_face_indices_binary" in triangle_groups[0]
    assert "indices_binary" in triangle_groups[0]
    assert "source_vertex_indices" not in triangle_groups[0]
    assert "source_face_indices" not in triangle_groups[0]
    assert "indices" not in triangle_groups[0]

    submesh.cdmw_native_preview_vertex_update_group = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": 0,
        "source_vertex_indices": IterationForbiddenList([0, 1]),
        "source_vertex_indices_binary": descriptor("update-source-vertices.bin", 2),
        "positions_binary": descriptor("update-positions.bin", 2, components=3, kind="f64"),
        "normals_binary": descriptor("update-normals.bin", 2, components=3, kind="f64"),
    }
    vertex_groups = mesh_edit_native_live_vertex_update_groups(
        mesh,
        {0: {"source_vertex_indices_binary": descriptor("changed.bin", 2)}},
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        include_normals=True,
        allow_source_space=True,
    )
    assert "source_vertex_indices_binary" in vertex_groups[0]
    assert "source_vertex_indices" not in vertex_groups[0]


def test_mesh_edit_triangle_replace_groups_consumes_native_source_ranges() -> None:
    submesh = SimpleNamespace(
        material="body_mat",
        texture="body_d.dds",
        cdmw_native_preview_triangle_group={
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 8,
            "source_vertex_count": 3,
            "source_face_start": 4,
            "source_face_count": 1,
            "positions_binary": {"path": "positions.bin", "count": 3, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 3, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 3, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 3, "components": 1, "type": "i32", "delete_after": True},
        },
    )
    mesh = SimpleNamespace(submeshes=[submesh])

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {},
        source_to_preview_point=lambda point: point,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=0.5,
        allow_source_space=True,
    )

    assert groups[0]["source_vertex_start"] == 8
    assert groups[0]["source_vertex_count"] == 3
    assert groups[0]["source_face_start"] == 4
    assert groups[0]["source_face_count"] == 1
    assert "source_vertex_indices" not in groups[0]
    assert "source_vertex_indices_binary" not in groups[0]
    assert "source_face_indices" not in groups[0]
    assert "source_face_indices_binary" not in groups[0]
    assert groups[0]["positions_binary"]["path"] == "positions.bin"
    assert groups[0]["position_space"] == "source"
    assert groups[0]["material_name"] == "body_mat"
    assert not hasattr(submesh, "cdmw_native_preview_triangle_group")


def test_mesh_edit_triangle_replace_groups_consumes_native_affine_payload() -> None:
    submesh = SimpleNamespace(
        cdmw_native_preview_triangle_group={
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1, 2],
            "source_face_indices": [0],
            "positions": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
            "normals": [0.0, 0.0, 1.0] * 3,
            "uvs": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
            "indices": [0, 1, 2],
        },
    )
    mesh = SimpleNamespace(submeshes=[submesh])
    position_transform = (1.0, 0.0, 0.0, 10.0, 0.0, 1.0, 0.0, 20.0, 0.0, 0.0, 1.0, 30.0)
    normal_transform = (0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

    groups = mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        {},
        source_to_preview_point=lambda point: point,
        position_transform_by_source={0: position_transform},
        normal_transform_by_source={0: normal_transform},
    )

    assert groups[0]["position_space"] == "source_affine"
    assert groups[0]["position_transform"] == list(position_transform)
    assert groups[0]["normal_transform"] == list(normal_transform)


def test_mesh_edit_triangle_replace_groups_clears_vertex_payload_without_valid_faces(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: False)
    mesh = SimpleNamespace(submeshes=[object()])
    transformed = {
        0: SimpleNamespace(
            vertices=[(1.0, 2.0, 3.0)],
            normals=[(0.0, 0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
    }

    assert mesh_edit_triangle_replace_groups(
        mesh,
        (0,),
        transformed,
        source_to_preview_point=lambda point: point,
        allow_python_fallback=True,
    ) == [
        {
            "source_submesh_index": 0,
            "material_source_submesh_index": 0,
            "material_name": "part_0",
            "texture_name": "",
            "source_vertex_indices": [],
            "source_face_indices": [],
            "positions": [],
            "indices": [],
        }
    ]


def test_mesh_edit_split_clone_preserves_preview_texture_metadata() -> None:
    mesh = ParsedMesh(
        submeshes=[
            SubMesh(
                name="body",
                material="body_mat",
                texture="body_d.dds",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
                faces=[(0, 1, 2), (1, 3, 2)],
            )
        ]
    )
    source = mesh.submeshes[0]
    source.preview_texture_path = "body_base.png"
    source.preview_texture_dds_path = "body_base.dds"
    source.preview_material_texture_path = "body_ma.png"
    source.preview_material_texture_dds_path = "body_ma.dds"
    source.preview_alpha_mode = "mask"
    source.preview_double_sided = True
    source.preview_native_material_overrides = {"roughness": 0.4}

    split = split_faces_to_submesh(mesh, selected_faces_by_submesh={0: {0}}, recompute_normals=False)

    new_submesh = mesh.submeshes[split.new_submesh_index]
    assert getattr(new_submesh, "preview_texture_path") == "body_base.png"
    assert getattr(new_submesh, "preview_material_texture_dds_path") == "body_ma.dds"
    assert getattr(new_submesh, "preview_alpha_mode") == "mask"
    assert getattr(new_submesh, "preview_double_sided") is True
    assert getattr(new_submesh, "preview_native_material_overrides") == {"roughness": 0.4}
    assert getattr(new_submesh, "cdmw_mesh_edit_material_source_submesh_index") == 0

    cloned = clone_mesh_for_editing(mesh)
    assert getattr(cloned.submeshes[split.new_submesh_index], "preview_texture_dds_path") == "body_base.dds"
    assert getattr(cloned.submeshes[split.new_submesh_index], "cdmw_mesh_edit_material_source_submesh_index") == 0


def test_mesh_edit_merge_index_groups_merges_nonnegative_values() -> None:
    target = {1: {2}}

    mesh_edit_merge_index_groups(target, {1: {3, -1}, 2: {"4"}})

    assert target == {1: {2, 3}, 2: {4}}


def test_mesh_edit_sorted_index_groups_filters_allowed_bounds_and_nonnegative_values() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert mesh_edit_sorted_index_groups(
        {0: {2, -1, "3"}, "1": ("bad", 4), 4: {1}},
        allowed_source_indices=(0, 1, 4),
        mesh=mesh,
    ) == {0: [2, 3], 1: [4]}
    assert mesh_edit_sorted_index_groups(object()) == {}


def test_mesh_edit_optional_sorted_indices_only_accepts_sets() -> None:
    assert mesh_edit_optional_sorted_indices({3, "1", 2}) == (1, 2, 3)
    assert mesh_edit_optional_sorted_indices([1, 2]) is None


def test_mesh_edit_topology_source_indices_merges_sets_and_iterables() -> None:
    assert mesh_edit_topology_source_indices({2, "1"}, (3, -1, "bad")) == (1, 2, 3)


def test_mesh_edit_mapping_keys_normalizes_nonnegative_mapping_keys() -> None:
    assert mesh_edit_mapping_keys({2: set(), "1": set(), -1: set(), "bad": set()}) == (1, 2)
    assert mesh_edit_mapping_keys(object()) == ()


def test_mesh_edit_index_group_count_and_presence_use_normalized_groups() -> None:
    groups = {0: {1, -1, "2"}, "bad": {3}, 1: ()}

    assert mesh_edit_index_group_count(groups) == 2
    assert mesh_edit_has_index_groups(groups) is True
    assert mesh_edit_has_index_groups({}) is False


def test_mesh_edit_tool_context_sets_visibility_flags() -> None:
    assert mesh_edit_tool_context("vertex", "brush", 3, editing_active=True) == {
        "brush_selection_tool": True,
        "remove_tool": False,
        "sculpt_tool": False,
        "select_tool": True,
        "selection_active": True,
        "selection_actions_visible": True,
        "smooth_tool": False,
    }
    assert mesh_edit_tool_context("smooth", "replace", 0, editing_active=True)["smooth_tool"] is True


def test_mesh_edit_status_text_helpers_format_counts_and_revision() -> None:
    assert mesh_edit_control_status_text("Ready.", 0, 4, editing_active=False) == "Ready."
    assert mesh_edit_control_status_text("Ready.", 12, 4, editing_active=True) == (
        "Ready. Selected vertices 12. Edited revision 4."
    )
    assert mesh_edit_selection_status_text("Ready.", 12, 3, 4) == (
        "Ready. Selected vertices 12; faces 3. Edited revision 4."
    )


def test_mesh_edit_index_groups_as_sets_reuses_sorted_group_filtering() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object()])

    assert mesh_edit_index_groups_as_sets(
        {"1": (2, "0", -1), 2: (4,)},
        allowed_source_indices=(1, 2),
        mesh=mesh,
    ) == {1: {0, 2}}


def test_mesh_edit_all_vertices_by_source_returns_in_bounds_nonempty_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1]),
            SimpleNamespace(vertices=[]),
            SimpleNamespace(vertices=[0]),
        ]
    )

    assert mesh_edit_all_vertices_by_source(mesh, (2, 1, 0, 4, "bad")) == {0: range(0, 2), 2: range(0, 1)}


def test_mesh_edit_inverted_vertex_selection_subtracts_normalized_selected_vertices() -> None:
    assert mesh_edit_inverted_vertex_selection(
        {0: {0, 1, 2}, "1": {0}},
        {0: {1, "bad"}, 1: {0}},
    ) == {0: {0, 2}}


def test_mesh_edit_selected_vertex_points_and_region_amount_use_valid_selection_bounds(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core

    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: False)

    class VertexSequence:
        def __init__(self, values: list[tuple[float, float, float]]) -> None:
            self._values = values

        def __len__(self) -> int:
            return len(self._values)

        def __getitem__(self, index: int) -> tuple[float, float, float]:
            return self._values[index]

        def __iter__(self):
            raise AssertionError("selected vertex point fallback copied the whole vertex sequence")

    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=VertexSequence([(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)])),
            SimpleNamespace(vertices=[(9.0, 9.0, 9.0)]),
        ]
    )

    assert mesh_edit_selected_vertex_points(mesh, {0: {0, 1, 8}, 3: {0}}) == [
        (0.0, 0.0, 0.0),
        (3.0, 4.0, 0.0),
    ]
    assert mesh_edit_selection_region_default_amount(mesh, {0: {0, 1}}) == 0.4
    assert mesh_edit_selection_region_default_amount(mesh, {}) == 0.01


def test_mesh_edit_selection_region_default_amount_prefers_native_bounds(monkeypatch) -> None:
    from cdmw.ui.archive_browser import static_replacement_mesh_edit_state as state

    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(0.0, 0.0, 0.0), (9.0, 9.0, 9.0)]),
        ]
    )

    def native_bounds(_mesh: object, selected_vertices_by_submesh: object) -> dict[str, object]:
        assert selected_vertices_by_submesh == {0: {0, 1}}
        return {
            "operation": "selection_bounds",
            "selected_vertex_count": 2,
            "has_bounds": True,
            "bbox_min": [0.0, 0.0, 0.0],
            "bbox_max": [0.0, 3.0, 4.0],
        }

    def fail_python_scan(*_args: object, **_kwargs: object) -> list[tuple[float, float, float]]:
        raise AssertionError("python selected-vertex point scan should stay fallback-only")

    monkeypatch.setattr("cdmw.services.mesh_workflow_service.summarize_native_mesh_selection_bounds", native_bounds)
    monkeypatch.setattr(state, "mesh_edit_selected_vertex_points", fail_python_scan)

    assert state.mesh_edit_selection_region_default_amount(mesh, {0: {0, 1}}) == 0.4


def test_mesh_edit_selection_region_amount_blocks_python_point_scan_when_native_available(monkeypatch) -> None:
    from cdmw.services import mesh_workflow_service as mesh_native_core
    from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_fallback_counts
    from cdmw.ui.archive_browser import static_replacement_mesh_edit_state as state

    class NoIterSequence:
        def __len__(self) -> int:
            return 10_001

        def __iter__(self):
            raise AssertionError("large selected-vertex point fallback iterated vertices")

    clear_native_mesh_core_fallback_counts()
    monkeypatch.setattr(mesh_native_core, "native_mesh_core_available", lambda: True)
    monkeypatch.setattr(mesh_native_core, "summarize_native_mesh_selection_bounds", lambda *_args, **_kwargs: {})
    mesh = SimpleNamespace(total_vertices=2, submeshes=[SimpleNamespace(vertices=NoIterSequence())])

    assert state.mesh_edit_selection_region_default_amount(mesh, {0: (0,)}, fallback=0.25) == 0.25
    assert state.mesh_edit_selected_vertex_points(mesh, {0: (0,)}) == []
    assert native_mesh_core_fallback_counts() == {"selection.vertex_points.blocked": 2}
    clear_native_mesh_core_fallback_counts()
