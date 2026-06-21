from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mapping_table_state import (
    geometry_mapping_summary_html,
    invalid_submesh_mapping_missing_source_message,
    invalid_submesh_mapping_non_numeric_message,
    invalid_submesh_mapping_title,
    mapping_committed_source_cell_state,
    mapping_edit_draft_tooltip,
    mapping_edit_placeholder_text,
    mapping_edit_refresh_interval_ms,
    mapping_edit_source_cell_state,
    mapping_route_button_enabled_state,
    mapping_route_button_style,
    mapping_route_control_text,
    mapping_route_primary_button_specs,
    mapping_route_selection_button_specs,
    mapping_status_action_state,
    mapping_status_dds_color,
    mapping_status_current_target_line,
    mapping_status_physics_color,
    mapping_status_physics_state,
    mapping_status_selection_lines,
    mapping_status_summary_badge,
    mapping_status_summary_badges,
    mapping_status_summary_html,
    mapping_target_confidence_state,
    mapping_target_dds_cell_state,
    mapping_target_details_text,
    mapping_table_action_control_text,
    mapping_table_advanced_visibility_state,
    mapping_table_build_can_start,
    mapping_table_build_complete,
    mapping_table_build_initial_state,
    mapping_table_build_mark_complete,
    mapping_table_build_mark_requested_started,
    mapping_table_build_next_index,
    mapping_table_build_requested_initial_state,
    mapping_table_build_requested_started,
    mapping_table_build_start_delay_ms,
    mapping_table_chunk_row_limit,
    mapping_table_chunk_presentation_state,
    mapping_table_chunk_time_budget_seconds,
    mapping_table_column_max_widths,
    mapping_table_column_min_widths,
    mapping_table_confidence_matches_low_filter,
    mapping_table_expand_columns,
    mapping_table_filters_active,
    mapping_table_build_set_next_index,
    mapping_table_height_fit_kwargs,
    mapping_table_row_hidden_by_filters,
    mapping_table_loading_progress_text,
    mapping_table_queued_progress_text,
    mapping_table_ready_progress_text,
    mapping_table_target_row_state,
    mesh_replacement_too_large_message,
    mesh_replacement_too_large_title,
    output_impact_review_presentation,
    removed_target_dds_tooltip,
    source_assignment_state_tooltip,
    source_assignment_targets_tooltip,
    suggested_mappings_by_target,
    vertex_limit_issue_display_text,
)


def test_mapping_table_action_control_text_preserves_labels_and_tooltips() -> None:
    text = mapping_table_action_control_text()

    assert text["headers"] == ["Target", "Role", "Index", "Source", "State", "DDS", "Physics"]
    assert "target -> source -> DDS" in text["routing_hint_html"]
    assert "original game draw/material slot" in text["routing_hint_tooltip"]
    assert "Targets</span>" in text["target_slots_html"]
    assert "replace/add/remove" in text["target_slots_tooltip"]
    assert text["low_confidence_filter"] == "Show low confidence only"
    assert text["empty_targets_filter"] == "Show removed targets only"
    assert text["clear_all_guesses"] == "Clear all guesses"
    assert text["apply_best_guesses"] == "Apply best guesses"
    assert text["group_materials"] == "Group by Source Material"
    assert text["preview_target"] == "Preview selected target"
    assert "rebuild the mapping manually" in text["clear_all_guesses_tooltip"]
    assert "best-guess target-slot mapping" in text["apply_best_guesses_tooltip"]
    assert "one source material set" in text["group_materials_tooltip"]
    assert text["preview_target_tooltip"] == "Highlight the currently selected target slot in the preview."
    assert text["advanced_mapping"] == "Advanced Mapping"
    assert "Parts Outliner" in text["advanced_mapping_tooltip"]
    assert text["mapping_status_initial"] == "No target/source selected."
    assert "Preview + Transform place parts." in text["geometry_hint_html"]
    assert "original PAC draw-slot assignment" in text["geometry_hint_tooltip"]
    assert text["advanced_part_transform"] == "Advanced Part Transform"


