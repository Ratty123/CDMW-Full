from __future__ import annotations

from collections import OrderedDict

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.static_replacement_d3d11_cache import (
    alignment_d3d11_invalidate_package_cache,
)
from cdmw.ui.archive_browser.static_replacement_d3d11_state import (
    ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES,
    alignment_d3d11_active_package_matches,
    alignment_d3d11_active_package_snapshot,
    alignment_d3d11_alignment_preview_failed_performance,
    alignment_d3d11_begin_archive_parity_upgrade,
    alignment_d3d11_begin_package_request,
    alignment_d3d11_cache_key_with_native_reference,
    alignment_d3d11_cached_loading_progress_detail,
    alignment_d3d11_cached_renderer_reload_detail,
    alignment_d3d11_clear_active_package,
    alignment_d3d11_clear_archive_parity_upgrade,
    alignment_d3d11_cached_loading_performance,
    alignment_d3d11_cached_reuse_performance,
    alignment_d3d11_closed_status_route,
    alignment_d3d11_clear_fast_transform_state,
    alignment_d3d11_clear_loading_start,
    alignment_d3d11_clear_original_texture_worker_refs,
    alignment_d3d11_clear_package_worker_refs,
    alignment_d3d11_clear_pending_process_retry,
    alignment_d3d11_clear_process_status_refs,
    alignment_d3d11_clear_queued_preview_request,
    alignment_d3d11_clear_stuck_loading_route,
    alignment_d3d11_drag_reload_stale,
    alignment_d3d11_error_status_route,
    alignment_d3d11_fast_transform_preview_state,
    alignment_d3d11_fast_transform_queue_state,
    alignment_d3d11_fast_transform_replay_state,
    alignment_d3d11_fast_transform_send_state,
    alignment_d3d11_failed_performance,
    alignment_d3d11_failed_performance_details,
    alignment_d3d11_global_fast_transform_pending,
    alignment_d3d11_host_ready_state,
    alignment_d3d11_loaded_package_transform_current,
    alignment_d3d11_loaded_status_route,
    alignment_d3d11_live_frame_available,
    alignment_d3d11_live_display_mode_performance,
    alignment_d3d11_loading_active,
    alignment_d3d11_loading_cleared_performance,
    alignment_d3d11_loading_initial_state,
    alignment_d3d11_loading_next_frame,
    alignment_d3d11_loading_presentation,
    alignment_d3d11_loading_recovery_action,
    alignment_d3d11_loading_set_active,
    alignment_d3d11_loading_spinner_frames,
    alignment_d3d11_loading_spinner_html,
    alignment_d3d11_loading_status_route,
    alignment_d3d11_loading_stuck,
    alignment_d3d11_loading_watchdog_snapshot,
    alignment_d3d11_invalid_status_payload_route,
    alignment_d3d11_loaded_timing_presentation,
    alignment_d3d11_mark_active_cached_package_reused,
    alignment_d3d11_mark_loaded_package,
    alignment_d3d11_mark_loading_started,
    alignment_d3d11_mark_preview_loaded,
    alignment_d3d11_mark_preview_unloaded,
    alignment_d3d11_mark_rebuild_reason,
    alignment_d3d11_mark_resources_loaded,
    alignment_d3d11_mark_transform_changed,
    alignment_d3d11_mode_refresh_needed,
    alignment_d3d11_mode_requires_original,
    alignment_d3d11_next_original_texture_worker_request_id,
    alignment_d3d11_original_texture_worker_request_current,
    alignment_d3d11_package_mode_has_original,
    alignment_d3d11_package_queued_performance,
    alignment_d3d11_package_loading_detail,
    alignment_d3d11_package_drop_cleanup_state,
    alignment_d3d11_package_failed_performance,
    alignment_d3d11_package_preparing_performance,
    alignment_d3d11_package_quality,
    alignment_d3d11_package_settings_changed,
    alignment_d3d11_pending_host_performance,
    alignment_d3d11_package_ready_route,
    alignment_d3d11_package_refresh_in_flight,
    alignment_d3d11_package_start_route,
    alignment_d3d11_pipeline_stage,
    alignment_d3d11_progress_update,
    alignment_d3d11_preview_mode_static_refresh_needed,
    alignment_d3d11_prepare_active_package,
    alignment_d3d11_process_finished_route,
    alignment_d3d11_process_reuse_state,
    alignment_d3d11_process_request_metadata,
    alignment_d3d11_process_start_route,
    alignment_d3d11_queued_latest_preview_reload_detail,
    alignment_d3d11_queued_preview_reload_detail,
    alignment_d3d11_queue_pending_request,
    alignment_d3d11_queue_preview_request,
    alignment_d3d11_raw_package_active_or_pending,
    alignment_d3d11_record_fast_transform_payload,
    alignment_d3d11_record_pending_process_retry,
    alignment_d3d11_record_original_texture_worker_refs,
    alignment_d3d11_record_package_worker_refs,
    alignment_d3d11_record_process_ref,
    alignment_d3d11_record_status_payload,
    alignment_d3d11_record_stale_reload_restart,
    alignment_d3d11_reload_queued_performance,
    alignment_d3d11_resources_waiting_detail,
    alignment_d3d11_resources_waiting_performance,
    alignment_d3d11_resources_waiting_performance_details,
    alignment_d3d11_resources_loaded_status_route,
    alignment_d3d11_restart_performance,
    alignment_d3d11_restart_performance_details,
    alignment_d3d11_remember_request_cache_key,
    alignment_d3d11_remember_request_package_quality,
    alignment_d3d11_reset_material_parity_state,
    alignment_d3d11_reset_request_state,
    alignment_d3d11_request_active,
    alignment_d3d11_request_cache_key,
    alignment_d3d11_request_display_mode,
    alignment_d3d11_request_package_quality,
    alignment_d3d11_request_reason,
    alignment_d3d11_render_settings_rebuild_performance,
    alignment_d3d11_render_settings_route,
    alignment_d3d11_saved_view_state_route,
    alignment_d3d11_render_tuning_live_performance,
    alignment_d3d11_renderer_error_performance,
    alignment_d3d11_renderer_host_restart_performance,
    alignment_d3d11_selection_highlight_performance,
    alignment_d3d11_restore_active_package,
    alignment_d3d11_stale_loading_detail,
    alignment_d3d11_stale_loading_restart_allowed,
    alignment_d3d11_stale_reload_route,
    alignment_d3d11_starting_performance,
    alignment_d3d11_startup_timeout_performance,
    alignment_d3d11_start_timeout_route,
    alignment_d3d11_stale_package_dropped_detail,
    alignment_d3d11_stale_package_dropped_performance,
    alignment_d3d11_status_event,
    alignment_d3d11_status_read_error_route,
    alignment_d3d11_take_pending_request,
    alignment_d3d11_theme_payload,
    alignment_d3d11_texture_flip_v_live_performance,
    alignment_d3d11_unavailable_performance,
    alignment_d3d11_unavailable_status_route,
    alignment_d3d11_ensure_loading_started,
    alignment_d3d11_view_state_reset_needed,
    alignment_d3d11_view_state_payload_route,
    alignment_d3d11_watchdog_ready_performance,
    alignment_d3d11_waiting_for_preview_panel_detail,
    alignment_lit_render_settings,
    alignment_preview_widget_render_settings,
    alignment_preview_quality_label,
    live_alignment_preview_status_message,
)
from cdmw.ui.archive_browser.static_replacement_raw_preview_state import (
    mesh_edit_raw_preview_transition_route,
)
from cdmw.ui.archive_browser.static_replacement_preview_mode_state import (
    alignment_preview_mode_route,
    alignment_preview_renderer_route,
)


def test_alignment_d3d11_loading_state_tracks_spinner_frame_and_active_flag() -> None:
    state = alignment_d3d11_loading_initial_state()

    assert state == {"active": False, "frame": 0}
    assert alignment_d3d11_loading_active(state) is False
    assert alignment_d3d11_loading_set_active(state, True) is True
    assert alignment_d3d11_loading_active(state) is True
    assert alignment_d3d11_loading_next_frame(state, 4) == 1
    assert alignment_d3d11_loading_next_frame(state, 4) == 2
    assert alignment_d3d11_loading_set_active(state, False) is False
    assert state == {"active": False, "frame": 2}


def test_alignment_d3d11_mesh_edit_mode_preserves_package_cache(tmp_path) -> None:
    active_package = tmp_path / "textured"
    raw_package = tmp_path / "raw"
    active_package.mkdir()
    raw_package.mkdir()
    state: dict[str, object] = {
        "active_package": active_package,
        "active_package_cache_key": "textured",
        "package_cache": OrderedDict(
            (
                (
                    "textured",
                    {"package_dir": active_package, "package_quality": "archive_parity"},
                ),
                (
                    "raw",
                    {"package_dir": raw_package, "package_quality": "mesh_edit_raw"},
                ),
            )
        ),
    }
    cleaned: list[tuple[object, int]] = []

    alignment_d3d11_invalidate_package_cache(
        state,
        "mesh_edit_mode",
        cleanup_package=lambda package, delay_ms: cleaned.append((package, delay_ms)),
    )

    assert list(state["package_cache"]) == ["textured", "raw"]
    assert state["active_package_cache_key"] == "textured"
    assert state["last_cache_event"] == "mode_dirty"
    assert state["last_cache_reason"] == "mesh_edit_mode"
    assert cleaned == []

    alignment_d3d11_invalidate_package_cache(
        state,
        "geometry",
        cleanup_package=lambda package, delay_ms: cleaned.append((package, delay_ms)),
    )

    assert state["package_cache"] == OrderedDict()
    assert state["active_package_cache_key"] == ""
    assert cleaned == [(active_package, 5000), (raw_package, 0)]


def test_alignment_d3d11_loading_presentation_prefers_detail_tooltip() -> None:
    presentation = alignment_d3d11_loading_presentation(
        True,
        message="Preparing preview",
        detail="stage=package",
    )

    assert presentation.status_text == "Preparing preview"
    assert presentation.status_tooltip == "stage=package"
    assert presentation.spinner_visible is True
    assert presentation.clear_spinner_text is False


def test_alignment_d3d11_loading_presentation_clears_spinner_when_inactive() -> None:
    presentation = alignment_d3d11_loading_presentation(False, message="Preview ready")

    assert presentation.status_text == "Preview ready"
    assert presentation.status_tooltip == "Preview ready"
    assert presentation.spinner_visible is False
    assert presentation.clear_spinner_text is True


def test_alignment_d3d11_loading_spinner_helpers_preserve_frame_html() -> None:
    assert alignment_d3d11_loading_spinner_frames() == ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES
    assert ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES == ("&#9679;", "&#9683;", "&#9681;", "&#9682;")

    html = alignment_d3d11_loading_spinner_html("&#9679;")

    assert "font-size:2.4em" in html
    assert "line-height:1.17" in html
    assert "color:#79c0ff" in html
    assert "&#9679;" in html


def test_alignment_d3d11_resources_waiting_details_include_host_and_progress() -> None:
    detail = alignment_d3d11_resources_waiting_detail(
        reason="loading watchdog",
        elapsed_s=7.25,
        last_percent=45,
        last_stage="package",
        host_detail="host hidden",
        child_detail="child missing",
        active_package="pkg",
    )

    assert "Native D3D11 uploaded package resources" in detail
    assert "elapsed=7.2s" in detail
    assert "last_progress=45%" in detail
    assert "last_stage=package" in detail
    assert "reason=loading watchdog" in detail
    assert "host=host hidden" in detail
    assert "child=child missing" in detail
    assert "active_package=pkg" in detail


def test_alignment_d3d11_resources_waiting_performance_details_stay_compact() -> None:
    detail = alignment_d3d11_resources_waiting_performance_details(
        reason="missing status file",
        elapsed_s=1.5,
        host_detail="host ready",
        child_detail="child ready",
        active_package="pkg",
    )

    assert detail == (
        "reason=missing status file\n"
        "elapsed=1.5s\n"
        "host=host ready\n"
        "child=child ready\n"
        "active_package=pkg"
    )


