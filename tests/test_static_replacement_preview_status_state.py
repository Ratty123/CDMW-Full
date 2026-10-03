from __future__ import annotations

from types import SimpleNamespace

from cdmw.models import ModelPreviewRenderSettings
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
from cdmw.ui.archive_browser.static_replacement_preview_mode_state import (
    alignment_preview_mode_initial_state,
    alignment_preview_mode_record,
)
from cdmw.ui.archive_browser.static_replacement_static_preview_state import static_preview_refresh_route_state
from cdmw.ui.archive_browser.static_replacement_raw_preview_state import (
    mesh_edit_raw_preview_initial_state,
    mesh_edit_raw_preview_record_state,
)
from cdmw.ui.archive_browser.static_replacement_preview_batch_state import (
    static_preview_batch_begin,
    static_preview_batch_end,
    static_preview_batch_initial_state,
    static_preview_batch_queue_request,
)
from cdmw.ui.archive_browser.static_replacement_preview_limits import (
    alignment_preview_background_source_face_limit_for_total,
    alignment_preview_requested_source_indices,
    alignment_preview_selected_source_face_limit_for_total,
    alignment_preview_source_face_total,
)
from cdmw.ui.archive_browser.static_replacement_d3d11_state import (
    alignment_d3d11_mark_loaded_package,
    alignment_d3d11_package_quality,
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
    assert "move/rotate/scale handles" in text["gizmo_tooltip"]
    assert "hidden and inactive in Edit Mesh" in text["gizmo_tooltip"]
    assert text["part_pick"] == "Part Pick"
    assert "hover highlights source parts" in text["part_pick_tooltip"]
    assert text["mesh_view_label"] == "Mesh view"
    assert "Edit Mesh > Viewport" in text["mesh_view_tooltip"]
    assert "Faces + Wire is the readable default" in text["mesh_view_tooltip"]
    assert text["dotnet_view_label"] == "Preview mode"
    assert "Preview" in text["dotnet_view_tooltip"]
    assert "Only renderer-backed modes" in text["dotnet_view_tooltip"]
    assert text["settings_button"] == "Preview Settings..."
    assert text["use_global"] == "Use Global"
    assert text["camera_label"] == "Camera"


def test_alignment_preview_control_text_uses_rust_authoritative_status_copy() -> None:
    text = alignment_preview_control_text()

    # The gesture legend and the "Live Alignment Preview" title are retired:
    # both spent a line of the editor's height restating tooltips.
    assert "d3d11_legend" not in text
    assert "d3d11_legend_tooltip" not in text
    assert "title" not in text
    assert text["d3d11_waiting_status"] == "Preview alignment preview is waiting for the resident renderer."
    assert text["d3d11_renderer_error"] == "Preview renderer error."
    assert text["d3d11_unavailable_status"] == "Preview host is unavailable."
    assert text["d3d11_closed_status"] == "Preview closed."


def test_alignment_preview_help_presentation_preserves_renderer_mode_copy() -> None:
    static_help = alignment_preview_help_presentation(d3d11_active=False)
    d3d11_help = alignment_preview_help_presentation(d3d11_active=True)

    assert static_help.text == "Live preview. Build Mod validates final package paths during export."
    assert "candidate location/rotation/scale" in static_help.tooltip
    assert "Mesh Replacement Alignment renderer" in static_help.settings_tooltip
    assert d3d11_help.text == "Resident Preview alignment preview."
    assert "resident Preview renderer" in d3d11_help.tooltip
    assert "Preview renderer" in d3d11_help.settings_tooltip


def test_alignment_d3d11_renderer_error_message_preserves_fallback() -> None:
    assert alignment_d3d11_renderer_error_message("") == "Preview renderer error."
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


def test_alignment_preview_mode_initial_state_defaults_to_side_by_side() -> None:
    assert alignment_preview_mode_initial_state(None) == {"current": "side_by_side"}
    assert alignment_preview_mode_initial_state("replacement_only") == {"current": "replacement_only"}


def test_alignment_preview_mode_record_returns_previous_and_current() -> None:
    state = alignment_preview_mode_initial_state("side_by_side")

    assert alignment_preview_mode_record(state, "replacement_only") == ("side_by_side", "replacement_only")
    assert state == {"current": "replacement_only"}

    assert alignment_preview_mode_record(state, "") == ("replacement_only", "side_by_side")
    assert state == {"current": "side_by_side"}


def test_static_preview_refresh_route_state_keeps_external_materials_and_tracks_original_readiness() -> None:
    route = static_preview_refresh_route_state(
        active_preview_mode="replacement_only",
        mesh_edit_enabled=False,
        mesh_edit_tab_active=False,
        replacement_mesh_available=True,
        interactive_preview=False,
        complete_external_swap_enabled=False,
        needs_original_material_preview=False,
        preview_controls_ready=True,
        original_mesh_available=True,
    )

    assert route.mesh_edit_direct_source_preview is False
    assert route.replacement_only_direct_source_preview is False
    assert route.source_owned_direct_source_preview is True
    assert route.require_original_reference is True
    assert route.can_build_source_geometry is True
    assert route.waits_for_original_reference(ready=False) is False

    mesh_edit_route = static_preview_refresh_route_state(
        active_preview_mode="side_by_side",
        mesh_edit_enabled=True,
        mesh_edit_tab_active=True,
        replacement_mesh_available=True,
        interactive_preview=True,
        complete_external_swap_enabled=True,
        needs_original_material_preview=False,
        preview_controls_ready=False,
        original_mesh_available=True,
    )

    assert mesh_edit_route.mesh_edit_direct_source_preview is False
    assert mesh_edit_route.replacement_only_direct_source_preview is False
    assert mesh_edit_route.source_owned_direct_source_preview is True
    assert mesh_edit_route.require_original_reference is True
    assert mesh_edit_route.can_build_source_geometry is False
    assert mesh_edit_route.waits_for_original_reference(ready=False) is True
    assert mesh_edit_route.waits_for_original_reference(ready=True) is False


def test_mesh_edit_raw_preview_initial_state_is_inactive() -> None:
    assert mesh_edit_raw_preview_initial_state() == {"active": False}


def test_mesh_edit_raw_preview_record_state_returns_previous_and_current() -> None:
    state = mesh_edit_raw_preview_initial_state()

    assert mesh_edit_raw_preview_record_state(state, True) == (False, True)
    assert state == {"active": True}

    assert mesh_edit_raw_preview_record_state(state, False) == (True, False)
    assert state == {"active": False}


def test_static_preview_batch_initial_state_preserves_flags() -> None:
    assert static_preview_batch_initial_state() == {
        "depth": 0,
        "texture": False,
        "texture_uv": False,
        "rebuild": False,
        "refresh": False,
    }


def test_static_preview_batch_queue_request_only_records_inside_batch() -> None:
    state: dict[str, object] = {"depth": 0}

    assert static_preview_batch_queue_request(state, "texture_uv") is False
    assert "texture_uv" not in state

    static_preview_batch_begin(state)

    assert static_preview_batch_queue_request(state, "texture_uv") is True
    assert state["texture_uv"] is True


def test_static_preview_batch_end_returns_outermost_requests_and_resets() -> None:
    state: dict[str, object] = {"depth": 0}

    static_preview_batch_begin(state)
    static_preview_batch_begin(state)
    static_preview_batch_queue_request(state, "texture")

    assert static_preview_batch_end(state) is None

    static_preview_batch_queue_request(state, "rebuild")
    payload = static_preview_batch_end(state)

    assert payload == {
        "texture": True,
        "texture_uv": False,
        "rebuild": True,
        "refresh": False,
    }
    assert state["depth"] == 0
    assert state["texture"] is False
    assert state["texture_uv"] is False
    assert state["rebuild"] is False
    assert state["refresh"] is False


def test_alignment_preview_requested_source_indices_filters_to_existing_submeshes() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert alignment_preview_requested_source_indices(mesh, (0, "2", 3, -1, "bad")) == (0, 2)
    assert alignment_preview_requested_source_indices(SimpleNamespace(submeshes=[]), (0,)) == ()


def test_alignment_preview_source_face_total_counts_requested_submeshes() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(faces=[1, 2]),
            SimpleNamespace(faces=[]),
            SimpleNamespace(faces=[1, 2, 3]),
        ]
    )

    assert alignment_preview_source_face_total(mesh, (0, 2, 9, "bad")) == 5