def test_suggested_mappings_by_target_indexes_target_submesh() -> None:
    mappings = (
        SimpleNamespace(target_submesh_index=2, name="late"),
        SimpleNamespace(target_submesh_index=0, name="first"),
    )

    by_target = suggested_mappings_by_target(mappings)

    assert by_target == {2: mappings[0], 0: mappings[1]}


def test_mapping_table_target_row_state_normalizes_mapping_payload() -> None:
    target = SimpleNamespace(name="TargetName", material="TargetMaterial")
    mapping = SimpleNamespace(source_submesh_indices=(2, "3"))

    state = mapping_table_target_row_state(target_index="4", target=target, mapping=mapping)

    assert state.target_index == 4
    assert state.row_number == 5
    assert state.target_label_text == "TargetMaterial"
    assert state.target_role_source_text == "TargetName TargetMaterial"
    assert state.initial_mapping_text == "2, 3"
    assert state.initial_source_indices == (2, 3)
    assert not state.removed
    assert not state.mapping_text_empty

    removed_state = mapping_table_target_row_state(
        target_index=1,
        target=SimpleNamespace(name="", material=""),
        mapping=SimpleNamespace(source_submesh_indices=()),
    )
    assert removed_state.target_label_text == "target 1"
    assert removed_state.removed
    assert removed_state.mapping_text_empty


def test_mapping_edit_and_status_summary_helpers_preserve_presentation_copy() -> None:
    assert mapping_edit_draft_tooltip() == "Draft source indices. Press Enter or leave the field to apply."
    assert mapping_edit_placeholder_text() == "empty, 0, or 0, 1"
    assert mapping_edit_refresh_interval_ms() == 260
    assert mapping_table_chunk_row_limit() == 8
    assert mapping_table_chunk_time_budget_seconds() == 0.012
    assert mapping_table_build_start_delay_ms() == 25
    assert mapping_table_column_min_widths() == (150, 60, 118, 160, 68, 78, 64)
    assert mapping_table_column_max_widths() == (280, 120, 180, 320, 120, 140, 110)
    assert mapping_table_expand_columns() == (0, 3)
    assert mapping_table_height_fit_kwargs() == {"minimum": 96, "screen_margin": 500, "maximum": 300}

    html = mapping_status_summary_html(("<span>Source A</span>", "<span>DDS B</span>"))

    assert "font-size:8px" in html
    assert "background:#0d1117" in html
    assert "<span>Source A</span><span>DDS B</span>" in html
    badge = mapping_status_summary_badge("DDS", "Review", "#d29922")
    assert "DDS" in badge
    assert "Review" in badge
    assert "#d29922" in badge
    badges = mapping_status_summary_badges(
        source_text="source A",
        target_text="target B",
        action_text="Replace target",
        action_color="#3fb950",
        dds_text="Review",
        physics_text="Preserved",
        physics_color="#7ee787",
    )
    assert len(badges) == 5
    assert "source A" in badges[0]
    assert "target B" in badges[1]
    assert "Replace target" in badges[2]
    assert "Review" in badges[3]
    assert "Preserved" in badges[4]


def test_mapping_status_action_state_preserves_selection_rules() -> None:
    assert mapping_status_action_state(
        has_target_edit=True,
        source_index=-1,
        source_indices_for_target=(),
        preview_only_source_indices=(),
    ) == {"text": "Remove target", "color": "#d29922"}
    assert mapping_status_action_state(
        has_target_edit=True,
        source_index=-1,
        source_indices_for_target=(2,),
        preview_only_source_indices=(),
    ) == {"text": "Replace target", "color": "#3fb950"}
    assert mapping_status_action_state(
        has_target_edit=True,
        source_index=-1,
        source_indices_for_target=(2, 3),
        preview_only_source_indices=(),
    ) == {"text": "Merge sources", "color": "#d29922"}
    assert mapping_status_action_state(
        has_target_edit=False,
        source_index=4,
        source_indices_for_target=(),
        preview_only_source_indices=(4,),
    ) == {"text": "Preview-only", "color": "#d29922"}
    assert mapping_status_action_state(
        has_target_edit=False,
        source_index=4,
        source_indices_for_target=(),
        preview_only_source_indices=(),
    ) == {"text": "Source selected", "color": "#79c0ff"}
    assert mapping_status_action_state(
        has_target_edit=False,
        source_index=-1,
        source_indices_for_target=(),
        preview_only_source_indices=(),
    ) == {"text": "Select", "color": "#8b949e"}