def test_alignment_d3d11_stale_loading_details_and_restart_failure_text() -> None:
    stale = alignment_d3d11_stale_loading_detail(
        reason="unchanged status file",
        elapsed_s=6.0,
        last_percent=80,
        last_stage="native_start",
        host_detail="host ready",
        child_detail="child ready",
        active_package="pkg",
    )

    assert stale.startswith("Native D3D11 stayed alive but did not report a fresh rendered frame.")
    assert "elapsed=6.0s" in stale
    assert "last_progress=80%" in stale
    assert "last_stage=native_start" in stale
    assert "reason=unchanged status file" in stale
    assert "active_package=pkg" in stale
    assert "restart=2/2" in alignment_d3d11_restart_performance_details(stale, restart_count=1)
    assert "latest preview request was queued immediately" in alignment_d3d11_restart_performance_details(
        stale,
        restart_count=1,
    )
    assert "no native loaded event arrived before the watchdog" in alignment_d3d11_failed_performance_details(
        stale
    )

    cleared = alignment_d3d11_loading_cleared_performance("loading watchdog")
    assert cleared.summary == "D3D11 preview loading state cleared."
    assert cleared.details == "reason=loading watchdog"

    ready = alignment_d3d11_watchdog_ready_performance(
        quality_label="Archive Preview parity",
        reason="loading watchdog",
        active_package="pkg",
    )
    assert ready.summary == "D3D11 preview ready - Archive Preview parity - loaded before watchdog"
    assert ready.details == "reason=loading watchdog\nactive_package=pkg"

    waiting = alignment_d3d11_resources_waiting_performance("waiting details")
    assert waiting.summary == "D3D11 resources loaded; waiting for visible preview panel."
    assert waiting.details == "waiting details"

    restart = alignment_d3d11_restart_performance(
        quality_label="Archive Preview parity",
        stale_details=stale,
        restart_count=1,
    )
    assert restart.summary == "D3D11 preview reload restarted - Archive Preview parity"
    assert "restart=2/2" in restart.details

    failed = alignment_d3d11_failed_performance(
        quality_label="Archive Preview parity",
        stale_details=stale,
    )
    assert failed.summary == "D3D11 preview reload failed - Archive Preview parity"
    assert "no native loaded event arrived before the watchdog" in failed.details


def test_alignment_d3d11_loaded_timing_presentation_formats_summary_and_details() -> None:
    presentation = alignment_d3d11_loaded_timing_presentation(
        {
            "last_cache_event": "hit",
            "last_cache_reason": "material",
            "package_quality": "archive_parity",
            "preview_pipeline_stage": "ready",
            "prepare_ms": 12.25,
            "package_ms": 34.5,
        },
        {
            "textures": {"diffuse": 2, "normal": 0, "roughness": 1},
            "native_manifest_ms": 1.0,
            "native_texture_ms": 2.5,
            "native_geometry_ms": 3.25,
            "first_frame_ms": 4.5,
            "frame_count": 6,
            "render_suppressed_count": 1,
            "parent_health": "ok",
        },
        quality_label="Archive Preview parity",
        cache_label="cache hit",
        channel_debug="Material Channel Contract: roughness=green",
    )

    assert presentation.native_load_ms == 6.75
    assert presentation.texture_text == "diffuse:2 roughness:1"
    assert presentation.summary == (
        "D3D11 preview loaded - Archive Preview parity - archive_parity package - "
        "reason material - cache hit - native 7 ms - textures diffuse:2 roughness:1"
    )
    assert "cache=hit" in presentation.details
    assert "pipeline ready" in presentation.details
    assert "prepare 12.2 ms" in presentation.details
    assert "package 34.5 ms" in presentation.details
    assert "native_load_upload 6.8 ms" in presentation.details
    assert "frames 6" in presentation.details
    assert "render_suppressed 1" in presentation.details
    assert "parent_health ok" in presentation.details
    assert "channels roughness=green" in presentation.details


def test_alignment_d3d11_cached_reuse_and_loading_performance_text() -> None:
    reuse = alignment_d3d11_cached_reuse_performance(
        {"prepare_ms": 3.25, "package_ms": 4.5},
        quality_label="Fast geometry",
        rebuild_reason="texture_uv",
    )

    assert reuse.summary == "D3D11 cached preview package - Fast geometry - reason texture_uv"
    assert "cache=hit" in reuse.details
    assert "reason=texture_uv" in reuse.details
    assert "prepare 3.2 ms" in reuse.details
    assert "package 4.5 ms" in reuse.details
    assert "native load/upload 0.0 ms (active package reused)" in reuse.details

    loading = alignment_d3d11_cached_loading_performance("material")

    assert loading.summary == "D3D11 cached preview package loading - reason material"
    assert loading.details == "cache=hit\nreason=material"


def test_alignment_d3d11_package_loading_detail_prioritizes_quality_and_texture_state() -> None:
    assert (
        alignment_d3d11_package_loading_detail(
            package_quality="fast_geometry",
            high_quality_textures=True,
            mesh_edit_raw_package=False,
            fast_geometry_loaded=False,
        )
        == "building fast geometry"
    )
    assert (
        alignment_d3d11_package_loading_detail(
            package_quality="material_refresh",
            high_quality_textures=True,
            mesh_edit_raw_package=False,
            fast_geometry_loaded=True,
        )
        == "refreshing materials with cached geometry"
    )
    assert (
        alignment_d3d11_package_loading_detail(
            package_quality="archive_parity",
            high_quality_textures=True,
            mesh_edit_raw_package=True,
            fast_geometry_loaded=True,
        )
        == "building editable mesh materials"
    )
    assert (
        alignment_d3d11_package_loading_detail(
            package_quality="archive_parity",
            high_quality_textures=True,
            mesh_edit_raw_package=False,
            fast_geometry_loaded=True,
        )
        == "building full Archive Preview material parity in background"
    )
    assert (
        alignment_d3d11_package_loading_detail(
            package_quality="archive_parity",
            high_quality_textures=False,
            mesh_edit_raw_package=False,
            fast_geometry_loaded=False,
        )
        == "building mesh and low-res textures"
    )


def test_alignment_d3d11_package_preparing_performance_text() -> None:
    presentation = alignment_d3d11_package_preparing_performance(
        {"last_cache_event": "miss"},
        quality_label="Archive Preview parity",
        cache_label="cache miss",
        rebuild_reason="geometry",
    )

    assert presentation.summary == "D3D11 package preparing - Archive Preview parity - cache miss"
    assert "cache=miss" in presentation.details
    assert "reason=geometry" in presentation.details
    assert "Full material parity runs in a background worker" in presentation.details


def test_alignment_d3d11_reload_and_starting_performance_text() -> None:
    state = {"last_cache_event": "hit", "prepare_ms": 12.2, "package_ms": 33.8}

    reload_presentation = alignment_d3d11_reload_queued_performance(
        state,
        quality_label="Material refresh",
        cache_label="cache hit",
        package_quality="material_refresh",
        rebuild_reason="material",
        channel_debug="Material Channel Contract: roughness=green",
    )

    assert reload_presentation.summary == (
        "D3D11 reload queued - Material refresh - material_refresh package - "
        "reason material - cache hit - prepare 12 ms, package 34 ms"
    )
    assert "cache=hit" in reload_presentation.details
    assert "reason=material" in reload_presentation.details
    assert "Material Channel Contract: roughness=green" in reload_presentation.details

    starting = alignment_d3d11_starting_performance(
        state,
        quality_label="Archive Preview parity",
        cache_label="cache hit",
        package_quality="archive_parity",
        rebuild_reason="geometry",
    )

    assert starting.summary == (
        "Starting D3D11 preview - Archive Preview parity - archive_parity package - "
        "reason geometry - cache hit - prepare 12 ms, package 34 ms"
    )
    assert starting.details == "cache=hit\nreason=geometry"


def test_alignment_d3d11_startup_and_error_performance_text() -> None:
    pending = alignment_d3d11_pending_host_performance(
        rebuild_reason="geometry",
        host_detail="window_not_visible",
    )
    assert pending.summary == "D3D11 preview host pending layout before renderer start."
    assert pending.details == "reason=geometry\nhost=window_not_visible"

    unavailable = alignment_d3d11_unavailable_performance()
    assert unavailable.summary == "Native D3D11 unavailable."
    assert "Native D3D11 is required for live alignment preview." in unavailable.details
    assert "Defender quarantines" in unavailable.details

    startup_timeout = alignment_d3d11_startup_timeout_performance()
    assert startup_timeout.summary == "D3D11 startup timeout."
    assert "Native D3D11 startup timeout waiting for status." in startup_timeout.details
    assert "Defender quarantines" in startup_timeout.details

    package_failed = alignment_d3d11_package_failed_performance("bad package")
    assert package_failed.summary == "D3D11 package failed."
    assert package_failed.details == "bad package"

    live_mode = alignment_d3d11_live_display_mode_performance("overlay")
    assert live_mode.summary == "D3D11 display mode changed live: overlay"
    assert live_mode.details == "cache=live-command reason=display_mode"

    selection = alignment_d3d11_selection_highlight_performance()
    assert selection.summary == "Selection highlight updated."
    assert (
        selection.details
        == "Selection changes use live D3D11 highlight commands and do not rebuild the preview package."
    )


def test_alignment_d3d11_live_status_performance_text() -> None:
    settings_rebuild = alignment_d3d11_render_settings_rebuild_performance()
    assert settings_rebuild.summary == "D3D11 preview package rebuild queued for texture settings."
    assert settings_rebuild.details == "cache=material_dirty reason=render_settings"

    tuning = alignment_d3d11_render_tuning_live_performance()
    assert tuning.summary == "D3D11 render tuning applied without rebuilding preview package."
    assert tuning.details == "cache=live-command reason=render_tuning"

    flip_v = alignment_d3d11_texture_flip_v_live_performance()
    assert flip_v.summary == "D3D11 texture Flip V applied without rebuilding preview package."
    assert flip_v.details == ""

    dropped_detail = alignment_d3d11_stale_package_dropped_detail(
        reason="stale_drag",
        request_id=12,
        active_preview_alive=True,
    )
    assert dropped_detail == (
        "Stale D3D11 package dropped before display.\n"
        "reason=stale_drag\n"
        "request_id=12\n"
        "active_preview_alive=True"
    )
    dropped = alignment_d3d11_stale_package_dropped_performance(
        reason="stale_drag",
        request_id=12,
        active_preview_alive=True,
    )
    assert dropped.summary == "Dropped stale D3D11 preview package; rebuilding current preview."
    assert dropped.details == "reason=stale_drag\nrequest_id=12\nactive_preview_alive=True"

    renderer_error = alignment_d3d11_renderer_error_performance("renderer crashed")
    assert renderer_error.summary == "D3D11 renderer error."
    assert renderer_error.details == "renderer crashed"

    queued = alignment_d3d11_package_queued_performance(
        quality_label="Archive Preview parity",
        refresh_elapsed_ms=14.6,
    )
    assert queued.summary == "D3D11 package queued - Archive Preview parity - refresh 15 ms"
    assert queued.details == ""

    failed = alignment_d3d11_alignment_preview_failed_performance("preview crashed")
    assert failed.summary == "D3D11 alignment preview failed."
    assert failed.details == "preview crashed"


