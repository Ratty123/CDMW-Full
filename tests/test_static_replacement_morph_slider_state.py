from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_morph_slider_state import (
    morph_slider_add_requires_modify_original_text,
    morph_slider_add_target_route_state,
    morph_slider_add_target_action_text,
    morph_slider_activity_guard_initial_state,
    morph_slider_added_status_text,
    morph_slider_amount_prompt_text,
    morph_slider_applied_status_text,
    morph_slider_active_deltas,
    morph_slider_bake_action_text,
    morph_slider_bake_action_tooltip,
    morph_slider_bake_change_label,
    morph_slider_bake_state,
    morph_slider_baked_status_text,
    morph_slider_capture_post_edit_deltas,
    morph_slider_clamped_percent,
    morph_slider_control_state,
    morph_slider_create_action_text,
    morph_slider_create_action_tooltip,
    morph_slider_create_route_state,
    morph_slider_create_requires_modify_original_text,
    morph_slider_create_requires_selection_text,
    morph_slider_created_status_text,
    morph_slider_default_name_text,
    morph_slider_expected_vertex_counts,
    morph_slider_feather_prompt_text,
    morph_slider_has_loaded_deltas,
    morph_slider_has_nonzero_values,
    morph_slider_import_action_text,
    morph_slider_import_requires_modify_original_text,
    morph_slider_import_route_state,
    morph_slider_imported_status_text,
    morph_slider_manage_action_text,
    morph_slider_manage_action_tooltip,
    morph_slider_name_prompt_text,
    morph_slider_post_edit_deltas_need_reset,
    morph_slider_reload_action_text,
    morph_slider_reload_state,
    morph_slider_reset_action_text,
    morph_slider_reset_change_label,
    morph_slider_reset_state,
    morph_slider_reset_status_text,
    morph_slider_row_state,
    morph_slider_row_reset_action_text,
    morph_slider_row_sync_states,
    morph_slider_status_text,
    morph_slider_supported,
    morph_slider_target_mesh_file_filter,
    morph_slider_title_text,
    morph_slider_topology_blocked_initial_state,
    morph_slider_topology_changed_reason_text,
    morph_slider_unique_slider_id,
    morph_slider_value_changed,
    morph_slider_value_commit_state,
    morph_slider_value_or_default,
    morph_slider_zero_post_edit_deltas,
    morph_slider_zero_post_edit_deltas_for_sources,
)


def test_morph_slider_supported_requires_modify_original_base_and_working_mesh() -> None:
    assert morph_slider_supported(
        modify_original_clone_mode=True,
        has_base_mesh=True,
        has_working_mesh=True,
    )
    assert not morph_slider_supported(
        modify_original_clone_mode=False,
        has_base_mesh=True,
        has_working_mesh=True,
    )
    assert not morph_slider_supported(
        modify_original_clone_mode=True,
        has_base_mesh=False,
        has_working_mesh=True,
    )


def test_morph_slider_loaded_and_nonzero_values_are_normalized() -> None:
    assert morph_slider_has_loaded_deltas({"volume": object()})
    assert not morph_slider_has_loaded_deltas({})
    assert morph_slider_has_nonzero_values({"a": "0.000002", "bad": object()})
    assert not morph_slider_has_nonzero_values({"a": "0.0", "bad": object()})
    assert morph_slider_active_deltas({"first": 1, "second": 2}) == (1, 2)


def test_morph_slider_initial_states_preserve_defaults() -> None:
    assert morph_slider_topology_blocked_initial_state() == {"blocked": False, "reason": ""}
    assert morph_slider_activity_guard_initial_state() == {"active": False}


def test_morph_slider_value_helpers_preserve_clamp_and_change_thresholds() -> None:
    assert morph_slider_clamped_percent("120", "-25", "75") == 75.0
    assert morph_slider_clamped_percent("-50", "-25", "75") == -25.0
    assert morph_slider_clamped_percent("25.5", "-25", "75") == 25.5
    assert morph_slider_value_changed("1.0", "1.000002")
    assert not morph_slider_value_changed("1.0", "1.0000001")
    assert morph_slider_value_changed(object(), "1.0")