def test_mapping_status_tooltip_lines_preserve_selection_copy() -> None:
    assert mapping_status_selection_lines("source A", "target B") == (
        "Selected source: source A",
        "Selected target: target B",
    )
    assert mapping_status_current_target_line("Selected: 1, 2", selection_ok=True) == "Current target: 1, 2"
    assert mapping_status_current_target_line("bad index", selection_ok=False) == "Current target error: bad index"


def test_mapping_status_dds_and_physics_state_preserve_color_rules() -> None:
    assert mapping_status_dds_color("Will prune") == "#d29922"
    assert mapping_status_dds_color("Review") == "#d29922"
    assert mapping_status_dds_color("-") == "#79c0ff"
    assert mapping_status_physics_color("Review") == "#f2cc60"
    assert mapping_status_physics_color("Preserved") == "#7ee787"
    assert mapping_status_physics_color("-") == "#8b949e"

    assert mapping_status_physics_state(
        target_index=1,
        source_indices_for_target=(2,),
        target_physics_text="-",
        source_physics_text="-",
    ) == {"text": "Preserved", "color": "#7ee787"}
    assert mapping_status_physics_state(
        target_index=1,
        source_indices_for_target=(2,),
        target_physics_text="Review",
        source_physics_text="-",
    ) == {"text": "Review", "color": "#f2cc60"}
    assert mapping_status_physics_state(
        target_index=1,
        source_indices_for_target=(2,),
        target_physics_text="Preserved",
        source_physics_text="Review",
    ) == {"text": "Review", "color": "#f2cc60"}
    assert mapping_status_physics_state(
        target_index=-1,
        source_indices_for_target=(),
        target_physics_text="-",
        source_physics_text="-",
    ) == {"text": "-", "color": "#8b949e"}


def test_mapping_edit_source_cell_state_tracks_empty_and_dirty_display() -> None:
    assert mapping_edit_source_cell_state("1", "1", has_source_indices=True) == {
        "is_empty": False,
        "foreground": "#cbd5e1",
    }
    assert mapping_edit_source_cell_state("1, 2", "1", has_source_indices=True) == {
        "is_empty": False,
        "foreground": "#f2cc60",
    }
    assert mapping_edit_source_cell_state("bad", "", has_source_indices=False) == {
        "is_empty": True,
        "foreground": "#f2cc60",
    }


def test_mapping_committed_source_cell_state_tracks_empty_and_invalid_display() -> None:
    assert mapping_committed_source_cell_state(selection_ok=True, has_source_indices=True) == {
        "is_empty": False,
        "foreground": "#cbd5e1",
    }
    assert mapping_committed_source_cell_state(selection_ok=False, has_source_indices=True) == {
        "is_empty": False,
        "foreground": "#fca5a5",
    }
    assert mapping_committed_source_cell_state(selection_ok=True, has_source_indices=False) == {
        "is_empty": True,
        "foreground": "#cbd5e1",
    }


def test_mapping_target_dds_cell_state_tracks_removed_and_empty_state() -> None:
    assert mapping_target_dds_cell_state(state_text="Removed", has_source_indices=False) == {
        "uses_removed_target_text": True,
        "foreground": "#fb923c",
    }
    assert mapping_target_dds_cell_state(state_text="Mapped", has_source_indices=True) == {
        "uses_removed_target_text": False,
        "foreground": "#cbd5e1",
    }


