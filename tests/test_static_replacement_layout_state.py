from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_layout_state import (
    alignment_dialog_fit_size,
    alignment_dialog_frame_origin,
    alignment_dialog_layout_embedded_resize_needed,
    alignment_dialog_layout_initial_state,
    alignment_dialog_layout_set_mode,
    alignment_dialog_responsive_layout,
)


def test_alignment_dialog_layout_initial_state_has_no_mode() -> None:
    assert alignment_dialog_layout_initial_state() == {"mode": ""}


def test_alignment_dialog_layout_embedded_resize_needed_for_first_or_forced_layout() -> None:
    state = alignment_dialog_layout_initial_state()

    assert alignment_dialog_layout_embedded_resize_needed(state, force_sizes=False) is True
    assert alignment_dialog_layout_set_mode(state, "embedded") is True
    assert alignment_dialog_layout_embedded_resize_needed(state, force_sizes=False) is False
    assert alignment_dialog_layout_embedded_resize_needed(state, force_sizes=True) is True


def test_alignment_dialog_layout_set_mode_reports_changes() -> None:
    state = alignment_dialog_layout_initial_state()

    assert alignment_dialog_layout_set_mode(state, "compact") is True
    assert alignment_dialog_layout_set_mode(state, "compact") is False
    assert alignment_dialog_layout_set_mode(state, "wide") is True
    assert state == {"mode": "wide"}


def test_alignment_dialog_responsive_layout_builds_embedded_splitter_sizes_once() -> None:
    state = alignment_dialog_layout_initial_state()

    layout = alignment_dialog_responsive_layout(
        state,
        width=1200,
        height=800,
        embedded=True,
        force_sizes=False,
        mesh_edit_tools_active=False,
        alignment_control_min_width=540,
        alignment_control_content_min_width=760,
        alignment_preview_min_width=620,
        mesh_edit_control_min_width=420,
        mesh_edit_control_content_min_width=620,
        mesh_edit_control_max_width=620,
    )

    assert layout.mode == "embedded"
    assert layout.main_orientation == "horizontal"
    assert layout.controls_policy == "preferred"
    assert layout.controls_min_width == 420
    assert layout.preview_min_width == 220
    assert layout.main_stretch == (1, 0)
    assert layout.main_sizes == (780, 420)
    assert layout.preview_sizes == (390, 390)
    assert alignment_dialog_responsive_layout(
        state,
        width=1200,
        height=800,
        embedded=True,
        force_sizes=False,
        mesh_edit_tools_active=False,
        alignment_control_min_width=540,
        alignment_control_content_min_width=760,
        alignment_preview_min_width=620,
        mesh_edit_control_min_width=420,
        mesh_edit_control_content_min_width=620,
        mesh_edit_control_max_width=620,
    ).main_sizes is None


def test_alignment_dialog_responsive_layout_covers_compact_and_wide_mesh_edit_modes() -> None:
    state = alignment_dialog_layout_initial_state()

    compact = alignment_dialog_responsive_layout(
        state,
        width=1500,
        height=900,
        embedded=False,
        force_sizes=False,
        mesh_edit_tools_active=False,
        alignment_control_min_width=540,
        alignment_control_content_min_width=760,
        alignment_preview_min_width=620,
        mesh_edit_control_min_width=420,
        mesh_edit_control_content_min_width=620,
        mesh_edit_control_max_width=620,
    )
    assert compact.mode == "compact"
    assert compact.main_orientation == "vertical"
    assert compact.controls_min_width == 0
    assert compact.main_sizes == (504, 324)
    assert compact.preview_sizes == (750, 750)

    wide_mesh = alignment_dialog_responsive_layout(
        state,
        width=2000,
        height=900,
        embedded=False,
        force_sizes=False,
        mesh_edit_tools_active=True,
        alignment_control_min_width=540,
        alignment_control_content_min_width=760,
        alignment_preview_min_width=620,
        mesh_edit_control_min_width=420,
        mesh_edit_control_content_min_width=620,
        mesh_edit_control_max_width=620,
    )
    assert wide_mesh.mode == "wide"
    assert wide_mesh.controls_policy == "fixed"
    assert wide_mesh.controls_min_width == 420
    assert wide_mesh.content_min_width == 620
    assert wide_mesh.controls_max_width == 620
    assert wide_mesh.preview_min_width == 620
    assert wide_mesh.main_sizes == (1520, 480)
    assert wide_mesh.preview_sizes == (760, 760)


def test_alignment_dialog_fit_size_and_frame_origin_clamp_to_available_screen() -> None:
    fit = alignment_dialog_fit_size(available_width=1920, available_height=1080)
    assert fit.width == 1720
    assert fit.height == 900
    assert alignment_dialog_fit_size(available_width=700, available_height=500).width == 676
    assert alignment_dialog_fit_size(available_width=700, available_height=500).height == 476

    origin = alignment_dialog_frame_origin(
        available_left=10,
        available_top=20,
        available_right=1010,
        available_bottom=820,
        frame_left=900,
        frame_top=780,
        frame_width=200,
        frame_height=100,
    )
    assert origin.left == 811
    assert origin.top == 721