def test_morph_slider_value_or_default_and_status_message_formatting() -> None:
    assert morph_slider_value_or_default({"volume": "12.5"}, "volume", 2.0) == 12.5
    assert morph_slider_value_or_default({}, "volume", 2.0) == 2.0
    assert morph_slider_value_or_default({"volume": None}, "volume", 2.0) == 0.0
    assert morph_slider_applied_status_text("Volume", 12.345) == "Applied Morph Slider Volume: 12.35%."


def test_morph_slider_row_and_sync_state_normalizes_widget_values() -> None:
    delta = SimpleNamespace(
        slider_id="volume",
        label="Volume",
        min_percent=-25.0,
        max_percent=75.0,
        default_percent=12.5,
    )

    state = morph_slider_row_state(delta, {"volume": "33.25"})

    assert state.slider_id == "volume"
    assert state.label == "Volume"
    assert state.slider_minimum == -2500
    assert state.slider_maximum == 7500
    assert state.spin_minimum == -25.0
    assert state.spin_maximum == 75.0
    assert state.current_percent == 33.25
    assert state.reset_percent == 12.5
    assert state.reset_text == "Reset"

    row = {"slider_id": "volume", "slider": object(), "spin": object()}
    sync = morph_slider_row_sync_states((row,), {"volume": 44.4})

    assert sync[0].row is row
    assert sync[0].slider_id == "volume"
    assert sync[0].percent == 44.4
    assert sync[0].slider_value == 4440


def test_morph_slider_value_commit_state_routes_apply_and_noop_cases() -> None:
    delta = SimpleNamespace(
        slider_id="volume",
        label="Volume",
        min_percent=-25.0,
        max_percent=75.0,
    )

    blocked = morph_slider_value_commit_state(
        update_active=True,
        delta=delta,
        supported=True,
        blocked=False,
        values={},
        percent=5.0,
    )
    assert blocked.should_commit is False

    unchanged = morph_slider_value_commit_state(
        update_active=False,
        delta=delta,
        supported=True,
        blocked=False,
        values={"volume": 75.0},
        percent=120.0,
    )
    assert unchanged.should_commit is False
    assert unchanged.clamped_percent == 75.0

    changed = morph_slider_value_commit_state(
        update_active=False,
        delta=delta,
        supported=True,
        blocked=False,
        values={"volume": 0.0},
        percent=120.0,
    )
    assert changed.should_commit is True
    assert changed.slider_id == "volume"
    assert changed.clamped_percent == 75.0
    assert changed.status_text == "Applied Morph Slider Volume: 75.00%."


def test_morph_slider_action_route_reset_and_bake_state() -> None:
    assert morph_slider_import_route_state(has_base_mesh=False).message == (
        "Open Modify Original for a parsed mesh before importing sliders."
    )
    assert morph_slider_import_route_state(has_base_mesh=True).allowed is True
    assert morph_slider_add_target_route_state(has_base_mesh=False).message == (
        "Open Modify Original for a parsed mesh before adding sliders."
    )
    assert morph_slider_create_route_state(has_base_mesh=False, has_selection=True).message == (
        "Open Modify Original for a parsed mesh before creating sliders."
    )
    assert morph_slider_create_route_state(has_base_mesh=True, has_selection=False).message == (
        "Select vertices first, then create a region slider."
    )
    assert morph_slider_create_route_state(has_base_mesh=True, has_selection=True).allowed is True

    assert morph_slider_reset_state(loaded=False).should_reset is False
    assert morph_slider_reset_state(loaded=True).change_label == "Reset Morph Sliders"
    assert morph_slider_bake_state(has_working_mesh=True, loaded=True, has_nonzero_values=True).status_text == (
        "Baked Morph Sliders into the editable mesh base."
    )
    assert morph_slider_bake_state(has_working_mesh=True, loaded=True, has_nonzero_values=False).should_bake is False

    reload_state = morph_slider_reload_state(
        preserve_values=True,
        values={"volume": 12.5},
        supported=True,
        has_base_mesh=True,
    )
    assert reload_state.old_values == {"volume": 12.5}
    assert reload_state.should_load_profiles is True
    assert reload_state.should_clear_post_edit_deltas is False

    unsupported_reload = morph_slider_reload_state(
        preserve_values=True,
        values={"volume": 12.5},
        supported=False,
        has_base_mesh=True,
    )
    assert unsupported_reload.should_load_profiles is False
    assert unsupported_reload.should_clear_post_edit_deltas is True