def test_mapping_target_confidence_state_preserves_row_label_and_color_rules() -> None:
    assert mapping_target_confidence_state(None) == {"text": "Manual", "color": "#94a3b8"}
    assert mapping_target_confidence_state(SimpleNamespace(source_submesh_indices=())) == {
        "text": "Remove Original Part",
        "color": "#fb923c",
    }
    assert mapping_target_confidence_state(
        SimpleNamespace(source_submesh_indices=(1,), confidence_label="high", confidence_score=0.95)
    ) == {"text": "Mapped: High (0.9)", "color": "#86efac"}
    assert mapping_target_confidence_state(
        SimpleNamespace(source_submesh_indices=(1,), confidence_label="medium", confidence_score=0.55)
    ) == {"text": "Mapped: Medium (0.6)", "color": "#facc15"}
    assert mapping_target_confidence_state(
        SimpleNamespace(source_submesh_indices=(1,), confidence_label="low", confidence_score=0.2)
    ) == {"text": "Mapped: Low (0.2)", "color": "#fb923c"}


def test_mapping_target_details_text_formats_role_geometry_counts() -> None:
    target = SimpleNamespace(vertices=(1, 2, 3), faces=(1, 2))

    assert mapping_target_details_text(4, "Body", "armor", target) == (
        "4: Body\nRole: armor\n3 vertices, 2 faces"
    )


def test_assignment_and_removed_target_tooltips_preserve_copy() -> None:
    assert source_assignment_targets_tooltip("0: target") == "0: target"
    assert source_assignment_targets_tooltip("") == "Not assigned to an original target."
    assert source_assignment_state_tooltip("Assigned") == "This replacement source feeds at least one original target."
    assert "visible for review" in source_assignment_state_tooltip("Preview-only")
    assert "excluded from output" in source_assignment_state_tooltip("Disabled")
    assert source_assignment_state_tooltip("Custom") == "Custom"
    assert "patched sidecar output prunes" in removed_target_dds_tooltip()


def test_mapping_table_filter_state_identifies_low_and_empty_rows() -> None:
    assert mapping_table_filters_active(show_low_only=True, show_empty_only=False)
    assert mapping_table_filters_active(show_low_only=False, show_empty_only=True)
    assert not mapping_table_filters_active(show_low_only=False, show_empty_only=False)
    assert mapping_table_confidence_matches_low_filter("Mapped: Low (0.2)")
    assert mapping_table_confidence_matches_low_filter("Manual")
    assert mapping_table_confidence_matches_low_filter("Empty")
    assert not mapping_table_confidence_matches_low_filter("Mapped: High (1.0)")
    assert mapping_table_row_hidden_by_filters(
        confidence_text="Mapped: High (1.0)",
        is_empty=False,
        show_low_only=True,
        show_empty_only=False,
    )
    assert not mapping_table_row_hidden_by_filters(
        confidence_text="Mapped: Low (0.2)",
        is_empty=False,
        show_low_only=True,
        show_empty_only=False,
    )
    assert mapping_table_row_hidden_by_filters(
        confidence_text="Manual",
        is_empty=False,
        show_low_only=False,
        show_empty_only=True,
    )
    assert not mapping_table_row_hidden_by_filters(
        confidence_text="Manual",
        is_empty=True,
        show_low_only=False,
        show_empty_only=True,
    )

    chunk_state = mapping_table_chunk_presentation_state(
        current_rows=8,
        total_rows=10,
        show_low_only=True,
        show_empty_only=False,
    )
    assert chunk_state.current_rows == 8
    assert chunk_state.total_rows == 10
    assert chunk_state.filters_active
    assert not chunk_state.fit_height
    assert not chunk_state.complete

    complete_state = mapping_table_chunk_presentation_state(
        current_rows="10",
        total_rows="10",
        show_low_only=False,
        show_empty_only=False,
    )
    assert complete_state.complete
    assert complete_state.fit_height


