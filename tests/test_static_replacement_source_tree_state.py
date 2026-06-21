from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_source_tree_state import (
    source_tree_context_menu_selection_state,
    source_tree_context_selection_action,
    source_tree_context_selection_clear_multi_indices,
    source_tree_context_selection_initial_state,
    source_tree_context_selection_multi_indices,
    source_tree_context_selection_record_multi_indices,
    source_tree_context_selection_right_press,
    source_tree_context_selection_set_right_press,
    source_tree_control_text,
    source_tree_current_selection_index,
    source_tree_item_state,
    source_tree_item_update_guard_initial_state,
    source_tree_layout_state,
    source_tree_population_chunk_policy,
    source_tree_population_complete,
    source_tree_population_initial_state,
    source_tree_population_loading_text,
    source_tree_population_mark_complete,
    source_tree_population_next_index,
    source_tree_population_queued_text,
    source_tree_population_ready_text,
    source_tree_population_set_next_index,
    source_tree_role_menu_specs,
)


def test_source_tree_item_update_guard_initial_state_preserves_default() -> None:
    assert source_tree_item_update_guard_initial_state() == {"active": False}


def test_source_tree_context_selection_tracks_right_press() -> None:
    state = source_tree_context_selection_initial_state()

    assert not source_tree_context_selection_right_press(state)
    source_tree_context_selection_set_right_press(state, True)
    assert source_tree_context_selection_right_press(state)
    source_tree_context_selection_set_right_press(state, False)
    assert not source_tree_context_selection_right_press(state)


def test_source_tree_context_selection_records_and_clears_multi_indices() -> None:
    state = source_tree_context_selection_initial_state()

    source_tree_context_selection_record_multi_indices(state, [3, 1])
    assert source_tree_context_selection_multi_indices(state) == (3, 1)
    source_tree_context_selection_clear_multi_indices(state)
    assert source_tree_context_selection_multi_indices(state) == ()


def test_source_tree_context_selection_action_tracks_multi_and_right_press_state() -> None:
    assert source_tree_context_selection_action([3, 1], right_press_active=False) == "record_multi"
    assert source_tree_context_selection_action([3], right_press_active=False) == "clear_multi"
    assert source_tree_context_selection_action([], right_press_active=True) == "none"


def test_source_tree_context_menu_selection_state_preserves_multi_right_click() -> None:
    preserved = source_tree_context_menu_selection_state(
        clicked_source_index=3,
        selected_source_indices=(3,),
        preserved_multi_indices=(3, 5),
        clicked_item_selected=True,
    )
    assert preserved.selected_source_indices == (3, 5)
    assert not preserved.select_clicked_item
    assert not preserved.clear_multi_indices

    clicked = source_tree_context_menu_selection_state(
        clicked_source_index="7",
        selected_source_indices=(),
        preserved_multi_indices=(),
        clicked_item_selected=False,
    )
    assert clicked.selected_source_indices == (7,)
    assert clicked.select_clicked_item
    assert clicked.clear_multi_indices


def test_source_tree_current_selection_index_uses_current_then_first_valid_selected() -> None:
    assert source_tree_current_selection_index(4, [1, 2]) == 4
    assert source_tree_current_selection_index(-1, ["bad", -2, "3"]) == 3
    assert source_tree_current_selection_index("bad", []) == -1


def test_source_tree_population_tracks_next_index_and_completion() -> None:
    state = source_tree_population_initial_state()

    assert source_tree_population_next_index(state) == 0
    assert not source_tree_population_complete(state)
    source_tree_population_set_next_index(state, 12)
    assert source_tree_population_next_index(state) == 12
    source_tree_population_mark_complete(state)
    assert source_tree_population_complete(state)


def test_source_tree_control_text_preserves_labels_and_headers() -> None:
    text = source_tree_control_text()

    assert text["source_group_title"] == "Replacement reference parts"
    assert "Original reference parts" in str(text["original_label_html"])
    assert "Replacement reference parts" in str(text["replacement_label_html"])
    assert text["source_tree_headers"] == ["Use", "#", "Source", "Role", "Target", "Status", "Geometry"]


def test_source_tree_layout_and_population_policy_preserve_ui_constants() -> None:
    layout_state = source_tree_layout_state()
    assert layout_state.minimum_height == 108
    assert layout_state.configure_widths == (42, 36, 120, 64, 120, 62, 96)
    assert layout_state.autofit_min_widths == (34, 30, 90, 60, 90, 60, 110)
    assert layout_state.autofit_max_widths == (48, 46, 220, 140, 220, 110, 180)
    assert layout_state.expand_columns == (2, 4, 6)
    assert layout_state.max_height == 360
    assert layout_state.height_fit_kwargs == {"minimum": 108, "screen_margin": 420, "maximum": 260}
    assert layout_state.persist_key == "source_parts"

    chunk_policy = source_tree_population_chunk_policy()
    assert chunk_policy.row_limit == 40
    assert chunk_policy.time_budget_seconds == 0.006


def test_source_tree_item_state_normalizes_source_row_values() -> None:
    source = type("Source", (), {"vertices": (1, 2), "faces": (1,), "name": "Part", "material": "Mat"})()
    state = source_tree_item_state(
        source_index="3",
        source=source,
        copied_texture_rows=("a", "b"),
        copied_texture_disabled=True,
        adjustment=type("Adjustment", (), {"enabled": False})(),
    )
    assert state.source_index == 3
    assert state.geometry_text == "2 vertices, 1 faces"
    assert state.source_name == "Part"
    assert state.source_material == "Mat"
    assert state.copied_texture_count == 2
    assert state.copied_texture_disabled
    assert not state.enabled


def test_source_tree_role_menu_specs_normalizes_labels_and_values() -> None:
    assert source_tree_role_menu_specs((("Auto", ""), ("Glow", "glow"), ("Bad", None))) == (
        ("Auto", ""),
        ("Glow", "glow"),
        ("Bad", ""),
    )


def test_source_tree_population_text_preserves_progress_copy() -> None:
    assert source_tree_population_queued_text(1234) == (
        "Replacement source list queued: 0 / 1,234 row(s). Preview can open while rows load."
    )
    assert source_tree_population_loading_text(12, 1234) == "Replacement source list loading: 12 / 1,234 row(s)."
    assert source_tree_population_ready_text(1234) == "Replacement source list ready: 1,234 row(s)."