def test_alignment_d3d11_reload_progress_details_stay_in_presentation_state() -> None:
    assert alignment_d3d11_queued_preview_reload_detail("material") == (
        "Queued preview reload. reason=material"
    )
    assert alignment_d3d11_queued_latest_preview_reload_detail("texture_uv") == (
        "Queued latest preview reload. reason=texture_uv"
    )
    assert alignment_d3d11_cached_loading_progress_detail("geometry") == (
        "Loading cached package. reason=geometry"
    )
    assert alignment_d3d11_cached_renderer_reload_detail("material") == (
        "Reloading cached renderer package. reason=material"
    )
    assert alignment_d3d11_waiting_for_preview_panel_detail(
        rebuild_reason="material",
        host_detail="host pending",
        retry_count=3,
    ) == "reason=material\nhost=host pending\nretry=3"

    restart = alignment_d3d11_renderer_host_restart_performance(
        rebuild_reason="texture_uv",
        host_detail="old host",
    )
    assert restart.summary == "D3D11 renderer host not reusable; restarting."
    assert restart.details == "reason=texture_uv\nhost=old host"


def test_alignment_d3d11_loaded_package_transform_current_uses_request_generation() -> None:
    state = {"request_transform_generation": 1, "request_transform_generations": {5: 9}}

    assert alignment_d3d11_loaded_package_transform_current(state, {"committed": 8}, request_id=5) is True
    assert alignment_d3d11_loaded_package_transform_current(state, {"committed": 8}, request_id=6) is False


def test_alignment_d3d11_request_package_quality_remembers_normalized_values() -> None:
    state: dict[str, object] = {}

    alignment_d3d11_remember_request_package_quality(state, 7, " Mesh_Edit_Raw ")

    assert alignment_d3d11_request_package_quality(state, 7, fallback="normal") == "mesh_edit_raw"
    assert alignment_d3d11_request_package_quality(state, 9, fallback=" Fast ") == "fast"


def test_alignment_d3d11_begin_package_request_records_request_metadata() -> None:
    state: dict[str, object] = {
        "request_id": 4,
        "request_drag_generations": "bad",
        "request_transform_generations": "bad",
        "request_display_modes": "bad",
        "request_reasons": "bad",
        "request_package_qualities": "bad",
    }

    request_id = alignment_d3d11_begin_package_request(
        state,
        drag_generation=11,
        transform_generation=12,
        display_mode="overlay",
        reason="material",
        package_quality=" Fast_Geometry ",
    )

    assert request_id == 5
    assert state["request_id"] == 5
    assert state["request_drag_generation"] == 11
    assert state["request_drag_generations"] == {5: 11}
    assert state["request_transform_generation"] == 12
    assert state["request_transform_generations"] == {5: 12}
    assert state["request_display_modes"] == {5: "overlay"}
    assert state["request_reasons"] == {5: "material"}
    assert state["request_package_qualities"] == {5: "fast_geometry"}


def test_alignment_d3d11_queue_pending_request_records_latest_request() -> None:
    model = object()
    state: dict[str, object] = {"request_id": 2}

    request_id = alignment_d3d11_queue_pending_request(
        state,
        model=model,
        label="Live alignment preview",
        display_mode="overlay",
        reason="texture_uv",
        transform_generation=9,
        package_quality="material_refresh",
    )

    assert request_id == 3
    assert state["request_id"] == 3
    assert state["pending_model"] is model
    assert state["pending_label"] == "Live alignment preview"
    assert state["pending_display_mode"] == "overlay"
    assert state["pending_reason"] == "texture_uv"
    assert state["pending_transform_generation"] == 9
    assert state["pending_package_quality"] == "material_refresh"


def test_alignment_d3d11_prepare_active_package_resets_renderer_status_state() -> None:
    package = object()
    status_file = object()
    state: dict[str, object] = {
        "preview_loaded": True,
        "resources_loaded": True,
        "status_signature": (10, 20),
        "status_payload_text": "old",
    }

    alignment_d3d11_prepare_active_package(
        state,
        package=package,
        request_id=6,
        display_mode="overlay",
        package_quality="archive_parity",
        cache_key="cache-key",
        status_file=status_file,
    )

    assert state["active_package"] is package
    assert state["active_package_request_id"] == 6
    assert state["active_package_display_mode"] == "overlay"
    assert state["active_package_quality"] == "archive_parity"
    assert state["active_package_cache_key"] == "cache-key"
    assert state["status_file"] is status_file
    assert state["status_signature"] == (0, 0)
    assert state["status_payload_text"] == ""
    assert state["preview_loaded"] is False
    assert state["resources_loaded"] is False


def test_alignment_d3d11_active_package_snapshot_and_restore_only_active_fields() -> None:
    original_package = object()
    state: dict[str, object] = {
        "active_package": original_package,
        "active_package_request_id": 9,
        "active_package_display_mode": "side_by_side",
        "active_package_quality": "fast_geometry",
        "active_package_cache_key": "old-cache",
        "preview_loaded": True,
    }
    snapshot = alignment_d3d11_active_package_snapshot(state)

    alignment_d3d11_prepare_active_package(
        state,
        package=object(),
        request_id=10,
        display_mode="overlay",
        package_quality="archive_parity",
        cache_key="new-cache",
        status_file=object(),
    )
    alignment_d3d11_restore_active_package(state, snapshot)

    assert state["active_package"] is original_package
    assert state["active_package_request_id"] == 9
    assert state["active_package_display_mode"] == "side_by_side"
    assert state["active_package_quality"] == "fast_geometry"
    assert state["active_package_cache_key"] == "old-cache"
    assert state["preview_loaded"] is False


def test_alignment_d3d11_active_package_match_and_drop_cleanup_state(tmp_path) -> None:
    active_package = tmp_path / "active"
    active_package.mkdir()
    other_package = tmp_path / "other"
    other_package.mkdir()

    assert (
        alignment_d3d11_active_package_matches(
            process_active=True,
            active_package=active_package,
            package=active_package,
        )
        is True
    )
    assert (
        alignment_d3d11_active_package_matches(
            process_active=False,
            active_package=active_package,
            package=active_package,
        )
        is False
    )
    assert (
        alignment_d3d11_active_package_matches(
            process_active=True,
            active_package=active_package,
            package=other_package,
        )
        is False
    )

    keep_state = alignment_d3d11_package_drop_cleanup_state(
        package=active_package,
        active_package=active_package,
        process_active=True,
    )
    assert keep_state.package_path == active_package
    assert keep_state.active_package_matches is True
    assert keep_state.should_cleanup is False

    cleanup_state = alignment_d3d11_package_drop_cleanup_state(
        package=other_package,
        active_package=active_package,
        process_active=True,
    )
    assert cleanup_state.package_path == other_package
    assert cleanup_state.active_package_matches is False
    assert cleanup_state.should_cleanup is True

    invalid_state = alignment_d3d11_package_drop_cleanup_state(
        package=None,
        active_package=active_package,
        process_active=True,
    )
    assert invalid_state.package_path is None
    assert invalid_state.should_cleanup is False


def test_alignment_d3d11_clear_active_package_returns_package_and_clears_selected_fields() -> None:
    package = object()
    process = object()
    state: dict[str, object] = {
        "process": process,
        "active_package": package,
        "active_package_request_id": 8,
        "active_package_display_mode": "overlay",
        "active_package_quality": "archive_parity",
        "active_package_cache_key": "cache",
        "status_file": object(),
        "status_signature": (1, 2),
        "status_payload_text": "payload",
    }

    returned = alignment_d3d11_clear_active_package(
        state,
        clear_process=True,
        clear_request_id=False,
        clear_status=True,
    )

    assert returned is package
    assert state["process"] is None
    assert state["active_package"] is None
    assert state["active_package_request_id"] == 8
    assert state["active_package_display_mode"] == ""
    assert state["active_package_quality"] == ""
    assert state["active_package_cache_key"] == ""
    assert state["status_file"] is None
    assert state["status_signature"] == (0, 0)
    assert state["status_payload_text"] == ""


def test_alignment_d3d11_clear_active_package_can_preserve_process_and_status() -> None:
    process = object()
    status_file = object()
    state: dict[str, object] = {
        "process": process,
        "active_package": object(),
        "active_package_request_id": 8,
        "active_package_display_mode": "overlay",
        "active_package_quality": "archive_parity",
        "active_package_cache_key": "cache",
        "status_file": status_file,
    }

    alignment_d3d11_clear_active_package(state)

    assert state["process"] is process
    assert state["active_package_request_id"] == 0
    assert state["status_file"] is status_file


def test_alignment_d3d11_process_status_refs_record_and_clear() -> None:
    process = object()
    state: dict[str, object] = {"status_file": "status.json"}

    alignment_d3d11_record_process_ref(state, process)

    assert state["process"] is process

    alignment_d3d11_clear_process_status_refs(state)

    assert state["process"] is None
    assert state["status_file"] is None


def test_alignment_d3d11_record_status_payload_tracks_changes() -> None:
    state: dict[str, object] = {
        "status_signature": (1, 2),
        "status_payload_text": "old",
    }

    assert (
        alignment_d3d11_record_status_payload(
            state,
            signature=(1, 2),
            payload_text="old",
        )
        is False
    )
    assert (
        alignment_d3d11_record_status_payload(
            state,
            signature=(1, 3),
            payload_text="new",
        )
        is True
    )
    assert state["status_signature"] == (1, 3)
    assert state["status_payload_text"] == "new"


def test_alignment_d3d11_status_event_and_loaded_route_select_pipeline_and_actions() -> None:
    assert alignment_d3d11_status_event({"event": " Loaded "}) == "loaded"

    fast_ready = alignment_d3d11_loaded_status_route(
        loaded_quality="fast_geometry",
        active_request_id=3,
        drag_active=False,
        drag_reload_stale=False,
    )
    assert fast_ready.pipeline_stage == "fast_geometry"
    assert fast_ready.should_apply_ready_state is True
    assert fast_ready.should_queue_archive_parity is True
    assert fast_ready.progress_message == "Preview ready."
    assert fast_ready.progress_stage == "ready"

    deferred = alignment_d3d11_loaded_status_route(
        loaded_quality="archive_parity",
        active_request_id=3,
        drag_active=True,
        drag_reload_stale=False,
    )
    assert deferred.pipeline_stage == "archive_parity_ready"
    assert deferred.should_defer_for_drag is True
    assert deferred.should_apply_ready_state is False
    assert deferred.should_queue_archive_parity is False

    stale = alignment_d3d11_loaded_status_route(
        loaded_quality="material_refresh",
        active_request_id=3,
        drag_active=False,
        drag_reload_stale=True,
    )
    assert stale.pipeline_stage == "material_loading"
    assert stale.should_keep_live_transform is True
    assert stale.progress_message == "Preview loaded; keeping live transform."


def test_alignment_d3d11_resources_and_loading_status_routes_normalize_payloads() -> None:
    waiting = alignment_d3d11_resources_loaded_status_route(
        {
            "render_suppressed_reason": "parent_not_renderable",
            "parent_renderable": False,
        }
    )
    assert waiting.waiting_for_visible_panel is True
    assert waiting.active is False
    assert "render_suppressed_reason=parent_not_renderable" in waiting.detail

    first_frame = alignment_d3d11_resources_loaded_status_route(
        {
            "geometry_upload_ms": "12.25",
            "texture_bind_ms": "bad",
        }
    )
    assert first_frame.waiting_for_visible_panel is False
    assert first_frame.active is True
    assert "geometry_upload_ms=12.2" in first_frame.detail
    assert "texture_bind_ms=0.0" in first_frame.detail

    tooltip = alignment_d3d11_loading_status_route(
        {"message": "Already loaded", "percent": 5, "stage": "upload"},
        preview_loaded=True,
        loading_stuck=False,
    )
    assert tooltip.action == "tooltip"
    assert tooltip.progress_percent == 5

    stuck = alignment_d3d11_loading_status_route(
        {"message": "", "percent": "bad"},
        preview_loaded=False,
        loading_stuck=True,
    )
    assert stuck.action == "clear_stuck"
    assert stuck.message == "Loading native D3D11 alignment preview..."

    progress = alignment_d3d11_loading_status_route(
        {"message": "Uploading", "percent": 0, "stage": "textures"},
        preview_loaded=False,
        loading_stuck=False,
    )
    assert progress.action == "progress"
    assert progress.progress_percent == 82
    assert progress.stage == "textures"