def test_mapping_route_control_text_preserves_labels_object_names_and_tooltips() -> None:
    text = mapping_route_control_text()

    assert text["replace"] == "Replace Target"
    assert text["add"] == "Add To Target"
    assert text["remove_source"] == "Remove From Target"
    assert text["remove_target"] == "Remove Original Part"
    assert text["clear_replacement"] == "Clear Replacement"
    assert text["clear_all"] == "Clear All"
    assert text["replace_object"] == "MeshRoutingReplaceButton"
    assert text["add_object"] == "MeshRoutingAddButton"
    assert text["remove_source_object"] == "MeshRoutingRemoveSourceButton"
    assert text["remove_target_object"] == "MeshRoutingRemoveTargetButton"
    assert "exactly the selected replacement source" in text["replace_tooltip"]
    assert "Append the selected replacement source" in text["add_tooltip"]
    assert "Remove the selected replacement source" in text["remove_source_tooltip"]
    assert "DDS sidecar references" in text["remove_target_tooltip"]
    assert "replacement source selection" in text["clear_replacement_tooltip"]
    assert "original, replacement, and target row selections" in text["clear_all_tooltip"]

    primary_specs = mapping_route_primary_button_specs(text)
    assert [spec.key for spec in primary_specs] == ["assign_source", "merge_source", "remove_source", "clear_target"]
    assert [spec.object_name for spec in primary_specs] == [
        "MeshRoutingReplaceButton",
        "MeshRoutingAddButton",
        "MeshRoutingRemoveSourceButton",
        "MeshRoutingRemoveTargetButton",
    ]
    assert [spec.color for spec in primary_specs] == ["#238636", "#1f6feb", "#8b949e", "#d29922"]
    assert mapping_route_button_style("MeshRoutingReplaceButton", "#238636") == (
        "QPushButton#MeshRoutingReplaceButton { border: 1px solid #238636; padding: 3px 8px; }"
    )

    selection_specs = mapping_route_selection_button_specs(text)
    assert [spec.key for spec in selection_specs] == ["clear_replacement", "clear_all"]
    assert [spec.label for spec in selection_specs] == ["Clear Replacement", "Clear All"]


def test_mapping_route_button_enabled_state_requires_valid_selection() -> None:
    assert mapping_route_button_enabled_state(source_index=1, target_index=2) == {
        "assign_source": True,
        "merge_source": True,
        "remove_source": True,
        "clear_target": True,
    }
    assert mapping_route_button_enabled_state(source_index=-1, target_index=2) == {
        "assign_source": False,
        "merge_source": False,
        "remove_source": False,
        "clear_target": True,
    }
    assert mapping_route_button_enabled_state(source_index=1, target_index=-1) == {
        "assign_source": False,
        "merge_source": False,
        "remove_source": False,
        "clear_target": False,
    }


def test_mapping_table_build_state_tracks_next_index_and_completion() -> None:
    state = mapping_table_build_initial_state()

    assert mapping_table_build_next_index(state) == 0
    assert not mapping_table_build_complete(state)
    mapping_table_build_set_next_index(state, 8)
    assert mapping_table_build_next_index(state) == 8
    mapping_table_build_mark_complete(state)
    assert mapping_table_build_complete(state)


def test_mapping_table_build_requested_state_tracks_started() -> None:
    state = mapping_table_build_requested_initial_state()
    build_state = mapping_table_build_initial_state()

    assert not mapping_table_build_requested_started(state)
    assert mapping_table_build_can_start(state, build_state)
    mapping_table_build_mark_requested_started(state)
    assert mapping_table_build_requested_started(state)
    assert not mapping_table_build_can_start(state, build_state)


def test_mapping_table_advanced_visibility_state_tracks_columns_and_widgets() -> None:
    visible_state = mapping_table_advanced_visibility_state(True)
    assert visible_state.advanced_visible
    assert visible_state.visible_widgets
    assert visible_state.hidden_columns == ((2, False), (4, True), (5, True), (6, True))
    assert visible_state.expand_part_tools

    hidden_state = mapping_table_advanced_visibility_state(False)
    assert not hidden_state.advanced_visible
    assert not hidden_state.visible_widgets
    assert hidden_state.hidden_columns == ((2, True), (4, False), (5, False), (6, False))
    assert not hidden_state.expand_part_tools


