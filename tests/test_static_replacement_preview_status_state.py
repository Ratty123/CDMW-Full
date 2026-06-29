from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_preview_status_state import (
    alignment_d3d11_renderer_error_message,
    alignment_preview_camera_button_specs,
    alignment_preview_control_text,
    alignment_preview_help_presentation,
    alignment_preview_initial_performance_status,
    alignment_preview_render_control_text,
    alignment_preview_view_sync_initial_state,
    preview_controls_ready_initial_state,
    preview_performance_status,
    static_preview_refresh_interval_ms,
    static_preview_refresh_performance_status,
    static_preview_settle_interval_ms,
)


def test_alignment_preview_small_initial_states_preserve_defaults() -> None:
    assert alignment_preview_view_sync_initial_state() == {"active": False}
    assert preview_controls_ready_initial_state() == {"ready": False}


def test_alignment_preview_camera_button_specs_preserve_order_labels_and_tooltips() -> None:
    specs = alignment_preview_camera_button_specs()

    assert [spec[0] for spec in specs] == ["Front", "Left", "Right", "Back", "Top", "Bottom", "-15", "+15", "Reset/Fit"]
    assert [spec[1] for spec in specs] == [
        "MeshAlignmentCameraFrontButton",
        "MeshAlignmentCameraLeftButton",
        "MeshAlignmentCameraRightButton",
        "MeshAlignmentCameraBackButton",
        "MeshAlignmentCameraTopButton",
        "MeshAlignmentCameraBottomButton",
        "MeshAlignmentCameraYawLeftButton",
        "MeshAlignmentCameraYawRightButton",
        "MeshAlignmentCameraResetFitButton",
    ]
    assert specs[0][2] == "Frame the replacement from the front. This moves only the preview camera."
    assert specs[-1][2] == "Reset camera yaw, pitch, pan, and fit framing. This does not change the mesh."


def test_alignment_preview_control_text_preserves_header_and_control_copy() -> None:
    text = alignment_preview_control_text()

    assert text["title"] == "Live Alignment Preview"
    assert text["clear_selection"] == "Clear Selection"
    assert "without changing routing" in text["clear_selection_tooltip"]
    assert text["renderer_label"] == "Renderer"
    assert "Archive Browser renderer" in text["renderer_tooltip"]
    assert text["renderer_scope"] == "Mesh Replacement Alignment renderer and texture controls are available from Preview Settings."
    assert text["preview_mode_label"] == "Preview mode"
    assert "Replacement only gives more room" in text["preview_mode_tooltip"]
    assert text["overlay_original_locked"] == "Original locked"
    assert "keep the original reference fixed" in text["overlay_original_locked_tooltip"]
    assert text["gizmo"] == "Gizmo"
    assert "move/rotate axis handles" in text["gizmo_tooltip"]
    assert text["part_pick"] == "Part Pick"
    assert "hover highlights source parts" in text["part_pick_tooltip"]
    assert text["d3d11_view_label"] == "D3D11 view"
    assert text["settings_button"] == "Preview Settings..."
    assert text["use_global"] == "Use Global"
    assert text["camera_label"] == "Camera"


def test_alignment_preview_control_text_preserves_d3d11_status_copy() -> None:
    text = alignment_preview_control_text()

    assert text["d3d11_legend"] == "Drag axes/center to move; Alt-drag to rotate; wheel zooms."
    assert "left-drag orbit" in text["d3d11_legend_tooltip"]
    assert text["d3d11_waiting_status"] == "Native D3D11 alignment preview is waiting for the first refresh."
    assert text["d3d11_renderer_error"] == "Native D3D11 renderer error."
    assert text["d3d11_unavailable_status"] == "Preview host is unavailable."
    assert text["d3d11_closed_status"] == "Preview closed."


def test_alignment_preview_help_presentation_preserves_renderer_mode_copy() -> None:
    static_help = alignment_preview_help_presentation(d3d11_active=False)
    d3d11_help = alignment_preview_help_presentation(d3d11_active=True)

    assert static_help.text == "Live preview. Build Mod validates final package paths during export."
    assert "candidate location/rotation/scale" in static_help.tooltip
    assert "Mesh Replacement Alignment renderer" in static_help.settings_tooltip
    assert d3d11_help.text == "Native D3D11 alignment preview."
    assert "view modes run through D3D11" in d3d11_help.tooltip
    assert "native D3D11 renderer" in d3d11_help.settings_tooltip