def test_alignment_d3d11_unavailable_and_terminal_status_routes_select_ui_actions() -> None:
    ready = alignment_d3d11_unavailable_status_route(
        preview_loaded=True,
        loading_stuck=True,
        reason="missing status file",
    )
    assert ready.action == "ready"
    assert ready.message == "Preview ready."

    stuck = alignment_d3d11_unavailable_status_route(
        preview_loaded=False,
        loading_stuck=True,
        reason="unchanged status file",
    )
    assert stuck.action == "clear_stuck"
    assert stuck.message == "unchanged status file"

    read_error = alignment_d3d11_status_read_error_route(ValueError("bad json"))
    assert read_error.action == "read_error"
    assert read_error.message == "Preview status read failed: bad json"
    assert read_error.should_mark_preview_unloaded is False

    invalid = alignment_d3d11_invalid_status_payload_route()
    assert invalid.action == "ignore"
    assert invalid.message == ""

    error = alignment_d3d11_error_status_route("renderer crashed")
    assert error.action == "error"
    assert error.should_mark_preview_unloaded is True
    assert error.should_clear_pending_rebuild is True
    assert error.performance_message == "renderer crashed"

    closed = alignment_d3d11_closed_status_route("")
    assert closed.action == "closed"
    assert closed.message == "Preview closed."
    assert closed.should_clear_pending_rebuild is True


def test_alignment_d3d11_mark_active_cached_package_reused_sets_fast_geometry_flags() -> None:
    state: dict[str, object] = {
        "preview_loaded": False,
        "stale_reload_restart_count": 2,
        "archive_parity_ready": True,
    }

    quality = alignment_d3d11_mark_active_cached_package_reused(
        state,
        request_id=4,
        display_mode="replacement_only",
        package_quality="fast_geometry",
        cache_key="cache",
    )

    assert quality == "fast_geometry"
    assert state["active_package_request_id"] == 4
    assert state["active_package_display_mode"] == "replacement_only"
    assert state["active_package_quality"] == "fast_geometry"
    assert state["active_package_cache_key"] == "cache"
    assert state["preview_loaded"] is True
    assert state["stale_reload_restart_count"] == 0
    assert state["fast_geometry_loaded"] is True
    assert state["archive_parity_ready"] is False


def test_alignment_d3d11_mark_active_cached_package_reused_sets_archive_parity_flags() -> None:
    state: dict[str, object] = {"archive_parity_upgrade_queued": True}

    quality = alignment_d3d11_mark_active_cached_package_reused(
        state,
        request_id=5,
        display_mode="overlay",
        package_quality="archive_parity",
        cache_key="cache",
    )

    assert quality == "archive_parity"
    assert state["fast_geometry_loaded"] is True
    assert state["archive_parity_ready"] is True
    assert state["archive_parity_upgrade_queued"] is False


def test_alignment_d3d11_mark_loaded_package_sets_quality_flags_from_active_package() -> None:
    state: dict[str, object] = {
        "active_package_quality": "archive_parity",
        "archive_parity_upgrade_queued": True,
        "stale_reload_restart_count": 2,
    }

    quality = alignment_d3d11_mark_loaded_package(state)

    assert quality == "archive_parity"
    assert state["preview_loaded"] is True
    assert state["resources_loaded"] is True
    assert state["stale_reload_restart_count"] == 0
    assert state["fast_geometry_loaded"] is True
    assert state["archive_parity_ready"] is True
    assert state["archive_parity_upgrade_queued"] is False


def test_alignment_d3d11_mark_loaded_package_keeps_archive_parity_queue_for_material_refresh() -> None:
    state: dict[str, object] = {"archive_parity_upgrade_queued": True}

    quality = alignment_d3d11_mark_loaded_package(state, package_quality="material_refresh")

    assert quality == "material_refresh"
    assert state["fast_geometry_loaded"] is True
    assert state["archive_parity_ready"] is True
    assert state["archive_parity_upgrade_queued"] is True


def test_alignment_d3d11_status_event_flags_update_resources_and_preview_state() -> None:
    state: dict[str, object] = {"preview_loaded": False}

    alignment_d3d11_mark_preview_loaded(state)
    alignment_d3d11_mark_resources_loaded(state)
    alignment_d3d11_mark_preview_unloaded(state)

    assert state["resources_loaded"] is True
    assert state["preview_loaded"] is False


def test_alignment_d3d11_material_parity_state_resets_queues_and_clears() -> None:
    state: dict[str, object] = {
        "fast_geometry_loaded": True,
        "archive_parity_ready": True,
        "archive_parity_upgrade_queued": True,
    }

    alignment_d3d11_reset_material_parity_state(state)

    assert state["fast_geometry_loaded"] is False
    assert state["archive_parity_ready"] is False
    assert state["archive_parity_upgrade_queued"] is False
    assert alignment_d3d11_begin_archive_parity_upgrade(state) is True
    assert alignment_d3d11_begin_archive_parity_upgrade(state) is False
    alignment_d3d11_clear_archive_parity_upgrade(state)
    assert state["archive_parity_upgrade_queued"] is False


def test_alignment_d3d11_pending_process_retry_state_tracks_package_and_count() -> None:
    package = object()
    state: dict[str, object] = {"pending_process_retry_count": 2}

    retry_count = alignment_d3d11_record_pending_process_retry(state, package=package)

    assert retry_count == 3
    assert state["pending_process_retry_count"] == 3
    assert state["pending_process_package"] is package

    alignment_d3d11_clear_pending_process_retry(state)

    assert state["pending_process_retry_count"] == 0
    assert state["pending_process_package"] is None


def test_alignment_d3d11_queue_preview_request_sets_queued_fields_without_incrementing_request() -> None:
    model = object()
    state: dict[str, object] = {
        "request_id": 4,
        "next_rebuild_reason": "material",
    }

    alignment_d3d11_queue_preview_request(
        state,
        model=model,
        label="Preview",
        display_mode="overlay",
        reason="geometry",
        transform_generation=7,
        package_quality="fast_geometry",
    )

    assert state["request_id"] == 4
    assert state["next_rebuild_reason"] == ""
    assert state["queued_model"] is model
    assert state["queued_label"] == "Preview"
    assert state["queued_display_mode"] == "overlay"
    assert state["queued_reason"] == "geometry"
    assert state["queued_transform_generation"] == 7
    assert state["queued_package_quality"] == "fast_geometry"


def test_alignment_d3d11_mark_rebuild_reason_sets_first_normalized_reason() -> None:
    state: dict[str, object] = {}

    assert alignment_d3d11_mark_rebuild_reason(state, " Material ") == "material"
    assert state["next_rebuild_reason"] == "material"
    assert alignment_d3d11_mark_rebuild_reason(state, "texture_uv") == "texture_uv"
    assert state["next_rebuild_reason"] == "material"
    state["next_rebuild_reason"] = ""
    assert alignment_d3d11_mark_rebuild_reason(state, "unknown") == "geometry"
    assert state["next_rebuild_reason"] == "geometry"


def test_alignment_d3d11_clear_queued_preview_request_clears_only_queued_fields() -> None:
    state: dict[str, object] = {
        "request_id": 4,
        "queued_model": object(),
        "queued_label": "Preview",
        "queued_display_mode": "overlay",
        "queued_reason": "geometry",
        "queued_transform_generation": 7,
        "queued_package_quality": "fast_geometry",
    }

    alignment_d3d11_clear_queued_preview_request(state)

    assert state["request_id"] == 4
    assert state["queued_model"] is None
    assert state["queued_label"] == ""
    assert state["queued_display_mode"] == ""
    assert state["queued_reason"] == ""
    assert state["queued_transform_generation"] == 0
    assert state["queued_package_quality"] == ""


def test_alignment_d3d11_take_pending_request_returns_values_and_clears_pending_fields() -> None:
    model = object()
    state: dict[str, object] = {
        "request_id": 4,
        "pending_model": model,
        "pending_label": "Preview",
        "pending_display_mode": "overlay",
        "pending_reason": "material",
        "pending_transform_generation": 7,
        "pending_package_quality": "fast_geometry",
    }

    pending_request = alignment_d3d11_take_pending_request(
        state,
        label_fallback="Fallback",
        display_mode_fallback="side_by_side",
    )

    assert pending_request == {
        "model": model,
        "label": "Preview",
        "display_mode": "overlay",
        "reason": "material",
        "transform_generation": 7,
        "package_quality": "fast_geometry",
    }
    assert state["request_id"] == 4
    assert state["pending_model"] is None
    assert state["pending_label"] == ""
    assert state["pending_display_mode"] == ""
    assert state["pending_reason"] == ""
    assert state["pending_transform_generation"] == 0
    assert state["pending_package_quality"] == ""


def test_alignment_d3d11_take_pending_request_uses_fallbacks() -> None:
    pending_request = alignment_d3d11_take_pending_request(
        {},
        label_fallback="Fallback",
        display_mode_fallback="side_by_side",
    )

    assert pending_request["label"] == "Fallback"
    assert pending_request["display_mode"] == "side_by_side"
    assert pending_request["reason"] == "geometry"
    assert pending_request["transform_generation"] == 0


def test_alignment_d3d11_package_worker_refs_record_and_clear() -> None:
    worker = object()
    thread = object()
    state: dict[str, object] = {}

    alignment_d3d11_record_package_worker_refs(state, worker=worker, thread=thread)

    assert state["worker"] is worker
    assert state["thread"] is thread

    alignment_d3d11_clear_package_worker_refs(state)

    assert state["worker"] is None
    assert state["thread"] is None


def test_alignment_d3d11_original_texture_worker_request_and_refs() -> None:
    worker = object()
    thread = object()
    state: dict[str, object] = {"original_texture_worker_request_id": "4"}

    assert alignment_d3d11_next_original_texture_worker_request_id(state) == 5
    assert alignment_d3d11_next_original_texture_worker_request_id(state) == 6
    assert state["original_texture_worker_request_id"] == 6
    assert alignment_d3d11_original_texture_worker_request_current(state, 6) is True
    assert alignment_d3d11_original_texture_worker_request_current(state, "6") is True
    assert alignment_d3d11_original_texture_worker_request_current(state, 5) is False

    alignment_d3d11_record_original_texture_worker_refs(state, worker=worker, thread=thread)

    assert state["original_texture_worker"] is worker
    assert state["original_texture_thread"] is thread

    alignment_d3d11_clear_original_texture_worker_refs(state)

    assert state["original_texture_worker"] is None
    assert state["original_texture_thread"] is None


def test_alignment_d3d11_record_stale_reload_restart_increments_count() -> None:
    state: dict[str, object] = {"stale_reload_restart_count": 2}

    restart_count = alignment_d3d11_record_stale_reload_restart(state)

    assert restart_count == 3
    assert state["stale_reload_restart_count"] == 3


