from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_mesh_edit_state import (
    mesh_edit_action_control_text,
    mesh_edit_pending_live_normals_initial_state,
    mesh_edit_revision_initial_state,
    source_geometry_revision_initial_state,
)


def test_mesh_edit_small_initial_states_preserve_defaults() -> None:
    assert mesh_edit_revision_initial_state() == {"value": 0}
    assert source_geometry_revision_initial_state() == {"value": 0}
    assert mesh_edit_pending_live_normals_initial_state() == {"include": False}


def test_mesh_edit_action_control_text_preserves_field_labels() -> None:
    text = mesh_edit_action_control_text()

    assert text["scope_label"] == "Scope"
    assert text["part_label"] == "Part"
    assert text["tool_label"] == "Tool"
    assert text["remove_mode_label"] == "Remove Mode"
    assert text["radius_label"] == "Radius"
    assert text["strength_label"] == "Strength"
    assert text["falloff_label"] == "Falloff"
    assert text["iterations_label"] == "Iterations"
    assert text["selection_label"] == "Selection"
    assert text["depth_label"] == "Depth"
