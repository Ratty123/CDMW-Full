from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload import (
    mesh_edit_all_live_vertices_for_sources,
    mesh_edit_live_vertex_update_groups,
    mesh_edit_payload_choice,
    mesh_edit_payload_float,
    mesh_edit_payload_has_drag_motion,
    mesh_edit_payload_int,
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


def test_mesh_edit_action_control_text_preserves_copy() -> None:
    text = mesh_edit_action_control_text()

    assert text["edit_mode"] == "Edit Mode"
    assert "Enable Blender-like Edit Mode" in text["edit_mode_tooltip"]
    assert "brush edits affect" in text["scope_combo_tooltip"]
    assert text["part_combo_tooltip"] == "Used only when Scope is set to Selected part only."
    assert text["initial_status"] == "Enable Edit Mode to edit visible replacement source geometry."
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
    assert subdivide_text["select_vertices"] == "Select vertices before subdividing mesh detail."
    assert subdivide_text["no_selected_vertices"] == "No faces touched the selected Mesh Editing vertices."
    assert mesh_edit_subdivided_selection_status(9) == "Subdivided 9 new face(s) for Mesh Editing detail."
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


def test_mesh_edit_queue_live_vertex_updates_merges_nonnegative_vertices() -> None:
    pending = {1: {2}}

    mesh_edit_queue_live_vertex_updates(pending, {1: (3, -1, "bad"), 2: ("4",)})

    assert pending == {1: {2, 3}, 2: {4}}


def test_mesh_edit_live_vertex_update_groups_builds_positions_and_normals() -> None:
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
    )

    assert groups == [
        {
            "source_submesh_index": 1,
            "source_vertex_indices": [0, 1],
            "positions": [11.0, 22.0, 33.0, 14.0, 25.0, 36.0],
            "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        }
    ]


def test_mesh_edit_triangle_replace_groups_builds_full_triangle_payload() -> None:
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
    )

    assert groups == [
        {
            "source_submesh_index": 1,
            "source_vertex_indices": [0, 1, 2],
            "source_face_indices": [0],
            "positions": [2.0, 4.0, 6.0, 5.0, 7.0, 9.0, 8.0, 10.0, 12.0],
            "indices": [0, 1, 2],
            "normals": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
        }
    ]


def test_mesh_edit_triangle_replace_groups_clears_vertex_payload_without_valid_faces() -> None:
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
    ) == [
        {
            "source_submesh_index": 0,
            "source_vertex_indices": [],
            "source_face_indices": [],
            "positions": [],
            "indices": [],
        }
    ]


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

    assert mesh_edit_all_vertices_by_source(mesh, (2, 1, 0, 4, "bad")) == {0: {0, 1}, 2: {0}}


def test_mesh_edit_inverted_vertex_selection_subtracts_normalized_selected_vertices() -> None:
    assert mesh_edit_inverted_vertex_selection(
        {0: {0, 1, 2}, "1": {0}},
        {0: {1, "bad"}, 1: {0}},
    ) == {0: {0, 2}}


def test_mesh_edit_selected_vertex_points_and_region_amount_use_valid_selection_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]),
            SimpleNamespace(vertices=[(9.0, 9.0, 9.0)]),
        ]
    )

    assert mesh_edit_selected_vertex_points(mesh, {0: {0, 1, 8}, 3: {0}}) == [
        (0.0, 0.0, 0.0),
        (3.0, 4.0, 0.0),
    ]
    assert mesh_edit_selection_region_default_amount(mesh, {0: {0, 1}}) == 0.4
    assert mesh_edit_selection_region_default_amount(mesh, {}) == 0.01