def test_alignment_d3d11_reset_request_state_clears_queued_pending_and_request_maps() -> None:
    state: dict[str, object] = {
        "request_id": 3,
        "queued_model": object(),
        "queued_label": "queued",
        "queued_display_mode": "replacement_only",
        "queued_reason": "geometry",
        "queued_transform_generation": 9,
        "queued_package_quality": "fast_geometry",
        "pending_model": object(),
        "pending_label": "pending",
        "pending_display_mode": "overlay",
        "pending_reason": "material",
        "pending_transform_generation": 8,
        "pending_package_quality": "archive_parity",
        "active_package_request_id": 3,
        "active_package_display_mode": "overlay",
        "active_package_quality": "fast_geometry",
        "active_package_cache_key": "cache",
        "request_display_modes": {3: "overlay"},
        "request_package_qualities": {3: "fast_geometry"},
        "request_reasons": {3: "material"},
        "request_cache_keys": {3: "cache"},
        "source_to_d3d11_ids": {0: 10},
        "d3d11_id_to_source_indices": {10: (0,)},
        "preview_loaded": True,
        "loading_percent": 50,
        "loading_stage": "load",
        "loading_message": "loading",
    }

    alignment_d3d11_reset_request_state(
        state,
        increment_request=True,
        clear_loading=True,
        clear_active_metadata=True,
        clear_mapping_ids=True,
    )

    assert state["request_id"] == 4
    assert state["queued_model"] is None
    assert state["queued_label"] == ""
    assert state["queued_display_mode"] == ""
    assert state["queued_reason"] == ""
    assert state["queued_transform_generation"] == 0
    assert state["queued_package_quality"] == ""
    assert state["pending_model"] is None
    assert state["pending_label"] == ""
    assert state["pending_display_mode"] == ""
    assert state["pending_reason"] == ""
    assert state["pending_transform_generation"] == 0
    assert state["pending_package_quality"] == ""
    assert state["active_package_request_id"] == 0
    assert state["active_package_display_mode"] == ""
    assert state["active_package_quality"] == ""
    assert state["active_package_cache_key"] == ""
    assert state["request_display_modes"] == {}
    assert state["request_package_qualities"] == {}
    assert state["request_reasons"] == {}
    assert state["request_cache_keys"] == {}
    assert state["source_to_d3d11_ids"] == {}
    assert state["d3d11_id_to_source_indices"] == {}
    assert state["preview_loaded"] is False
    assert state["loading_percent"] == 0
    assert state["loading_stage"] == ""
    assert state["loading_message"] == ""


def test_alignment_d3d11_reset_request_state_can_preserve_request_id_and_loading_status() -> None:
    state: dict[str, object] = {
        "request_id": 3,
        "active_package_request_id": 3,
        "preview_loaded": True,
        "loading_percent": 50,
        "active_package_display_mode": "overlay",
        "source_to_d3d11_ids": {0: 10},
    }

    alignment_d3d11_reset_request_state(
        state,
        increment_request=False,
        clear_loading=False,
        clear_active_request_id=False,
    )

    assert state["request_id"] == 3
    assert state["active_package_request_id"] == 3
    assert state["preview_loaded"] is True
    assert state["loading_percent"] == 50
    assert state["active_package_display_mode"] == "overlay"
    assert state["source_to_d3d11_ids"] == {0: 10}


def test_alignment_d3d11_raw_package_active_or_pending_checks_active_queued_pending_and_requests() -> None:
    assert alignment_d3d11_raw_package_active_or_pending({"active_package_quality": "mesh_edit_raw"}) is True
    assert alignment_d3d11_raw_package_active_or_pending({"queued_package_quality": "MESH_EDIT_RAW"}) is True
    assert alignment_d3d11_raw_package_active_or_pending({"pending_package_quality": "mesh_edit_raw"}) is True
    assert (
        alignment_d3d11_raw_package_active_or_pending({"request_package_qualities": {2: "mesh_edit_raw"}})
        is True
    )
    assert alignment_d3d11_raw_package_active_or_pending({"request_package_qualities": {2: "normal"}}) is False


def test_mesh_edit_raw_preview_transition_routes_texture_restore_and_raw_refresh() -> None:
    unchanged = mesh_edit_raw_preview_transition_route(
        False,
        False,
        raw_package_active_or_pending=True,
    )
    assert unchanged.changed is False
    assert unchanged.should_queue_static_preview_refresh is False
    assert unchanged.should_stop_raw_package is False
    assert unchanged.should_queue_texture_preview_refresh is False

    enabled = mesh_edit_raw_preview_transition_route(
        False,
        True,
        raw_package_active_or_pending=False,
    )
    assert enabled.changed is True
    assert enabled.should_clear_static_preview_caches is True
    assert enabled.should_invalidate_package_cache is True
    assert enabled.should_queue_static_preview_refresh is True
    assert enabled.should_stop_raw_package is False
    assert enabled.should_queue_texture_preview_refresh is False

    disabled = mesh_edit_raw_preview_transition_route(
        True,
        False,
        raw_package_active_or_pending=True,
    )
    assert disabled.changed is True
    assert disabled.should_clear_static_preview_caches is True
    assert disabled.should_invalidate_package_cache is True
    assert disabled.should_queue_static_preview_refresh is True
    assert disabled.should_stop_raw_package is True
    assert disabled.should_queue_texture_preview_refresh is True

    disabled_without_raw = mesh_edit_raw_preview_transition_route(
        True,
        False,
        raw_package_active_or_pending=False,
    )
    assert disabled_without_raw.should_stop_raw_package is False
    assert disabled_without_raw.should_queue_static_preview_refresh is True
    assert disabled_without_raw.should_queue_texture_preview_refresh is True


def test_alignment_d3d11_mark_transform_changed_advances_generation_and_clears_pending_work() -> None:
    state = {
        "request_id": 3,
        "queued_model": object(),
        "queued_label": "queued",
        "queued_reason": "geometry",
        "queued_transform_generation": 7,
        "queued_package_quality": "fast_geometry",
        "pending_model": object(),
        "pending_label": "pending",
        "pending_reason": "material",
        "pending_transform_generation": 8,
        "pending_package_quality": "material_refresh",
        "request_package_qualities": {3: "fast_geometry"},
        "active_package_request_id": 9,
    }
    transform_generation = {"value": 4, "committed": 2}

    generation = alignment_d3d11_mark_transform_changed(state, transform_generation)

    assert generation == 5
    assert transform_generation == {"value": 5, "committed": 5}
    assert state["request_id"] == 4
    assert state["queued_model"] is None
    assert state["queued_label"] == ""
    assert state["queued_reason"] == ""
    assert state["queued_transform_generation"] == 0
    assert state["queued_package_quality"] == ""
    assert state["pending_model"] is None
    assert state["pending_label"] == ""
    assert state["pending_reason"] == ""
    assert state["pending_transform_generation"] == 0
    assert state["pending_package_quality"] == ""
    assert state["request_package_qualities"] == {}
    assert state["active_package_request_id"] == 9


def test_alignment_d3d11_drag_reload_stale_tracks_drag_and_transform_generations() -> None:
    state = {
        "request_drag_generation": 3,
        "request_drag_generations": {5: 10},
        "request_transform_generation": 2,
        "request_transform_generations": {5: 10},
    }

    assert alignment_d3d11_drag_reload_stale(state, {"active": True}, {"committed": 3}, {"committed": 2}) is True
    assert (
        alignment_d3d11_drag_reload_stale(
            state,
            {"active": False},
            {"committed": 11},
            {"committed": 2},
            request_id=5,
        )
        is True
    )
    assert (
        alignment_d3d11_drag_reload_stale(
            state,
            {"active": False},
            {"committed": 9},
            {"committed": 9},
            request_id=5,
        )
        is False
    )


def test_alignment_d3d11_request_reason_normalizes_known_reasons() -> None:
    state = {"request_reasons": {4: " Texture_UV ", 5: "invalid"}}

    assert alignment_d3d11_request_reason(state, request_id=4, fallback="material") == "texture_uv"
    assert alignment_d3d11_request_reason(state, request_id=5, fallback="material") == "geometry"
    assert alignment_d3d11_request_reason({}, request_id=0, fallback="mode_missing_original") == "mode_missing_original"


def test_alignment_d3d11_request_display_mode_uses_request_map_with_fallback() -> None:
    state = {"request_display_modes": {4: "overlay"}}

    assert alignment_d3d11_request_display_mode(state, 4, fallback="side_by_side") == "overlay"
    assert alignment_d3d11_request_display_mode(state, 5, fallback="side_by_side") == "side_by_side"
    assert alignment_d3d11_request_display_mode({}, 4, fallback="") == "side_by_side"


def test_alignment_d3d11_request_cache_key_reads_request_map() -> None:
    state = {"request_cache_keys": {4: "cache-key"}}

    assert alignment_d3d11_request_cache_key(state, 4) == "cache-key"
    assert alignment_d3d11_request_cache_key(state, 5) == ""
    assert alignment_d3d11_request_cache_key({}, 4) == ""


def test_alignment_d3d11_package_start_route_normalizes_gates_reason_and_generation() -> None:
    dropped = alignment_d3d11_package_start_route(
        dialog_live=False,
        preview_active=True,
        model_is_preview_data=True,
        display_mode="overlay",
        fallback_display_mode="side_by_side",
        reason="bad",
        transform_generation=None,
        current_transform_generation=7,
        active_request_id=3,
    )
    assert dropped.should_drop is True
    assert dropped.drop_reason == "dialog_closing_worker"
    assert dropped.should_start is False
    assert dropped.rebuild_reason == "geometry"
    assert dropped.transform_generation == 7

    inactive = alignment_d3d11_package_start_route(
        dialog_live=True,
        preview_active=False,
        model_is_preview_data=True,
        display_mode="",
        fallback_display_mode="replacement_only",
        reason="texture_uv",
        transform_generation="bad",
        current_transform_generation=4,
        active_request_id=3,
    )
    assert inactive.should_start is False
    assert inactive.should_drop is False
    assert inactive.display_mode == "replacement_only"
    assert inactive.rebuild_reason == "texture_uv"
    assert inactive.transform_generation == 4

    ready = alignment_d3d11_package_start_route(
        dialog_live=True,
        preview_active=True,
        model_is_preview_data=True,
        display_mode="overlay",
        fallback_display_mode="side_by_side",
        reason="material",
        transform_generation=9,
        current_transform_generation=4,
        active_request_id=3,
    )
    assert ready.should_start is True
    assert ready.display_mode == "overlay"
    assert ready.rebuild_reason == "material"
    assert ready.transform_generation == 9


def test_alignment_d3d11_process_start_route_and_reuse_state_cover_drop_pause_and_restart() -> None:
    assert alignment_d3d11_process_start_route(
        dialog_live=False,
        request_id=1,
        current_request_id=1,
        drag_active=False,
        drag_reload_stale=False,
    ).drop_reason == "dialog_closing"
    assert alignment_d3d11_process_start_route(
        dialog_live=True,
        request_id=2,
        current_request_id=1,
        drag_active=False,
        drag_reload_stale=False,
    ).drop_reason == "stale_request"
    active_drag = alignment_d3d11_process_start_route(
        dialog_live=True,
        request_id=1,
        current_request_id=1,
        drag_active=True,
        drag_reload_stale=False,
    )
    assert active_drag.drop_reason == "active_drag"
    assert active_drag.should_pause_loading is True
    assert active_drag.pause_message == "Preview reload paused during movement."
    assert alignment_d3d11_process_start_route(
        dialog_live=True,
        request_id=1,
        current_request_id=1,
        drag_active=False,
        drag_reload_stale=True,
    ).should_handle_stale_drag is True
    assert alignment_d3d11_process_start_route(
        dialog_live=True,
        request_id=0,
        current_request_id=1,
        drag_active=False,
        drag_reload_stale=False,
    ).should_start is True

    assert alignment_d3d11_process_reuse_state(
        process_active=True,
        host_ready=True,
        host_detail="ready",
    ).can_reuse_process is True
    restart = alignment_d3d11_process_reuse_state(
        process_active=True,
        host_ready=False,
        host_detail="hidden",
    )
    assert restart.should_report_restart is True
    assert restart.host_detail == "hidden"


def test_alignment_d3d11_package_ready_route_covers_drop_stale_and_accept() -> None:
    assert alignment_d3d11_package_ready_route(
        dialog_live=False,
        request_id=1,
        current_request_id=1,
        drag_reload_stale=False,
    ).drop_reason == "dialog_closing"
    assert alignment_d3d11_package_ready_route(
        dialog_live=True,
        request_id=2,
        current_request_id=1,
        drag_reload_stale=False,
    ).drop_reason == "stale_request"
    assert alignment_d3d11_package_ready_route(
        dialog_live=True,
        request_id=1,
        current_request_id=1,
        drag_reload_stale=True,
    ).should_handle_stale_drag is True
    assert alignment_d3d11_package_ready_route(
        dialog_live=True,
        request_id=1,
        current_request_id=1,
        drag_reload_stale=False,
    ).should_accept is True