def test_morph_slider_presentation_text_preserves_existing_user_messages() -> None:
    assert morph_slider_title_text() == "Morph Sliders"
    assert morph_slider_create_action_text() == "Create Slider From Selection"
    assert (
        morph_slider_create_action_tooltip()
        == "Save the selected vertices as a Volume Size slider for this Modify Original mesh topology."
    )
    assert morph_slider_manage_action_text() == "Manage Profiles"
    assert morph_slider_manage_action_tooltip() == "Import Body Slider Pro packs or add exact same-topology target-mesh sliders."
    assert morph_slider_import_action_text() == "Import Slider Pack"
    assert morph_slider_add_target_action_text() == "Add Slider From Target Mesh"
    assert morph_slider_target_mesh_file_filter() == "Morph Target Mesh (*.obj *.pac *.pam *.pamlod)"
    assert morph_slider_reload_action_text() == "Reload Profiles"
    assert morph_slider_reset_action_text() == "Reset Sliders"
    assert morph_slider_row_reset_action_text() == "Reset"
    assert morph_slider_reset_change_label() == "Reset Morph Sliders"
    assert morph_slider_reset_status_text() == "Reset Morph Sliders."
    assert morph_slider_bake_action_text() == "Bake Sliders"
    assert (
        morph_slider_bake_action_tooltip()
        == "Apply current slider values into the editable base mesh, then reset slider values to zero."
    )
    assert morph_slider_bake_change_label() == "Bake Morph Sliders"
    assert morph_slider_baked_status_text() == "Baked Morph Sliders into the editable mesh base."
    assert (
        morph_slider_import_requires_modify_original_text()
        == "Open Modify Original for a parsed mesh before importing sliders."
    )
    assert morph_slider_add_requires_modify_original_text() == "Open Modify Original for a parsed mesh before adding sliders."
    assert (
        morph_slider_create_requires_modify_original_text()
        == "Open Modify Original for a parsed mesh before creating sliders."
    )
    assert morph_slider_create_requires_selection_text() == "Select vertices first, then create a region slider."
    assert morph_slider_topology_changed_reason_text() == "Topology changed; reset the edited scope before using Morph Sliders."
    assert morph_slider_name_prompt_text() == "Slider name:"
    assert morph_slider_default_name_text() == "Volume Size"
    assert morph_slider_amount_prompt_text() == "100% size amount:"
    assert morph_slider_feather_prompt_text() == "Feather rings:"
    assert morph_slider_imported_status_text("Slim") == "Imported Morph Slider profile: Slim."
    assert morph_slider_added_status_text("Wide") == "Added Morph Slider profile: Wide."
    assert morph_slider_created_status_text("Volume Size") == "Created Morph Slider profile: Volume Size."


def test_morph_slider_unique_slider_id_matches_duplicate_naming() -> None:
    used = {"volume", "volume_2_2"}

    assert morph_slider_unique_slider_id("Volume", used, profile_index=1) == "Volume_2_3"
    assert morph_slider_unique_slider_id("", set(), profile_index=0) == "slider"


