"""D3D11 preview progress, quality, theme, and render-setting helpers."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, MutableMapping

from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.ui.archive_browser.static_replacement_d3d11_cache import alignment_d3d11_dirty_flags_for_reason
from cdmw.ui.archive_browser.static_replacement_d3d11_loading_details import (
    alignment_d3d11_failed_performance_details,
    alignment_d3d11_resources_waiting_detail,
    alignment_d3d11_resources_waiting_performance_details,
    alignment_d3d11_restart_performance_details,
    alignment_d3d11_stale_loading_detail,
)


ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES = ("&#9679;", "&#9683;", "&#9681;", "&#9682;")
ALIGNMENT_D3D11_DEFENDER_HINT = (
    "If Defender quarantines an unsigned experimental EXE, submit it to Microsoft before allowing it."
)


@dataclasses.dataclass(frozen=True)
class AlignmentD3D11LoadingPresentation:
    status_text: str
    status_tooltip: str
    spinner_visible: bool
    clear_spinner_text: bool


@dataclasses.dataclass(frozen=True)
class AlignmentD3D11LoadedTimingPresentation:
    summary: str
    details: str
    native_load_ms: float
    texture_text: str


@dataclasses.dataclass(frozen=True)
class AlignmentD3D11StatusPresentation:
    summary: str
    details: str


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def alignment_lit_render_settings(settings: object, fallback_settings: ModelPreviewRenderSettings) -> ModelPreviewRenderSettings:
    return clamp_model_preview_render_settings(
        dataclasses.replace(settings)
        if isinstance(settings, ModelPreviewRenderSettings)
        else fallback_settings
    )


def alignment_preview_widget_render_settings(settings: object, *, interactive: bool) -> object:
    if not interactive:
        return settings
    settings = dataclasses.replace(settings)
    settings.disable_all_support_maps = True
    settings.disable_normal_map = True
    settings.disable_material_map = True
    settings.disable_height_map = True
    settings.low_quality_texture_max_dimension = min(
        int(getattr(settings, "low_quality_texture_max_dimension", 1024) or 1024),
        1024,
    )
    return clamp_model_preview_render_settings(settings)


def alignment_d3d11_loading_initial_state() -> dict[str, object]:
    return {"active": False, "frame": 0}


def alignment_d3d11_loading_next_frame(
    state: MutableMapping[str, object],
    frame_count: int,
) -> int:
    count = max(1, int(frame_count or 1))
    frame_index = (int(state.get("frame", 0) or 0) + 1) % count
    state["frame"] = frame_index
    return frame_index


def alignment_d3d11_loading_set_active(
    state: MutableMapping[str, object],
    active: bool,
) -> bool:
    current = bool(active)
    state["active"] = current
    return current


def alignment_d3d11_loading_active(state: Mapping[str, object]) -> bool:
    return bool(state.get("active"))


def alignment_d3d11_loading_presentation(
    active: bool,
    *,
    message: str = "",
    detail: str = "",
) -> AlignmentD3D11LoadingPresentation:
    message_text = str(message or "")
    detail_text = str(detail or "")
    return AlignmentD3D11LoadingPresentation(
        status_text=message_text,
        status_tooltip=detail_text or message_text,
        spinner_visible=bool(active),
        clear_spinner_text=not bool(active),
    )


def alignment_d3d11_loading_spinner_frames() -> tuple[str, ...]:
    return ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES


def alignment_d3d11_loading_spinner_html(frame: str) -> str:
    return (
        "<span style='font-size:2.4em; line-height:1.17; color:#79c0ff; font-weight:700;'>"
        f"{str(frame or '')}"
        "</span>"
    )


def alignment_d3d11_loading_cleared_performance(reason: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 preview loading state cleared.",
        details=f"reason={str(reason or '')}",
    )


def alignment_d3d11_watchdog_ready_performance(
    *,
    quality_label: str,
    reason: str,
    active_package: object,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 preview ready - {str(quality_label or '')} - loaded before watchdog",
        details=f"reason={str(reason or '')}\nactive_package={active_package}",
    )


def alignment_d3d11_resources_waiting_performance(details: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 resources loaded; waiting for visible preview panel.",
        details=str(details or ""),
    )


def alignment_d3d11_restart_performance(
    *,
    quality_label: str,
    stale_details: str,
    restart_count: int,
    max_restarts: int = 2,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 preview reload restarted - {str(quality_label or '')}",
        details=alignment_d3d11_restart_performance_details(
            stale_details,
            restart_count=restart_count,
            max_restarts=max_restarts,
        ),
    )


def alignment_d3d11_failed_performance(
    *,
    quality_label: str,
    stale_details: str,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 preview reload failed - {str(quality_label or '')}",
        details=alignment_d3d11_failed_performance_details(stale_details),
    )


def _alignment_d3d11_channel_debug_text(channel_debug: str, fallback: str = "") -> str:
    channel_debug_text = str(channel_debug or "")
    if channel_debug_text.startswith("Material Channel Contract: "):
        return "channels " + channel_debug_text[len("Material Channel Contract: "):]
    return channel_debug_text or str(fallback or "")


def _alignment_d3d11_state_timing_details(state: Mapping[str, object]) -> tuple[float, float]:
    return (
        float(state.get("prepare_ms", 0.0) or 0.0),
        float(state.get("package_ms", 0.0) or 0.0),
    )


def alignment_d3d11_cached_reuse_performance(
    state: Mapping[str, object],
    *,
    quality_label: str,
    rebuild_reason: str,
) -> AlignmentD3D11StatusPresentation:
    prepare_ms, package_ms = _alignment_d3d11_state_timing_details(state)
    reason_text = str(rebuild_reason or "geometry")
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 cached preview package - {str(quality_label or '')} - reason {reason_text}",
        details=(
            f"cache=hit\n"
            f"reason={reason_text}\n"
            f"prepare {prepare_ms:.1f} ms\n"
            f"package {package_ms:.1f} ms\n"
            "native load/upload 0.0 ms (active package reused)"
        ),
    )


def alignment_d3d11_cached_loading_performance(rebuild_reason: str) -> AlignmentD3D11StatusPresentation:
    reason_text = str(rebuild_reason or "geometry")
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 cached preview package loading - reason {reason_text}",
        details=f"cache=hit\nreason={reason_text}",
    )


def alignment_d3d11_queued_preview_reload_detail(rebuild_reason: str) -> str:
    reason_text = str(rebuild_reason or "geometry")
    return f"Queued preview reload. reason={reason_text}"


def alignment_d3d11_queued_latest_preview_reload_detail(rebuild_reason: str) -> str:
    reason_text = str(rebuild_reason or "geometry")
    return f"Queued latest preview reload. reason={reason_text}"


def alignment_d3d11_cached_loading_progress_detail(rebuild_reason: str) -> str:
    reason_text = str(rebuild_reason or "geometry")
    return f"Loading cached package. reason={reason_text}"


def alignment_d3d11_cached_renderer_reload_detail(rebuild_reason: str) -> str:
    reason_text = str(rebuild_reason or "geometry")
    return f"Reloading cached renderer package. reason={reason_text}"


def alignment_d3d11_waiting_for_preview_panel_detail(
    *,
    rebuild_reason: str,
    host_detail: str,
    retry_count: object,
) -> str:
    reason_text = str(rebuild_reason or "geometry")
    try:
        retry_text = str(int(retry_count or 0))
    except (TypeError, ValueError):
        retry_text = "0"
    return f"reason={reason_text}\nhost={str(host_detail or '')}\nretry={retry_text}"


def alignment_d3d11_package_loading_detail(
    *,
    package_quality: str,
    high_quality_textures: bool,
    mesh_edit_raw_package: bool,
    fast_geometry_loaded: bool,
) -> str:
    package_quality_key = str(package_quality or "").strip().lower()
    if package_quality_key == "fast_geometry":
        return "building fast geometry"
    if package_quality_key == "material_refresh":
        return "refreshing materials with cached geometry"
    if bool(mesh_edit_raw_package):
        return "building editable mesh materials"
    if package_quality_key == "archive_parity" and bool(fast_geometry_loaded):
        return "building full Archive Preview material parity in background"
    return "resolving textures" if bool(high_quality_textures) else "building mesh and low-res textures"


def alignment_d3d11_package_preparing_performance(
    state: Mapping[str, object],
    *,
    quality_label: str,
    cache_label: str,
    rebuild_reason: str,
) -> AlignmentD3D11StatusPresentation:
    reason_text = str(rebuild_reason or "geometry")
    return AlignmentD3D11StatusPresentation(
        summary=(
            f"D3D11 package preparing - {str(quality_label or '')} - "
            f"{str(cache_label or '')}"
        ),
        details=(
            f"cache={state.get('last_cache_event')}\n"
            f"reason={reason_text}\n"
            "Full material parity runs in a background worker. You can keep using the UI; "
            "preview-changing edits cancel/restart the pending parity package."
        ),
    )


def alignment_d3d11_reload_queued_performance(
    state: Mapping[str, object],
    *,
    quality_label: str,
    cache_label: str,
    package_quality: str,
    rebuild_reason: str,
    channel_debug: str = "",
) -> AlignmentD3D11StatusPresentation:
    prepare_ms, package_ms = _alignment_d3d11_state_timing_details(state)
    reason_text = str(rebuild_reason or "geometry")
    cache_event = str(state.get("last_cache_event", "miss") or "miss")
    summary = (
        f"D3D11 reload queued - {str(quality_label or '')} - "
        f"{str(package_quality or 'normal')} package - "
        f"reason {reason_text} - {str(cache_label or '')} - "
        f"prepare {prepare_ms:.0f} ms, "
        f"package {package_ms:.0f} ms"
    )
    return AlignmentD3D11StatusPresentation(
        summary=summary,
        details=(
            f"cache={cache_event}\n"
            f"reason={reason_text}\n"
            f"{str(channel_debug or summary)}"
        ),
    )


def alignment_d3d11_starting_performance(
    state: Mapping[str, object],
    *,
    quality_label: str,
    cache_label: str,
    package_quality: str,
    rebuild_reason: str,
) -> AlignmentD3D11StatusPresentation:
    prepare_ms, package_ms = _alignment_d3d11_state_timing_details(state)
    reason_text = str(rebuild_reason or "geometry")
    cache_event = str(state.get("last_cache_event", "miss") or "miss")
    return AlignmentD3D11StatusPresentation(
        summary=(
            f"Starting D3D11 preview - {str(quality_label or '')} - "
            f"{str(package_quality or 'normal')} package - "
            f"reason {reason_text} - {str(cache_label or '')} - "
            f"prepare {prepare_ms:.0f} ms, "
            f"package {package_ms:.0f} ms"
        ),
        details=f"cache={cache_event}\nreason={reason_text}",
    )


def alignment_d3d11_pending_host_performance(
    *,
    rebuild_reason: str,
    host_detail: str,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 preview host pending layout before renderer start.",
        details=f"reason={str(rebuild_reason or 'geometry')}\nhost={str(host_detail or '')}",
    )


def alignment_d3d11_renderer_host_restart_performance(
    *,
    rebuild_reason: str,
    host_detail: str,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 renderer host not reusable; restarting.",
        details=f"reason={str(rebuild_reason or 'geometry')}\nhost={str(host_detail or '')}",
    )


def alignment_d3d11_unavailable_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="Native D3D11 unavailable.",
        details=(
            "Native D3D11 is required for live alignment preview. "
            f"{ALIGNMENT_D3D11_DEFENDER_HINT}"
        ),
    )


def alignment_d3d11_startup_timeout_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 startup timeout.",
        details=(
            "Native D3D11 startup timeout waiting for status. "
            f"{ALIGNMENT_D3D11_DEFENDER_HINT}"
        ),
    )


def alignment_d3d11_package_failed_performance(message: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 package failed.",
        details=str(message),
    )


def alignment_d3d11_live_display_mode_performance(mode: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary=f"D3D11 display mode changed live: {str(mode or '')}",
        details="cache=live-command reason=display_mode",
    )


def alignment_d3d11_selection_highlight_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="Selection highlight updated.",
        details="Selection changes use live D3D11 highlight commands and do not rebuild the preview package.",
    )


def alignment_d3d11_render_settings_rebuild_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 preview package rebuild queued for texture settings.",
        details="cache=material_dirty reason=render_settings",
    )


def alignment_d3d11_render_tuning_live_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 render tuning applied without rebuilding preview package.",
        details="cache=live-command reason=render_tuning",
    )


def alignment_d3d11_texture_flip_v_live_performance() -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 texture Flip V applied without rebuilding preview package.",
        details="",
    )


def alignment_d3d11_stale_package_dropped_detail(
    *,
    reason: str,
    request_id: int,
    active_preview_alive: bool,
) -> str:
    return (
        "Stale D3D11 package dropped before display.\n"
        f"reason={str(reason or '')}\n"
        f"request_id={int(request_id or 0)}\n"
        f"active_preview_alive={bool(active_preview_alive)}"
    )


def alignment_d3d11_stale_package_dropped_performance(
    *,
    reason: str,
    request_id: int,
    active_preview_alive: bool,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="Dropped stale D3D11 preview package; rebuilding current preview.",
        details=(
            f"reason={str(reason or '')}\n"
            f"request_id={int(request_id or 0)}\n"
            f"active_preview_alive={bool(active_preview_alive)}"
        ),
    )


def alignment_d3d11_renderer_error_performance(message: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 renderer error.",
        details=str(message),
    )


def alignment_d3d11_package_queued_performance(
    *,
    quality_label: str,
    refresh_elapsed_ms: float,
) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary=(
            f"D3D11 package queued - {str(quality_label or '')} - "
            f"refresh {float(refresh_elapsed_ms or 0.0):.0f} ms"
        ),
        details="",
    )


def alignment_d3d11_alignment_preview_failed_performance(message: str) -> AlignmentD3D11StatusPresentation:
    return AlignmentD3D11StatusPresentation(
        summary="D3D11 alignment preview failed.",
        details=str(message),
    )


def alignment_d3d11_loaded_timing_presentation(
    state: Mapping[str, object],
    payload: Mapping[str, object],
    *,
    quality_label: str,
    cache_label: str,
    channel_debug: str = "",
) -> AlignmentD3D11LoadedTimingPresentation:
    textures = payload.get("textures", {})
    texture_text = "none"
    if isinstance(textures, Mapping):
        texture_text = " ".join(
            f"{slot}:{int(count)}"
            for slot, count in sorted(textures.items())
            if int(count or 0) > 0
        ) or "none"
    cache_event = str(state.get("last_cache_event", "miss") or "miss")
    rebuild_reason = str(
        state.get("last_cache_reason", "") or state.get("last_rebuild_reason", "geometry") or "geometry"
    )
    native_manifest_ms = float(payload.get("native_manifest_ms", payload.get("manifest_read_ms", 0.0)) or 0.0)
    native_texture_ms = float(payload.get("native_texture_ms", payload.get("texture_bind_ms", 0.0)) or 0.0)
    native_geometry_ms = float(payload.get("native_geometry_ms", payload.get("geometry_upload_ms", 0.0)) or 0.0)
    native_load_ms = native_manifest_ms + native_texture_ms + native_geometry_ms
    first_frame_ms = _float_value(payload.get("first_frame_ms"))
    frame_ms = _float_value(payload.get("frame_time_ms") or payload.get("frame_ms") or first_frame_ms)
    fps = _float_value(payload.get("current_fps") or payload.get("fps") or payload.get("average_fps"))
    if fps <= 0.0 and frame_ms > 0.0:
        fps = 1000.0 / frame_ms
    frame_text = f"FPS {fps:.1f} - frame {frame_ms:.2f} ms - " if fps > 0.0 and frame_ms > 0.0 else ""
    channel_debug_text = _alignment_d3d11_channel_debug_text(channel_debug)
    summary = (
        f"D3D11 preview loaded - {str(quality_label or '')} - "
        f"{frame_text}"
        f"{str(state.get('package_quality', 'normal') or 'normal')} package - "
        f"reason {rebuild_reason} - {str(cache_label or '')} - "
        f"native {native_load_ms:.0f} ms - "
        f"textures {texture_text}"
    )
    details = (
        f"cache={cache_event}\n"
        f"reason {rebuild_reason}\n"
        f"pipeline {str(state.get('preview_pipeline_stage', '') or '')}\n"
        f"prepare {float(state.get('prepare_ms', 0.0) or 0.0):.1f} ms\n"
        f"package {float(state.get('package_ms', 0.0) or 0.0):.1f} ms\n"
        f"native_manifest_ms {native_manifest_ms:.1f}\n"
        f"native_texture_ms {native_texture_ms:.1f}\n"
        f"native_geometry_ms {native_geometry_ms:.1f}\n"
        f"native_load_upload {native_load_ms:.1f} ms\n"
        f"fps {fps:.1f}\n"
        f"first_frame {first_frame_ms:.1f} ms\n"
        f"frames {int(payload.get('frame_count', 0) or 0)}\n"
        f"render_suppressed {int(payload.get('render_suppressed_count', 0) or 0)}\n"
        f"parent_health {str(payload.get('parent_health', '') or '')}\n"
        f"{channel_debug_text}"
    )
    return AlignmentD3D11LoadedTimingPresentation(
        summary=summary,
        details=details,
        native_load_ms=native_load_ms,
        texture_text=texture_text,
    )


def alignment_d3d11_progress_update(
    state: MutableMapping[str, object],
    percent: int,
    message: str,
    *,
    stage: str = "",
    detail: str = "",
    active: bool = True,
) -> tuple[str, str, bool]:
    percent = max(0, min(100, int(percent or 0)))
    message_text = str(message or "Preparing preview").strip() or "Preparing preview"
    if not message_text.startswith(f"{percent}%"):
        message_text = f"{percent}% {message_text}"
    stage_text = str(stage or "").strip()
    state["loading_percent"] = percent
    state["loading_stage"] = stage_text
    state["loading_message"] = message_text
    tooltip_parts = []
    if detail:
        tooltip_parts.append(str(detail))
    if stage_text:
        tooltip_parts.append(f"stage={stage_text}")
    tooltip_parts.append(f"progress={percent}%")
    return message_text, "\n".join(tooltip_parts), bool(active and percent < 100)


def alignment_d3d11_clear_loading_start(state: MutableMapping[str, object]) -> None:
    state["loading_started_at"] = 0.0


def alignment_d3d11_mark_loading_started(state: MutableMapping[str, object], now_s: float) -> float:
    started_at = float(now_s or 0.0)
    state["loading_started_at"] = started_at
    return started_at


def alignment_d3d11_ensure_loading_started(state: MutableMapping[str, object], now_s: float) -> float:
    started_at = float(state.get("loading_started_at", 0.0) or 0.0)
    if started_at <= 0.0:
        started_at = alignment_d3d11_mark_loading_started(state, now_s)
    return started_at


def alignment_d3d11_pipeline_stage(state: MutableMapping[str, object], stage: str) -> str:
    normalized = str(stage or "idle").strip().lower() or "idle"
    state["preview_pipeline_stage"] = normalized
    return normalized


def alignment_d3d11_package_quality(
    settings: object,
    state: Mapping[str, object],
    *,
    reason: str,
    mesh_edit_raw_preview_active: bool,
) -> tuple[object, bool, bool, str]:
    use_textures = bool(getattr(settings, "use_textures_by_default", True))
    high_quality_textures = bool(use_textures and getattr(settings, "high_quality_by_default", True))
    enable_material_combiner = bool(use_textures)
    normalized_reason = str(reason or state.get("next_rebuild_reason", "") or "").strip().lower()
    dirty_flags = alignment_d3d11_dirty_flags_for_reason(normalized_reason)
    if mesh_edit_raw_preview_active:
        return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "mesh_edit_raw"
    if (
        bool(state.get("archive_parity_ready"))
        and dirty_flags.affects_material()
        and not dirty_flags.affects_geometry()
    ):
        return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "material_refresh"
    if (
        dirty_flags.affects_geometry()
        and not bool(state.get("fast_geometry_loaded"))
        and not bool(state.get("archive_parity_ready"))
    ):
        fast_settings = dataclasses.replace(
            settings,
            use_textures_by_default=False,
            high_quality_by_default=False,
        )
        return clamp_model_preview_render_settings(fast_settings), False, False, "fast_geometry"
    return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "archive_parity"


def alignment_preview_quality_label(state: Mapping[str, object]) -> str:
    quality = str(
        state.get("active_package_quality", "")
        or state.get("package_quality", "")
        or ""
    ).strip().lower()
    if quality == "fast_geometry":
        return "Fast geometry"
    if quality == "archive_parity":
        return "Archive Preview parity"
    if quality == "material_refresh":
        return "Material refresh"
    if quality == "mesh_edit_raw":
        return "Editable mesh"
    return "Normal quality"


def live_alignment_preview_status_message() -> str:
    return (
        "Live alignment preview - fast geometry appears first; full Archive Preview material parity "
        "loads in the background. Preview-changing edits restart that parity load."
    )


def alignment_d3d11_theme_payload(background_color: str, text_color: str) -> dict[str, str]:
    return {
        "background": str(background_color),
        "text": str(text_color),
    }


__all__ = [
    "ALIGNMENT_D3D11_DEFENDER_HINT",
    "ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES",
    "AlignmentD3D11LoadedTimingPresentation",
    "AlignmentD3D11LoadingPresentation",
    "AlignmentD3D11StatusPresentation",
    "alignment_d3d11_clear_loading_start",
    "alignment_d3d11_cached_loading_performance",
    "alignment_d3d11_cached_loading_progress_detail",
    "alignment_d3d11_cached_renderer_reload_detail",
    "alignment_d3d11_cached_reuse_performance",
    "alignment_d3d11_ensure_loading_started",
    "alignment_d3d11_alignment_preview_failed_performance",
    "alignment_d3d11_failed_performance",
    "alignment_d3d11_loading_active",
    "alignment_d3d11_loading_cleared_performance",
    "alignment_d3d11_loading_initial_state",
    "alignment_d3d11_loading_next_frame",
    "alignment_d3d11_loading_presentation",
    "alignment_d3d11_loading_set_active",
    "alignment_d3d11_loading_spinner_frames",
    "alignment_d3d11_loading_spinner_html",
    "alignment_d3d11_loaded_timing_presentation",
    "alignment_d3d11_live_display_mode_performance",
    "alignment_d3d11_mark_loading_started",
    "alignment_d3d11_package_queued_performance",
    "alignment_d3d11_queued_latest_preview_reload_detail",
    "alignment_d3d11_queued_preview_reload_detail",
    "alignment_d3d11_package_loading_detail",
    "alignment_d3d11_package_failed_performance",
    "alignment_d3d11_package_preparing_performance",
    "alignment_d3d11_package_quality",
    "alignment_d3d11_pending_host_performance",
    "alignment_d3d11_pipeline_stage",
    "alignment_d3d11_progress_update",
    "alignment_d3d11_failed_performance_details",
    "alignment_d3d11_render_settings_rebuild_performance",
    "alignment_d3d11_render_tuning_live_performance",
    "alignment_d3d11_renderer_error_performance",
    "alignment_d3d11_renderer_host_restart_performance",
    "alignment_d3d11_resources_waiting_detail",
    "alignment_d3d11_resources_waiting_performance",
    "alignment_d3d11_resources_waiting_performance_details",
    "alignment_d3d11_reload_queued_performance",
    "alignment_d3d11_restart_performance",
    "alignment_d3d11_restart_performance_details",
    "alignment_d3d11_starting_performance",
    "alignment_d3d11_startup_timeout_performance",
    "alignment_d3d11_stale_loading_detail",
    "alignment_d3d11_stale_package_dropped_detail",
    "alignment_d3d11_stale_package_dropped_performance",
    "alignment_d3d11_selection_highlight_performance",
    "alignment_d3d11_theme_payload",
    "alignment_d3d11_texture_flip_v_live_performance",
    "alignment_d3d11_unavailable_performance",
    "alignment_d3d11_watchdog_ready_performance",
    "alignment_d3d11_waiting_for_preview_panel_detail",
    "alignment_lit_render_settings",
    "alignment_preview_quality_label",
    "alignment_preview_widget_render_settings",
    "live_alignment_preview_status_message",
]