def test_alignment_d3d11_process_request_metadata_and_native_ref_cache_key() -> None:
    state = {
        "request_display_modes": {4: "overlay"},
        "request_package_qualities": {4: "archive_parity"},
        "request_reasons": {4: "material"},
        "request_cache_keys": {4: "cache"},
    }

    metadata = alignment_d3d11_process_request_metadata(
        state,
        4,
        display_mode_fallback="side_by_side",
        package_quality_fallback="normal",
        rebuild_reason_fallback="geometry",
    )

    assert metadata.display_mode == "overlay"
    assert metadata.package_quality == "archive_parity"
    assert metadata.rebuild_reason == "material"
    assert metadata.cache_key == "cache"
    assert alignment_d3d11_cache_key_with_native_reference(
        "cache",
        native_reference_signature_hash="abc123",
    ) == "cache|native_ref=abc123|original_reference_native_splice=disabled_v2"
    assert alignment_d3d11_cache_key_with_native_reference("cache") == (
        "cache|original_reference_native_splice=disabled_v2"
    )


def test_alignment_d3d11_remember_request_cache_key_replaces_invalid_map() -> None:
    state: dict[str, object] = {"request_cache_keys": "bad"}

    alignment_d3d11_remember_request_cache_key(state, 6, "cache-key")

    assert state["request_cache_keys"] == {6: "cache-key"}
    assert alignment_d3d11_request_cache_key(state, 6) == "cache-key"


def test_alignment_d3d11_theme_payload_uses_fixed_preview_colors() -> None:
    assert alignment_d3d11_theme_payload("#15191d", "#c8d3df") == {
        "background": "#15191d",
        "text": "#c8d3df",
    }


def test_alignment_d3d11_global_fast_transform_pending_requires_global_payload() -> None:
    assert alignment_d3d11_global_fast_transform_pending({}) is False
    assert alignment_d3d11_global_fast_transform_pending({"pending_fast_transform": {"source_submesh_indices": (1,)}}) is False
    assert alignment_d3d11_global_fast_transform_pending({"pending_fast_transform": {"source_submesh_indices": ()}}) is True


def test_alignment_d3d11_clear_fast_transform_state_clears_pending_payloads() -> None:
    state = {
        "pending_fast_transform": {"offset": (1.0, 2.0, 3.0)},
        "pending_part_fast_transforms": {2: {"offset": (4.0, 5.0, 6.0)}},
        "preview_loaded": True,
    }

    alignment_d3d11_clear_fast_transform_state(state)

    assert state["pending_fast_transform"] is None
    assert state["pending_part_fast_transforms"] == {}
    assert state["preview_loaded"] is True


def test_alignment_d3d11_record_fast_transform_payload_routes_global_and_part_state() -> None:
    global_payload = {"source_submesh_indices": (), "translation": (1.0, 0.0, 0.0)}
    part_payload = {"source_submesh_indices": (2, "1", -1), "translation": (0.0, 1.0, 0.0)}
    state: dict[str, object] = {"pending_part_fast_transforms": "bad"}

    assert alignment_d3d11_record_fast_transform_payload(state, global_payload) == ()
    assert state["pending_fast_transform"] is global_payload
    assert alignment_d3d11_record_fast_transform_payload(state, part_payload) == (1, 2)
    assert state["pending_part_fast_transforms"] == {1: part_payload, 2: part_payload}


def test_alignment_d3d11_fast_transform_queue_state_records_and_routes_send() -> None:
    global_payload = {"source_submesh_indices": (), "translation": (1.0, 0.0, 0.0)}
    part_payload = {"source_submesh_indices": (3, 2), "translation": (0.0, 1.0, 0.0)}
    state: dict[str, object] = {}

    assert alignment_d3d11_fast_transform_queue_state(
        state,
        global_payload,
        preview_active=True,
        drag_active=False,
    ) == {"source_indices": (), "send_preview": True}
    assert state["pending_fast_transform"] is global_payload
    assert alignment_d3d11_fast_transform_queue_state(
        state,
        part_payload,
        preview_active=True,
        drag_active=True,
    ) == {"source_indices": (2, 3), "send_preview": False}
    assert state["pending_part_fast_transforms"] == {2: part_payload, 3: part_payload}


def test_alignment_d3d11_fast_transform_preview_state_builds_global_and_part_payloads() -> None:
    state: dict[str, object] = {
        "pending_fast_transform": {
            "translation": (1.0, 2.0, 3.0),
            "rotation_degrees": (4.0, 5.0, 6.0),
            "scale_xyz": (2.0, 2.0, 2.0),
        },
        "pending_part_fast_transforms": {
            3: {"translation": (7.0, 8.0, 9.0)},
            1: {"rotation_degrees": (10.0, 11.0, 12.0), "scale_xyz": (3.0, 3.0, 3.0)},
        },
    }

    result = alignment_d3d11_fast_transform_preview_state(
        state,
        lambda source_indices: tuple(index + 10 for index in source_indices),
    )

    assert result == (
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
        (2.0, 2.0, 2.0),
        [
            {
                "source_submesh_indices": (11,),
                "translation": (0.0, 0.0, 0.0),
                "rotation_degrees": (10.0, 11.0, 12.0),
                "scale_xyz": (3.0, 3.0, 3.0),
            },
            {
                "source_submesh_indices": (13,),
                "translation": (7.0, 8.0, 9.0),
                "rotation_degrees": (0.0, 0.0, 0.0),
                "scale_xyz": (1.0, 1.0, 1.0),
            },
        ],
    )


def test_alignment_d3d11_fast_transform_preview_state_skips_missing_editor_ids() -> None:
    state = {
        "pending_fast_transform": "bad",
        "pending_part_fast_transforms": {
            1: {"translation": (1.0, 0.0, 0.0)},
            2: {"translation": (2.0, 0.0, 0.0)},
            3: "bad",
        },
    }

    result = alignment_d3d11_fast_transform_preview_state(
        state,
        lambda source_indices: () if tuple(source_indices) == (2,) else tuple(source_indices),
    )

    assert result == (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        [
            {
                "source_submesh_indices": (1,),
                "translation": (1.0, 0.0, 0.0),
                "rotation_degrees": (0.0, 0.0, 0.0),
                "scale_xyz": (1.0, 1.0, 1.0),
            },
        ],
    )


def test_alignment_d3d11_fast_transform_preview_state_ignores_editor_id_resolver_errors() -> None:
    state = {
        "pending_part_fast_transforms": {
            1: {"translation": (1.0, 0.0, 0.0)},
        },
    }

    def broken_resolver(_source_indices):
        raise TypeError("'NoneType' object is not callable")

    assert alignment_d3d11_fast_transform_preview_state(state, broken_resolver) == (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        [],
    )


def test_alignment_d3d11_fast_transform_send_state_builds_scope_and_transform_payload() -> None:
    state: dict[str, object] = {
        "pending_fast_transform": {
            "translation": (1.0, 2.0, 3.0),
            "rotation_degrees": (4.0, 5.0, 6.0),
            "scale_xyz": (2.0, 2.0, 2.0),
        },
        "pending_part_fast_transforms": {
            2: {"translation": (7.0, 8.0, 9.0)},
        },
    }

    assert alignment_d3d11_fast_transform_send_state(
        state,
        lambda source_indices: tuple(index + 20 for index in source_indices),
        scope_source_indices=("2", 4),
    ) == {
        "update_scope": True,
        "scope_source_indices": (22, 24),
        "translation": (1.0, 2.0, 3.0),
        "rotation_degrees": (4.0, 5.0, 6.0),
        "scale_xyz": (2.0, 2.0, 2.0),
        "part_transforms": [
            {
                "source_submesh_indices": (22,),
                "translation": (7.0, 8.0, 9.0),
                "rotation_degrees": (0.0, 0.0, 0.0),
                "scale_xyz": (1.0, 1.0, 1.0),
            }
        ],
    }
    assert alignment_d3d11_fast_transform_send_state(
        state,
        lambda source_indices: tuple(source_indices),
    )["update_scope"] is False


def test_alignment_d3d11_fast_transform_send_state_ignores_bad_scope_editor_ids() -> None:
    state: dict[str, object] = {
        "pending_fast_transform": {
            "translation": (1.0, 2.0, 3.0),
        },
        "pending_part_fast_transforms": {
            2: {"translation": (7.0, 8.0, 9.0)},
        },
    }

    def broken_resolver(_source_indices):
        raise TypeError("'NoneType' object is not callable")

    assert alignment_d3d11_fast_transform_send_state(
        state,
        broken_resolver,
        scope_source_indices=(2,),
    ) == {
        "update_scope": True,
        "scope_source_indices": (),
        "translation": (1.0, 2.0, 3.0),
        "rotation_degrees": (0.0, 0.0, 0.0),
        "scale_xyz": (1.0, 1.0, 1.0),
        "part_transforms": [],
    }


def test_alignment_d3d11_fast_transform_replay_state_routes_clear_send_or_noop() -> None:
    assert alignment_d3d11_fast_transform_replay_state(
        {"pending_fast_transform": {"translation": (1.0, 0.0, 0.0)}},
        mesh_edit_raw_active=True,
        preview_active=True,
    ) == {"clear_state": True, "reset_host": True, "send_preview": False}
    assert alignment_d3d11_fast_transform_replay_state(
        {"pending_part_fast_transforms": {2: {"translation": (0.0, 1.0, 0.0)}}},
        mesh_edit_raw_active=False,
        preview_active=True,
    ) == {"clear_state": False, "reset_host": False, "send_preview": True}
    assert alignment_d3d11_fast_transform_replay_state(
        {"pending_fast_transform": "bad", "pending_part_fast_transforms": {}},
        mesh_edit_raw_active=False,
        preview_active=True,
    ) == {"clear_state": False, "reset_host": False, "send_preview": False}


def test_alignment_d3d11_view_state_reset_needed_tracks_generation() -> None:
    state: dict[str, object] = {"mesh_editor_view_state_reset_generation": 2}

    assert alignment_d3d11_view_state_reset_needed(state, 2) is False
    assert alignment_d3d11_view_state_reset_needed(state, 3) is True
    assert state["mesh_editor_view_state_reset_generation"] == 3


def test_alignment_d3d11_view_state_routes_separate_generation_from_qt_snapshot_work() -> None:
    state: dict[str, object] = {"mesh_editor_view_state_reset_generation": 2}

    ignored = alignment_d3d11_view_state_payload_route(
        state,
        2,
        payload_is_mapping=False,
    )
    assert ignored.action == "ignore"
    assert ignored.should_ignore is True

    reset = alignment_d3d11_view_state_payload_route(
        state,
        3,
        payload_is_mapping=True,
    )
    assert reset.action == "reset_generation"
    assert reset.should_clear_saved_state is True
    assert reset.should_store_snapshot is False
    assert state["mesh_editor_view_state_reset_generation"] == 3

    store = alignment_d3d11_view_state_payload_route(
        state,
        3,
        payload_is_mapping=True,
    )
    assert store.action == "store_snapshot"
    assert store.should_clear_saved_state is True
    assert store.should_store_snapshot is True

    saved = alignment_d3d11_saved_view_state_route(
        state,
        3,
        has_saved_state=True,
    )
    assert saved.action == "return_saved"
    assert saved.should_return_saved_state is True

    empty = alignment_d3d11_saved_view_state_route(
        state,
        3,
        has_saved_state=False,
    )
    assert empty.action == "empty"
    assert empty.should_return_saved_state is False