def test_morph_slider_zero_post_edit_deltas_match_source_vertex_shape() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1]),
            SimpleNamespace(vertices=[0]),
        ]
    )

    assert morph_slider_zero_post_edit_deltas(mesh) == [
        [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
        [(0.0, 0.0, 0.0)],
    ]
    assert morph_slider_zero_post_edit_deltas(None) == []


def test_morph_slider_capture_post_edit_deltas_compares_working_and_slider_meshes() -> None:
    working_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(2.0, 3.0, 4.0), (5.0, 6.0, 7.0)]),
            SimpleNamespace(vertices=[(10.0, 10.0, 10.0)]),
        ]
    )
    slider_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(1.0, 1.0, 1.0), (3.0, 2.0, 1.0)]),
            SimpleNamespace(vertices=[(2.0, 3.0, 4.0)]),
        ]
    )

    assert morph_slider_capture_post_edit_deltas(working_mesh, slider_mesh) == [
        [(1.0, 2.0, 3.0), (2.0, 4.0, 6.0)],
        [(8.0, 7.0, 6.0)],
    ]
    assert morph_slider_capture_post_edit_deltas(None, slider_mesh) == []


def test_morph_slider_delta_shape_helpers_detect_and_reset_mismatches() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[0, 1]),
            SimpleNamespace(vertices=[0]),
        ]
    )
    expected_counts = morph_slider_expected_vertex_counts(mesh)

    assert expected_counts == [2, 1]
    assert not morph_slider_post_edit_deltas_need_reset(
        [[(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [(3.0, 0.0, 0.0)]],
        expected_counts,
    )
    assert morph_slider_post_edit_deltas_need_reset([[(1.0, 0.0, 0.0)]], expected_counts)
    assert morph_slider_post_edit_deltas_need_reset(
        [[(1.0, 0.0, 0.0)], [(3.0, 0.0, 0.0)]],
        expected_counts,
    )


def test_morph_slider_zero_post_edit_deltas_for_sources_mutates_valid_sources_only() -> None:
    post_edit_deltas = [
        [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        [(3.0, 0.0, 0.0)],
    ]

    morph_slider_zero_post_edit_deltas_for_sources(post_edit_deltas, (1, "bad", 9))

    assert post_edit_deltas == [
        [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        [(0.0, 0.0, 0.0)],
    ]


def test_morph_slider_status_text_preserves_existing_user_messages() -> None:
    assert morph_slider_status_text(
        supported=False,
        blocked=False,
        block_reason="",
        loaded=False,
        profile_count=0,
        slider_count=0,
    ) == "Morph Sliders are available in Modify Original mode for compatible PAC/PAM/PAMLOD meshes."
    assert morph_slider_status_text(
        supported=True,
        blocked=True,
        block_reason="topology mismatch",
        loaded=True,
        profile_count=2,
        slider_count=3,
    ) == "Morph Sliders disabled: topology mismatch"
    assert morph_slider_status_text(
        supported=True,
        blocked=False,
        block_reason="",
        loaded=True,
        profile_count=2,
        slider_count=3000,
    ) == "Loaded 3,000 slider(s) from 2 compatible local profile(s)."
    assert morph_slider_status_text(
        supported=True,
        blocked=False,
        block_reason="",
        loaded=False,
        profile_count=0,
        slider_count=0,
    ) == "No compatible slider profile loaded for this Modify Original mesh."


def test_morph_slider_control_state_keeps_enablement_rules_together() -> None:
    assert morph_slider_control_state(
        supported=True,
        loaded=True,
        blocked=False,
        selected_count=3,
        has_nonzero_values=True,
    ) == {
        "group_enabled": True,
        "create_enabled": True,
        "manage_enabled": True,
        "rows_enabled": True,
        "reset_enabled": True,
        "bake_enabled": True,
    }
    assert morph_slider_control_state(
        supported=True,
        loaded=True,
        blocked=True,
        selected_count=3,
        has_nonzero_values=True,
    ) == {
        "group_enabled": True,
        "create_enabled": False,
        "manage_enabled": True,
        "rows_enabled": False,
        "reset_enabled": False,
        "bake_enabled": False,
    }
    assert morph_slider_control_state(
        supported=True,
        loaded=False,
        blocked=False,
        selected_count=0,
        has_nonzero_values=True,
    )["create_enabled"] is False