def test_mapping_table_progress_text_preserves_copy() -> None:
    assert mapping_table_queued_progress_text(1234) == (
        "Target routing table queued: 0 / 1,234 row(s). Preview can render while rows load."
    )
    assert mapping_table_loading_progress_text(12, 1234) == (
        "Target routing table loading: 12 / 1,234 row(s). Preview remains usable while this fills in."
    )
    assert mapping_table_ready_progress_text(1234) == "Target routing table ready: 1,234 row(s)."


def test_mapping_validation_warning_text_preserves_dialog_copy() -> None:
    assert invalid_submesh_mapping_title() == "Invalid Submesh Mapping"
    assert invalid_submesh_mapping_non_numeric_message(2, "bad") == (
        "Target 2 contains a non-numeric source index: bad"
    )
    assert invalid_submesh_mapping_missing_source_message(2, 99) == (
        "Target 2 references source index 99, but that source does not exist or is an anchor marker."
    )
    assert vertex_limit_issue_display_text(tuple(f"issue {index}" for index in range(10))) == (
        "issue 0\nissue 1\nissue 2\nissue 3\nissue 4\nissue 5\nissue 6\nissue 7\n... 2 more target(s)"
    )
    assert mesh_replacement_too_large_title() == "Mesh Replacement Too Large"
    assert mesh_replacement_too_large_message("target A exceeds") == (
        "One or more target draw slots exceed the current 16-bit export limit.\n\n"
        "target A exceeds\n\n"
        "Use the Parts tab to disable, split, or map fewer replacement sources into each target, "
        "or decimate the source mesh before importing."
    )


def test_geometry_mapping_summary_html_preserves_counts_and_session_edits() -> None:
    html = geometry_mapping_summary_html(1234, 56, 7, session_edit_count=8)

    assert "Replacement parts</span><span style='color:#f0f6fc;'> 1,234</span>" in html
    assert "Active targets</span><span style='color:#f0f6fc;'> 56</span>" in html
    assert "Empty targets</span><span style='color:#f0f6fc;'> 7</span>" in html
    assert "Session edits</span><span style='color:#f0f6fc;'> 8</span>" in html
    assert "Session edits" not in geometry_mapping_summary_html(1, 2, 3)


def test_output_impact_review_presentation_preserves_summary_and_tooltip() -> None:
    presentation = output_impact_review_presentation(
        ("target A", "target B"),
        used_source_count=1234,
        disabled_mapped_source_count=5,
        preview_only_source_count=6,
        generated_dds_count=7,
        sidecar_enabled=True,
    )

    assert "Output</span>" in presentation["html"]
    assert "| remove 2" in presentation["html"]
    assert "| source 1,234" in presentation["html"]
    assert "| disabled 5" in presentation["html"]
    assert "| preview-only 6" in presentation["html"]
    assert "| DDS 7" in presentation["html"]
    assert "| sidecar prune removed" in presentation["html"]
    assert "Removed targets: target A, target B" in presentation["tooltip"]
    assert "Removed target DDS parameters will be pruned from patched sidecars." in presentation["tooltip"]


def test_output_impact_review_presentation_preserves_prune_and_empty_states() -> None:
    pruned = output_impact_review_presentation(
        (),
        used_source_count=1,
        disabled_mapped_source_count=2,
        preview_only_source_count=3,
        generated_dds_count=4,
        sidecar_enabled=True,
        prune_unmapped_enabled=True,
    )
    empty = output_impact_review_presentation((), 0, 0, 0, 0)

    assert "| sidecar visible only" in pruned["html"]
    assert "Unmapped original DDS parameters will be pruned" in pruned["tooltip"]
    assert "| sidecar -" in empty["html"]
    assert "Removed targets: none" in empty["tooltip"]
    assert "No original targets are removed." in empty["tooltip"]