def test_alignment_d3d11_mode_refresh_needed_detects_original_required_package_gaps() -> None:
    assert alignment_d3d11_mode_requires_original("side_by_side") is True
    assert alignment_d3d11_mode_requires_original("replacement_only") is False
    assert alignment_d3d11_package_mode_has_original("overlay") is True
    assert alignment_d3d11_package_mode_has_original("replacement_only") is False
    assert (
        alignment_d3d11_mode_refresh_needed(
            {"active_package": object(), "active_package_display_mode": "replacement_only"},
            "side_by_side",
            queued_model_active=False,
            pending_model_active=False,
            mesh_edit_raw_preview_active=True,
        )
        is True
    )
    assert (
        alignment_d3d11_mode_refresh_needed(
            {"queued_display_mode": "replacement_only"},
            "overlay",
            queued_model_active=True,
            pending_model_active=False,
            mesh_edit_raw_preview_active=True,
        )
        is True
    )
    assert (
        alignment_d3d11_mode_refresh_needed(
            {"pending_display_mode": "replacement_only"},
            "overlay",
            queued_model_active=False,
            pending_model_active=True,
            mesh_edit_raw_preview_active=True,
        )
        is True
    )


def test_alignment_d3d11_mode_refresh_needed_tracks_stale_mesh_edit_raw_package() -> None:
    assert (
        alignment_d3d11_mode_refresh_needed(
            {
                "active_package": object(),
                "active_package_display_mode": "side_by_side",
                "active_package_quality": "mesh_edit_raw",
            },
            "side_by_side",
            queued_model_active=False,
            pending_model_active=False,
            mesh_edit_raw_preview_active=False,
        )
        is True
    )
    assert (
        alignment_d3d11_mode_refresh_needed(
            {"active_package": object(), "active_package_display_mode": "side_by_side"},
            "replacement_only",
            queued_model_active=True,
            pending_model_active=True,
            mesh_edit_raw_preview_active=False,
        )
        is False
    )


def test_alignment_d3d11_preview_mode_static_refresh_needed_requires_live_or_pending_work() -> None:
    assert (
        alignment_d3d11_preview_mode_static_refresh_needed(
            {"active_package": object()},
            mode_refresh_needed=False,
            renderer_active=False,
            queued_model_active=False,
            pending_model_active=False,
        )
        is False
    )
    assert (
        alignment_d3d11_preview_mode_static_refresh_needed(
            {},
            mode_refresh_needed=False,
            renderer_active=True,
            queued_model_active=False,
            pending_model_active=False,
        )
        is False
    )
    assert (
        alignment_d3d11_preview_mode_static_refresh_needed(
            {},
            mode_refresh_needed=True,
            renderer_active=True,
            queued_model_active=True,
            pending_model_active=True,
        )
        is True
    )
    assert (
        alignment_d3d11_preview_mode_static_refresh_needed(
            {},
            mode_refresh_needed=False,
            renderer_active=False,
            queued_model_active=False,
            pending_model_active=False,
        )
        is True
    )


def test_alignment_d3d11_request_active_checks_any_live_request_source() -> None:
    assert (
        alignment_d3d11_request_active(
            process_active=False,
            thread_active=False,
            queued_model_active=False,
            pending_model_active=False,
            active_package_exists=False,
        )
        is False
    )
    assert (
        alignment_d3d11_request_active(
            process_active=False,
            thread_active=True,
            queued_model_active=False,
            pending_model_active=False,
            active_package_exists=False,
        )
        is True
    )
    assert (
        alignment_d3d11_request_active(
            process_active=False,
            thread_active=False,
            queued_model_active=True,
            pending_model_active=False,
            active_package_exists=False,
        )
        is True
    )
    assert (
        alignment_d3d11_request_active(
            process_active=False,
            thread_active=False,
            queued_model_active=False,
            pending_model_active=False,
            active_package_exists=True,
        )
        is True
    )


def test_alignment_d3d11_package_refresh_in_flight_requires_preview_active() -> None:
    assert (
        alignment_d3d11_package_refresh_in_flight(
            {},
            preview_active=False,
            queued_model_active=True,
            pending_model_active=False,
            thread_active=False,
            process_active=False,
            active_package_exists=False,
            committed_transform_generation=0,
        )
        is False
    )


def test_alignment_d3d11_package_refresh_in_flight_tracks_active_work() -> None:
    base = {
        "preview_active": True,
        "queued_model_active": False,
        "pending_model_active": False,
        "thread_active": False,
        "process_active": False,
        "active_package_exists": False,
        "committed_transform_generation": 0,
    }

    assert alignment_d3d11_package_refresh_in_flight({}, **{**base, "queued_model_active": True}) is True
    assert alignment_d3d11_package_refresh_in_flight({}, **{**base, "pending_model_active": True}) is True
    assert alignment_d3d11_package_refresh_in_flight({}, **{**base, "thread_active": True}) is True
    assert alignment_d3d11_package_refresh_in_flight({}, **{**base, "process_active": True}) is True
    assert alignment_d3d11_package_refresh_in_flight({}, **{**base, "active_package_exists": True}) is True
    assert alignment_d3d11_package_refresh_in_flight({"preview_loaded": True}, **{**base, "process_active": True}) is False


def test_alignment_d3d11_package_refresh_in_flight_tracks_transform_generation() -> None:
    state = {
        "preview_loaded": True,
        "active_package_request_id": 7,
        "request_transform_generation": 2,
        "request_transform_generations": {7: 4},
    }

    assert (
        alignment_d3d11_package_refresh_in_flight(
            state,
            preview_active=True,
            queued_model_active=False,
            pending_model_active=False,
            thread_active=False,
            process_active=False,
            active_package_exists=False,
            committed_transform_generation=5,
        )
        is True
    )
    assert (
        alignment_d3d11_package_refresh_in_flight(
            state,
            preview_active=True,
            queued_model_active=False,
            pending_model_active=False,
            thread_active=False,
            process_active=False,
            active_package_exists=False,
            committed_transform_generation=4,
        )
        is False
    )


def test_alignment_d3d11_live_frame_available_requires_loaded_process_and_package() -> None:
    assert (
        alignment_d3d11_live_frame_available(
            {"preview_loaded": True},
            process_active=True,
            active_package_exists=True,
        )
        is True
    )
    assert (
        alignment_d3d11_live_frame_available(
            {"preview_loaded": False},
            process_active=True,
            active_package_exists=True,
        )
        is False
    )
    assert (
        alignment_d3d11_live_frame_available(
            {"preview_loaded": True},
            process_active=False,
            active_package_exists=True,
        )
        is False
    )
    assert (
        alignment_d3d11_live_frame_available(
            {"preview_loaded": True},
            process_active=True,
            active_package_exists=False,
        )
        is False
    )


def test_alignment_d3d11_loading_stuck_handles_loaded_idle_frame() -> None:
    assert (
        alignment_d3d11_loading_stuck(
            loading_active=True,
            preview_loaded=True,
            queued_model_active=False,
            pending_model_active=False,
            thread_active=False,
            loading_started_at=0.0,
            loading_elapsed_s=0.0,
            timeout_s=6.0,
            request_active=False,
            process_active=False,
            active_package_exists=False,
        )
        is True
    )
    assert (
        alignment_d3d11_loading_stuck(
            loading_active=True,
            preview_loaded=True,
            queued_model_active=True,
            pending_model_active=False,
            thread_active=False,
            loading_started_at=0.0,
            loading_elapsed_s=0.0,
            timeout_s=6.0,
            request_active=False,
            process_active=False,
            active_package_exists=False,
        )
        is False
    )


def test_alignment_d3d11_loading_stuck_handles_elapsed_request_state() -> None:
    base = dict(
        loading_active=True,
        preview_loaded=False,
        queued_model_active=False,
        pending_model_active=False,
        thread_active=False,
        loading_started_at=10.0,
        timeout_s=6.0,
    )

    assert alignment_d3d11_loading_stuck(**base, loading_elapsed_s=2.0, request_active=False, process_active=False, active_package_exists=False) is False
    assert alignment_d3d11_loading_stuck(**base, loading_elapsed_s=7.0, request_active=False, process_active=False, active_package_exists=False) is True
    assert alignment_d3d11_loading_stuck(**base, loading_elapsed_s=7.0, request_active=True, process_active=False, active_package_exists=True) is False
    assert alignment_d3d11_loading_stuck(**base, loading_elapsed_s=7.0, request_active=True, process_active=True, active_package_exists=True) is True


def test_alignment_d3d11_stale_loading_restart_allowed_limits_retries_and_drag() -> None:
    assert alignment_d3d11_stale_loading_restart_allowed(restart_count=0, drag_active=False) is True
    assert alignment_d3d11_stale_loading_restart_allowed(restart_count=1, drag_active=False) is True
    assert alignment_d3d11_stale_loading_restart_allowed(restart_count=2, drag_active=False) is False
    assert alignment_d3d11_stale_loading_restart_allowed(restart_count=0, drag_active=True) is False


def test_alignment_d3d11_host_ready_state_reports_first_blocking_reason() -> None:
    assert alignment_d3d11_host_ready_state(
        dialog_live=False,
        host_visible=True,
        width=320,
        height=240,
        parent_hwnd=5,
    ).detail == "alignment dialog is closing"
    assert alignment_d3d11_host_ready_state(
        dialog_live=True,
        host_visible=False,
        width=320,
        height=240,
        parent_hwnd=5,
    ).detail == "preview host widget is hidden"
    assert alignment_d3d11_host_ready_state(
        dialog_live=True,
        host_visible=True,
        width=8,
        height=240,
        parent_hwnd=5,
    ).detail == "preview host widget is too small (8x240)"
    assert alignment_d3d11_host_ready_state(
        dialog_live=True,
        host_visible=True,
        width=320,
        height=240,
        parent_hwnd=0,
    ).detail == "preview host parent HWND is unavailable"
    assert alignment_d3d11_host_ready_state(
        dialog_live=True,
        host_visible=True,
        width=320,
        height=240,
        parent_hwnd=5,
        child_hwnd=0,
        require_child=True,
    ).detail == "native preview child HWND is unavailable"
    ready = alignment_d3d11_host_ready_state(
        dialog_live=True,
        host_visible=True,
        width=320,
        height=240,
        parent_hwnd=5,
        child_hwnd=7,
        require_child=True,
    )
    assert ready.ready is True
    assert ready.detail == "preview host is ready"


def test_alignment_d3d11_clear_stuck_loading_route_selects_single_action() -> None:
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=False,
        preview_loaded=False,
        resources_loaded=False,
        process_active=True,
        active_package_exists=True,
        host_ready=True,
        child_ready=True,
        restart_count=0,
        drag_active=False,
    ).action == "dialog_closed"
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=True,
        preview_loaded=False,
        resources_loaded=False,
        process_active=False,
        active_package_exists=False,
        host_ready=True,
        child_ready=True,
        restart_count=0,
        drag_active=False,
    ).should_report_idle is True
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=True,
        preview_loaded=True,
        resources_loaded=False,
        process_active=True,
        active_package_exists=True,
        host_ready=False,
        child_ready=False,
        restart_count=0,
        drag_active=False,
    ).should_restore_loaded_preview is True
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=True,
        preview_loaded=False,
        resources_loaded=True,
        process_active=True,
        active_package_exists=True,
        host_ready=True,
        child_ready=False,
        restart_count=0,
        drag_active=False,
    ).should_report_resources_waiting is True
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=True,
        preview_loaded=False,
        resources_loaded=False,
        process_active=True,
        active_package_exists=True,
        host_ready=True,
        child_ready=True,
        restart_count=1,
        drag_active=False,
    ).should_restart is True
    assert alignment_d3d11_clear_stuck_loading_route(
        dialog_live=True,
        preview_loaded=False,
        resources_loaded=False,
        process_active=True,
        active_package_exists=True,
        host_ready=True,
        child_ready=True,
        restart_count=2,
        drag_active=False,
    ).should_report_failed is True