def test_alignment_d3d11_renderer_error_message_preserves_fallback() -> None:
    assert alignment_d3d11_renderer_error_message("") == "Native D3D11 renderer error."
    assert alignment_d3d11_renderer_error_message("GPU device removed") == "GPU device removed"


def test_alignment_preview_initial_performance_status_preserves_copy() -> None:
    presentation = alignment_preview_initial_performance_status()

    assert presentation.text == "Preview timing: waiting for first refresh."
    assert presentation.tooltip == "Live preview CPU rebuild, prepared-model, and texture upload timing."
    assert static_preview_refresh_interval_ms() == 140
    assert static_preview_settle_interval_ms() == 850


def test_alignment_preview_render_control_text_preserves_copy() -> None:
    text = alignment_preview_render_control_text()

    assert text["visible_label"] == "Visible"
    assert text["visible_tooltip"] == "Texture-selection strategy for alignment preview rebuilds."
    assert text["render_label"] == "Render"
    assert text["render_tooltip"] == "Render mode for the live alignment preview."
    assert text["disable_tint"] == "No tint"
    assert text["disable_tint_tooltip"] == "Ignore sidecar tint in this alignment preview."
    assert text["disable_brightness"] == "No brightness"
    assert text["disable_brightness_tooltip"] == "Ignore sidecar brightness multiplier in this alignment preview."
    assert text["disable_uv_scale"] == "No UV scale"
    assert text["disable_uv_scale_tooltip"] == "Ignore sidecar UV scale in this alignment preview."
    assert text["support_maps"] == "Support maps"
    assert text["support_maps_tooltip"] == "Enable resolved normal, material/mask, and height maps in the preview."
    assert text["depth_label"] == "Depth"
    assert text["depth_tooltip"] == "Height/depth contribution for Lit and Height / Depth Response preview modes."
    assert text["shine_label"] == "Shine"
    assert text["shine_tooltip"] == "Maximum material/metal shine contribution in Lit and Metal / Shine Response modes."
    assert text["rough_label"] == "Rough"
    assert text["rough_tooltip"] == "Roughness contrast for highlight sharpness and Roughness Response diagnostics."
    assert text["original_reference_label"] == "Original Reference"
    assert text["original_reference_description"] == "Original asset reference preview."
    assert text["original_reference_loading"] == "Original reference preview is loading..."
    assert text["replacement_preview_label"] == "Replacement Preview"
    assert text["replacement_preview_description"] == "Select texture slots to preview."
    assert text["replacement_preview_loading"] == "Replacement preview is loading..."


def test_preview_performance_status_uses_summary_for_text_and_tooltip() -> None:
    presentation = preview_performance_status("Preview ready.")

    assert presentation.text == "Preview ready."
    assert presentation.tooltip == "Preview ready."


def test_preview_performance_status_prefers_details_for_tooltip() -> None:
    presentation = preview_performance_status("Preview ready.", details="worker=done")

    assert presentation.text == "Preview ready."
    assert presentation.tooltip == "worker=done"


def test_preview_performance_status_keeps_empty_fallback_tooltip() -> None:
    presentation = preview_performance_status("")

    assert presentation.text == ""
    assert presentation.tooltip == "Live preview status."


def test_static_preview_refresh_performance_status_formats_timing_summary() -> None:
    presentation = static_preview_refresh_performance_status(
        quality_label="Archive Preview parity",
        refresh_ms=12.6,
        geometry_ms=3.25,
        prepare_ms=4.5,
        upload_ms=5.75,
    )

    assert presentation.text == "Preview refreshed - Archive Preview parity - refresh 13 ms"
    assert presentation.tooltip == (
        "refresh 12.6 ms\n"
        "geometry 3.2 ms\n"
        "prepare 4.5 ms\n"
        "GL upload 5.8 ms"
    )


def test_static_preview_refresh_performance_status_coerces_invalid_timings() -> None:
    presentation = static_preview_refresh_performance_status(
        quality_label="",
        refresh_ms=None,
        geometry_ms="bad",
        prepare_ms=1,
        upload_ms="2.4",
    )

    assert presentation.text == "Preview refreshed -  - refresh 0 ms"
    assert presentation.tooltip == (
        "refresh 0.0 ms\n"
        "geometry 0.0 ms\n"
        "prepare 1.0 ms\n"
        "GL upload 2.4 ms"
    )
