"""D3D11 preview status-state helpers for static replacement previews."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlignmentD3D11LoadedStatusRoute:
    pipeline_stage: str
    pipeline_detail: str
    progress_message: str
    progress_stage: str
    should_sync_mesh_edit_preview: bool
    should_defer_for_drag: bool
    should_keep_live_transform: bool
    should_apply_ready_state: bool
    should_queue_archive_parity: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ResourcesLoadedStatusRoute:
    message: str
    stage: str
    detail: str
    active: bool
    waiting_for_visible_panel: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11LoadingStatusRoute:
    action: str
    message: str
    stage: str
    progress_percent: int


@dataclass(frozen=True, slots=True)
class AlignmentD3D11StatusUnavailableRoute:
    action: str
    message: str


@dataclass(frozen=True, slots=True)
class AlignmentD3D11TerminalStatusRoute:
    action: str
    message: str
    should_mark_preview_unloaded: bool
    should_clear_pending_rebuild: bool
    performance_message: str


def _request_id(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def alignment_d3d11_status_event(payload: Mapping[str, object]) -> str:
    return str(payload.get("event", "") or "").strip().lower()


def alignment_d3d11_unavailable_status_route(
    *,
    preview_loaded: bool,
    loading_stuck: bool,
    reason: str,
) -> AlignmentD3D11StatusUnavailableRoute:
    normalized_reason = str(reason or "").strip() or "status unavailable"
    if bool(preview_loaded):
        return AlignmentD3D11StatusUnavailableRoute("ready", "Preview ready.")
    if bool(loading_stuck):
        return AlignmentD3D11StatusUnavailableRoute("clear_stuck", normalized_reason)
    return AlignmentD3D11StatusUnavailableRoute("ignore", normalized_reason)


def alignment_d3d11_status_read_error_route(error: object) -> AlignmentD3D11TerminalStatusRoute:
    return AlignmentD3D11TerminalStatusRoute(
        action="read_error",
        message=f"Preview status read failed: {error}",
        should_mark_preview_unloaded=False,
        should_clear_pending_rebuild=False,
        performance_message="",
    )


def alignment_d3d11_invalid_status_payload_route() -> AlignmentD3D11TerminalStatusRoute:
    return AlignmentD3D11TerminalStatusRoute(
        action="ignore",
        message="",
        should_mark_preview_unloaded=False,
        should_clear_pending_rebuild=False,
        performance_message="",
    )


def alignment_d3d11_record_status_payload(
    state: MutableMapping[str, object],
    *,
    signature: object,
    payload_text: str,
) -> bool:
    normalized_payload = str(payload_text or "")
    if (
        signature == state.get("status_signature", (0, 0))
        and normalized_payload == str(state.get("status_payload_text", "") or "")
    ):
        return False
    state["status_signature"] = signature
    state["status_payload_text"] = normalized_payload
    return True


def alignment_d3d11_mark_active_cached_package_reused(
    state: MutableMapping[str, object],
    *,
    request_id: int,
    display_mode: str,
    package_quality: str,
    cache_key: str,
) -> str:
    state["active_package_request_id"] = _request_id(request_id)
    state["active_package_display_mode"] = str(display_mode or "")
    state["active_package_quality"] = str(package_quality or "")
    state["active_package_cache_key"] = str(cache_key or "")
    state["preview_loaded"] = True
    state["stale_reload_restart_count"] = 0
    cached_quality = str(package_quality or "").strip().lower()
    if cached_quality == "fast_geometry":
        state["fast_geometry_loaded"] = True
        state["archive_parity_ready"] = False
    elif cached_quality == "archive_parity":
        state["fast_geometry_loaded"] = True
        state["archive_parity_ready"] = True
        state["material_complete_preview_seen"] = True
        state["archive_parity_upgrade_queued"] = False
    elif cached_quality == "material_refresh":
        state["material_complete_preview_seen"] = True
    return cached_quality


def alignment_d3d11_mark_loaded_package(
    state: MutableMapping[str, object],
    *,
    package_quality: str = "",
) -> str:
    state["preview_loaded"] = True
    state["resources_loaded"] = True
    state["stale_reload_restart_count"] = 0
    loaded_quality = str(
        package_quality
        or state.get("active_package_quality", "")
        or state.get("package_quality", "normal")
        or "normal"
    ).strip().lower()
    if loaded_quality == "fast_geometry":
        state["fast_geometry_loaded"] = True
        state["archive_parity_ready"] = False
    elif loaded_quality == "archive_parity":
        state["fast_geometry_loaded"] = True
        state["archive_parity_ready"] = True
        state["material_complete_preview_seen"] = True
        state["archive_parity_upgrade_queued"] = False
    elif loaded_quality == "material_refresh":
        state["fast_geometry_loaded"] = True
        state["archive_parity_ready"] = True
        state["material_complete_preview_seen"] = True
    return loaded_quality


def alignment_d3d11_loaded_status_route(
    *,
    loaded_quality: object,
    active_request_id: object,
    drag_active: bool,
    drag_reload_stale: bool,
) -> AlignmentD3D11LoadedStatusRoute:
    quality = str(loaded_quality or "").strip().lower()
    pipeline_stage = ""
    pipeline_detail = ""
    if quality == "fast_geometry":
        pipeline_stage = "fast_geometry"
        pipeline_detail = "first visible D3D11 geometry ready"
    elif quality == "archive_parity":
        pipeline_stage = "archive_parity_ready"
        pipeline_detail = "full material preview ready"
    elif quality == "material_refresh":
        pipeline_stage = "material_loading"
        pipeline_detail = "material refresh package ready"
    if bool(drag_active):
        return AlignmentD3D11LoadedStatusRoute(
            pipeline_stage=pipeline_stage,
            pipeline_detail=pipeline_detail,
            progress_message="Preview loaded; applying after movement settles.",
            progress_stage="",
            should_sync_mesh_edit_preview=True,
            should_defer_for_drag=True,
            should_keep_live_transform=False,
            should_apply_ready_state=False,
            should_queue_archive_parity=False,
        )
    if _request_id(active_request_id) and bool(drag_reload_stale):
        return AlignmentD3D11LoadedStatusRoute(
            pipeline_stage=pipeline_stage,
            pipeline_detail=pipeline_detail,
            progress_message="Preview loaded; keeping live transform.",
            progress_stage="",
            should_sync_mesh_edit_preview=True,
            should_defer_for_drag=False,
            should_keep_live_transform=True,
            should_apply_ready_state=False,
            should_queue_archive_parity=False,
        )
    return AlignmentD3D11LoadedStatusRoute(
        pipeline_stage=pipeline_stage,
        pipeline_detail=pipeline_detail,
        progress_message="Preview ready.",
        progress_stage="ready",
        should_sync_mesh_edit_preview=True,
        should_defer_for_drag=False,
        should_keep_live_transform=False,
        should_apply_ready_state=True,
        should_queue_archive_parity=quality == "fast_geometry",
    )


def alignment_d3d11_mark_resources_loaded(state: MutableMapping[str, object]) -> None:
    state["resources_loaded"] = True


def _status_float(payload: Mapping[str, object], key: str) -> float:
    try:
        return float(payload.get(key, 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def alignment_d3d11_resources_loaded_status_route(
    payload: Mapping[str, object],
) -> AlignmentD3D11ResourcesLoadedStatusRoute:
    reason_text = str(
        payload.get("render_suppressed_reason", "")
        or payload.get("parent_health", "")
        or ""
    ).strip().lower()
    parent_renderable = bool(payload.get("parent_renderable", True))
    if (not parent_renderable) or reason_text in {"parent_not_renderable", "window_not_visible"}:
        return AlignmentD3D11ResourcesLoadedStatusRoute(
            message="Preview resources loaded; waiting for visible preview panel.",
            stage="resources_loaded",
            detail=(
                f"render_suppressed_reason={reason_text or 'none'}\n"
                f"parent_renderable={parent_renderable}"
            ),
            active=False,
            waiting_for_visible_panel=True,
        )
    return AlignmentD3D11ResourcesLoadedStatusRoute(
        message="Preview resources loaded; waiting for first frame.",
        stage="resources_loaded",
        detail=(
            f"geometry_upload_ms={_status_float(payload, 'geometry_upload_ms'):.1f}\n"
            f"texture_bind_ms={_status_float(payload, 'texture_bind_ms'):.1f}"
        ),
        active=True,
        waiting_for_visible_panel=False,
    )


def alignment_d3d11_loading_status_route(
    payload: Mapping[str, object],
    *,
    preview_loaded: bool,
    loading_stuck: bool,
) -> AlignmentD3D11LoadingStatusRoute:
    message = str(payload.get("message", "") or "Loading native D3D11 alignment preview...")
    try:
        percent = int(round(float(payload.get("percent", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        percent = 0
    stage = str(payload.get("stage", "") or "native")
    if bool(preview_loaded):
        return AlignmentD3D11LoadingStatusRoute("tooltip", message, stage, max(0, percent))
    if bool(loading_stuck):
        return AlignmentD3D11LoadingStatusRoute("clear_stuck", message, stage, max(0, percent))
    return AlignmentD3D11LoadingStatusRoute("progress", message, stage, percent if percent > 0 else 82)


def alignment_d3d11_error_status_route(message: object) -> AlignmentD3D11TerminalStatusRoute:
    normalized = str(message or "").strip()
    return AlignmentD3D11TerminalStatusRoute(
        action="error",
        message=normalized,
        should_mark_preview_unloaded=True,
        should_clear_pending_rebuild=True,
        performance_message=normalized,
    )


def alignment_d3d11_closed_status_route(message: object) -> AlignmentD3D11TerminalStatusRoute:
    normalized = str(message or "").strip() or "Preview closed."
    return AlignmentD3D11TerminalStatusRoute(
        action="closed",
        message=normalized,
        should_mark_preview_unloaded=True,
        should_clear_pending_rebuild=True,
        performance_message="",
    )


def alignment_d3d11_mark_preview_unloaded(state: MutableMapping[str, object]) -> None:
    state["preview_loaded"] = False


def alignment_d3d11_mark_preview_loaded(state: MutableMapping[str, object]) -> None:
    state["preview_loaded"] = True


def alignment_d3d11_reset_material_parity_state(state: MutableMapping[str, object]) -> None:
    state["fast_geometry_loaded"] = False
    state["archive_parity_ready"] = False
    state["archive_parity_upgrade_queued"] = False


def alignment_d3d11_begin_archive_parity_upgrade(state: MutableMapping[str, object]) -> bool:
    if bool(state.get("archive_parity_ready")):
        return False
    if bool(state.get("archive_parity_upgrade_queued")):
        return False
    state["archive_parity_upgrade_queued"] = True
    return True


def alignment_d3d11_clear_archive_parity_upgrade(state: MutableMapping[str, object]) -> None:
    state["archive_parity_upgrade_queued"] = False


__all__ = [
    "AlignmentD3D11LoadedStatusRoute",
    "AlignmentD3D11LoadingStatusRoute",
    "AlignmentD3D11ResourcesLoadedStatusRoute",
    "AlignmentD3D11StatusUnavailableRoute",
    "AlignmentD3D11TerminalStatusRoute",
    "alignment_d3d11_closed_status_route",
    "alignment_d3d11_error_status_route",
    "alignment_d3d11_invalid_status_payload_route",
    "alignment_d3d11_loaded_status_route",
    "alignment_d3d11_loading_status_route",
    "alignment_d3d11_begin_archive_parity_upgrade",
    "alignment_d3d11_clear_archive_parity_upgrade",
    "alignment_d3d11_mark_active_cached_package_reused",
    "alignment_d3d11_mark_loaded_package",
    "alignment_d3d11_mark_preview_loaded",
    "alignment_d3d11_mark_preview_unloaded",
    "alignment_d3d11_mark_resources_loaded",
    "alignment_d3d11_record_status_payload",
    "alignment_d3d11_reset_material_parity_state",
    "alignment_d3d11_resources_loaded_status_route",
    "alignment_d3d11_status_read_error_route",
    "alignment_d3d11_unavailable_status_route",
    "alignment_d3d11_status_event",
]