def test_alignment_preview_selected_source_face_limit_thresholds() -> None:
    assert alignment_preview_selected_source_face_limit_for_total(
        130_000,
        selected_requested=True,
        interactive=True,
        fallback_limit=7,
    ) == 18_000
    assert alignment_preview_selected_source_face_limit_for_total(
        130_000,
        selected_requested=False,
        interactive=True,
        fallback_limit=7,
    ) == 8_000
    assert alignment_preview_selected_source_face_limit_for_total(
        10_000,
        selected_requested=False,
        interactive=False,
        fallback_limit=7,
    ) == 7


def test_alignment_preview_background_source_face_limit_thresholds() -> None:
    assert alignment_preview_background_source_face_limit_for_total(
        130_000,
        interactive=True,
        fallback_limit=7,
    ) == 2_000
    assert alignment_preview_background_source_face_limit_for_total(
        45_000,
        interactive=False,
        fallback_limit=7,
    ) == 5_000
    assert alignment_preview_background_source_face_limit_for_total(
        10_000,
        interactive=False,
        fallback_limit=7,
    ) == 7


def test_alignment_d3d11_package_quality_keeps_loaded_material_frame_during_geometry_rebuild() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)

    result_settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {
            "fast_geometry_loaded": False,
            "archive_parity_ready": False,
            "material_complete_preview_seen": True,
        },
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert result_settings.use_textures_by_default is False
    assert high_quality is False
    assert material_combiner is False
    assert package_quality == "archive_parity"


def test_material_complete_frame_authority_survives_active_package_handoff() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)
    state: dict[str, object] = {}
    alignment_d3d11_mark_loaded_package(state, package_quality="archive_parity")
    state.update(
        preview_loaded=False,
        active_package_quality="",
        fast_geometry_loaded=False,
        archive_parity_ready=False,
    )

    _result_settings, _high_quality, _combiner, quality = alignment_d3d11_package_quality(
        settings,
        state,
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert state["material_complete_preview_seen"] is True
    assert quality == "archive_parity"