def test_alignment_d3d11_loading_watchdog_snapshot_and_recovery_action_normalize_runtime_state() -> None:
    snapshot = alignment_d3d11_loading_watchdog_snapshot(
        {
            "active_package_request_id": "7",
            "preview_loaded": True,
            "resources_loaded": False,
            "loading_started_at": "10.5",
            "loading_percent": "84",
            "loading_stage": "",
            "stale_reload_restart_count": "1",
        },
        now_s=16.0,
    )

    assert snapshot.active_request_id == 7
    assert snapshot.preview_loaded is True
    assert snapshot.elapsed_s == 5.5
    assert snapshot.last_percent == 84
    assert snapshot.last_stage == "unknown"
    assert snapshot.restart_count == 1

    dialog_closed = alignment_d3d11_loading_recovery_action(
        alignment_d3d11_clear_stuck_loading_route(
            dialog_live=False,
            preview_loaded=False,
            resources_loaded=False,
            process_active=False,
            active_package_exists=False,
            host_ready=False,
            child_ready=False,
            restart_count=0,
            drag_active=False,
        )
    )
    assert dialog_closed.action == "dialog_closed"
    assert dialog_closed.should_mark_preview_unloaded is True
    assert dialog_closed.should_set_loading_inactive is True

    idle = alignment_d3d11_loading_recovery_action(
        alignment_d3d11_clear_stuck_loading_route(
            dialog_live=True,
            preview_loaded=False,
            resources_loaded=False,
            process_active=False,
            active_package_exists=False,
            host_ready=True,
            child_ready=True,
            restart_count=0,
            drag_active=False,
        )
    )
    assert idle.action == "idle"
    assert idle.should_reset_request_idle is True
    assert idle.loading_message == "Preview idle."

    restart = alignment_d3d11_loading_recovery_action(
        alignment_d3d11_clear_stuck_loading_route(
            dialog_live=True,
            preview_loaded=False,
            resources_loaded=False,
            process_active=True,
            active_package_exists=True,
            host_ready=True,
            child_ready=True,
            restart_count=0,
            drag_active=False,
        )
    )
    assert restart.action == "restart"
    assert restart.should_record_restart is True
    assert restart.should_stop_process is True
    assert restart.should_queue_latest_rebuild is True
    assert restart.detail_kind == "stale_loading"


def test_alignment_d3d11_process_runtime_routes_cover_timeout_finish_and_stale_reload() -> None:
    assert alignment_d3d11_start_timeout_route(
        dialog_live=True,
        status_matches=True,
        process_active=True,
        status_file_exists=False,
    ).should_report_timeout is True
    assert alignment_d3d11_start_timeout_route(
        dialog_live=True,
        status_matches=True,
        process_active=True,
        status_file_exists=True,
    ).should_report_timeout is False

    ignored_finish = alignment_d3d11_process_finished_route(
        current_process=False,
        widgets_live=True,
        exit_code=1,
    )
    assert ignored_finish.should_ignore is True

    failed_finish = alignment_d3d11_process_finished_route(
        current_process=True,
        widgets_live=True,
        exit_code=7,
    )
    assert failed_finish.should_poll_status is True
    assert failed_finish.should_cleanup is True
    assert failed_finish.should_report_error is True

    paused_reload = alignment_d3d11_stale_reload_route(
        dialog_live=True,
        drag_active=True,
        process_active=True,
        active_package_exists=True,
    )
    assert paused_reload.should_continue is False
    assert paused_reload.should_pause_loading is True

    live_reload = alignment_d3d11_stale_reload_route(
        dialog_live=True,
        drag_active=False,
        process_active=True,
        active_package_exists=True,
    )
    assert live_reload.should_continue is True
    assert live_reload.active_preview_alive is True


def test_alignment_d3d11_progress_update_normalizes_state_and_tooltip() -> None:
    state = {}

    message, tooltip, loading_active = alignment_d3d11_progress_update(
        state,
        42,
        "Building package",
        stage="package",
        detail="worker active",
    )

    assert message == "42% Building package"
    assert tooltip == "worker active\nstage=package\nprogress=42%"
    assert loading_active is True
    assert state == {
        "loading_percent": 42,
        "loading_stage": "package",
        "loading_message": "42% Building package",
    }


def test_alignment_d3d11_progress_update_clamps_and_finishes_at_100() -> None:
    state = {}

    message, tooltip, loading_active = alignment_d3d11_progress_update(
        state,
        120,
        "",
        active=True,
    )

    assert message == "100% Preparing preview"
    assert tooltip == "progress=100%"
    assert loading_active is False
    assert state["loading_percent"] == 100


def test_alignment_d3d11_loading_start_helpers_mark_clear_and_ensure() -> None:
    state: dict[str, object] = {}

    assert alignment_d3d11_ensure_loading_started(state, 10.5) == 10.5
    assert state["loading_started_at"] == 10.5
    assert alignment_d3d11_ensure_loading_started(state, 20.0) == 10.5
    assert alignment_d3d11_mark_loading_started(state, 22.0) == 22.0

    alignment_d3d11_clear_loading_start(state)

    assert state["loading_started_at"] == 0.0


def test_alignment_d3d11_pipeline_stage_normalizes_state() -> None:
    state: dict[str, object] = {}

    assert alignment_d3d11_pipeline_stage(state, " Native_Start ") == "native_start"
    assert state["preview_pipeline_stage"] == "native_start"
    assert alignment_d3d11_pipeline_stage(state, "") == "idle"


def test_alignment_d3d11_package_quality_prefers_mesh_edit_raw_package() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)

    result_settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {},
        reason="geometry",
        mesh_edit_raw_preview_active=True,
    )

    assert result_settings.use_textures_by_default is True
    assert high_quality is True
    assert material_combiner is True
    assert package_quality == "mesh_edit_raw"


def test_alignment_d3d11_render_settings_route_splits_package_rebuild_live_and_static() -> None:
    old_settings = ModelPreviewRenderSettings(disable_all_support_maps=False)
    new_settings = ModelPreviewRenderSettings(disable_all_support_maps=True)

    assert alignment_d3d11_package_settings_changed(old_settings, new_settings) is True
    assert alignment_d3d11_package_settings_changed(old_settings, old_settings) is False

    rebuild = alignment_d3d11_render_settings_route(
        d3d11_active=True,
        package_settings_changed=True,
    )
    assert rebuild.action == "d3d11_rebuild"
    assert rebuild.should_invalidate_package_cache is True
    assert rebuild.should_mark_rebuild_reason is True
    assert rebuild.should_queue_static_preview_refresh is True
    assert rebuild.should_apply_live_render_tuning is False
    assert rebuild.performance_kind == "rebuild"

    live = alignment_d3d11_render_settings_route(
        d3d11_active=True,
        package_settings_changed=False,
    )
    assert live.action == "d3d11_live"
    assert live.should_apply_live_render_tuning is True
    assert live.should_queue_static_preview_refresh is False

    static = alignment_d3d11_render_settings_route(
        d3d11_active=False,
        package_settings_changed=True,
    )
    assert static.action == "static"
    assert static.should_apply_static_widget_settings is True
    assert static.should_queue_static_preview_refresh is True


def test_alignment_preview_renderer_and_mode_routes_keep_qt_work_at_call_site() -> None:
    unavailable = alignment_preview_renderer_route(
        "d3d11",
        d3d11_available=False,
        d3d11_active=False,
    )
    assert unavailable.action == "unavailable"
    assert unavailable.should_report_unavailable is True
    assert unavailable.should_reset_d3d11_state is True
    assert unavailable.should_apply_static_preview_mode is True

    active = alignment_preview_renderer_route(
        "d3d11",
        d3d11_available=True,
        d3d11_active=True,
    )
    assert active.action == "d3d11"
    assert active.should_show_d3d11_preview is True
    assert active.should_sync_highlights is True
    assert active.should_queue_selection_preview_refresh is True

    live_mode = alignment_preview_mode_route(
        "overlay",
        d3d11_active=True,
        needs_static_refresh=False,
    )
    assert live_mode.should_set_live_d3d11_mode is True
    assert live_mode.should_mark_d3d11_rebuild is False
    assert live_mode.should_replay_fast_transform is True

    rebuild_mode = alignment_preview_mode_route(
        "side_by_side",
        d3d11_active=True,
        needs_static_refresh=True,
    )
    assert rebuild_mode.should_set_live_d3d11_mode is False
    assert rebuild_mode.should_mark_d3d11_rebuild is True
    assert rebuild_mode.should_queue_static_preview_refresh is True

    static_mode = alignment_preview_mode_route(
        "replacement_only",
        d3d11_active=False,
        needs_static_refresh=True,
    )
    assert static_mode.static_stack_index == 2
    assert static_mode.should_replay_fast_transform is False
    assert static_mode.should_queue_static_preview_refresh is True


def test_alignment_preview_widget_render_settings_disables_expensive_maps_when_interactive() -> None:
    settings = ModelPreviewRenderSettings(
        use_textures_by_default=True,
        high_quality_by_default=True,
        disable_all_support_maps=False,
        disable_normal_map=False,
        disable_material_map=False,
        disable_height_map=False,
        low_quality_texture_max_dimension=4096,
    )

    result = alignment_preview_widget_render_settings(settings, interactive=True)

    assert result is not settings
    assert result.disable_all_support_maps is True
    assert result.disable_normal_map is True
    assert result.disable_material_map is True
    assert result.disable_height_map is True
    assert result.low_quality_texture_max_dimension == 1024


def test_alignment_lit_render_settings_clones_model_preview_settings_or_uses_fallback() -> None:
    settings = ModelPreviewRenderSettings(low_quality_texture_max_dimension=2048)
    fallback = ModelPreviewRenderSettings(low_quality_texture_max_dimension=512)

    result = alignment_lit_render_settings(settings, fallback)

    assert result is not settings
    assert result.low_quality_texture_max_dimension == 2048
    fallback_result = alignment_lit_render_settings(object(), fallback)
    assert fallback_result is not fallback
    assert fallback_result.low_quality_texture_max_dimension == 512


def test_alignment_preview_widget_render_settings_preserves_settings_when_not_interactive() -> None:
    settings = ModelPreviewRenderSettings(low_quality_texture_max_dimension=2048)

    assert alignment_preview_widget_render_settings(settings, interactive=False) is settings


def test_alignment_d3d11_package_quality_uses_material_refresh_when_geometry_clean() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=False)

    _settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {"archive_parity_ready": True},
        reason="material",
        mesh_edit_raw_preview_active=False,
    )

    assert high_quality is False
    assert material_combiner is True
    assert package_quality == "material_refresh"


def test_alignment_d3d11_package_quality_uses_fast_geometry_before_parity() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)

    result_settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {"fast_geometry_loaded": False, "archive_parity_ready": False},
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert result_settings.use_textures_by_default is False
    assert result_settings.high_quality_by_default is False
    assert high_quality is False
    assert material_combiner is False
    assert package_quality == "fast_geometry"


def test_alignment_d3d11_package_quality_falls_back_to_archive_parity() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=False, high_quality_by_default=True)

    result_settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {"fast_geometry_loaded": True},
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert result_settings.use_textures_by_default is False
    assert high_quality is False
    assert material_combiner is False
    assert package_quality == "archive_parity"


def test_alignment_preview_quality_label_uses_active_package_then_fallback() -> None:
    assert alignment_preview_quality_label({"active_package_quality": "fast_geometry"}) == "Fast geometry"
    assert alignment_preview_quality_label({"active_package_quality": "archive_parity"}) == "Archive Preview parity"
    assert alignment_preview_quality_label({"active_package_quality": "material_refresh"}) == "Material refresh"
    assert alignment_preview_quality_label({"active_package_quality": "mesh_edit_raw"}) == "Editable mesh"
    assert alignment_preview_quality_label({"package_quality": "mesh_edit_raw"}) == "Editable mesh"
    assert alignment_preview_quality_label({}) == "Normal quality"


def test_live_alignment_preview_status_message_mentions_background_parity_load() -> None:
    message = live_alignment_preview_status_message()

    assert "fast geometry appears first" in message
    assert "Archive Preview material parity" in message
