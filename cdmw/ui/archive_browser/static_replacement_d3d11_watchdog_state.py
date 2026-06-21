"""D3D11 loading watchdog and stale-preview recovery rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ClearStuckLoadingRouteState:
    action: str
    should_restore_loaded_preview: bool
    should_report_idle: bool
    should_report_resources_waiting: bool
    should_restart: bool
    should_report_failed: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11LoadingWatchdogSnapshot:
    active_request_id: int
    preview_loaded: bool
    resources_loaded: bool
    started_at: float
    elapsed_s: float
    last_percent: int
    last_stage: str
    restart_count: int


@dataclass(frozen=True, slots=True)
class AlignmentD3D11LoadingRecoveryAction:
    action: str
    loading_message: str
    progress_message: str
    detail_kind: str
    performance_kind: str
    should_mark_preview_unloaded: bool
    should_set_loading_inactive: bool
    should_reset_request_idle: bool
    should_restore_loaded_preview: bool
    should_record_restart: bool
    should_stop_process: bool
    should_queue_latest_rebuild: bool


def _request_id(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def alignment_d3d11_loading_stuck(
    *,
    loading_active: bool,
    preview_loaded: bool,
    queued_model_active: bool,
    pending_model_active: bool,
    thread_active: bool,
    loading_started_at: float,
    loading_elapsed_s: float,
    timeout_s: float,
    request_active: bool,
    process_active: bool,
    active_package_exists: bool,
) -> bool:
    if not loading_active:
        return False
    if preview_loaded:
        return not bool(queued_model_active or pending_model_active or thread_active)
    if float(loading_started_at or 0.0) <= 0.0:
        return False
    if float(loading_elapsed_s) < float(timeout_s):
        return False
    if not request_active:
        return True
    return bool(process_active and active_package_exists)


def alignment_d3d11_loading_watchdog_snapshot(
    state: Mapping[str, object],
    *,
    now_s: float,
) -> AlignmentD3D11LoadingWatchdogSnapshot:
    try:
        started_at = float(state.get("loading_started_at", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        started_at = 0.0
    elapsed_s = max(0.0, float(now_s or 0.0) - started_at) if started_at > 0.0 else 0.0
    try:
        last_percent = int(state.get("loading_percent", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        last_percent = 0
    try:
        restart_count = int(state.get("stale_reload_restart_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        restart_count = 0
    return AlignmentD3D11LoadingWatchdogSnapshot(
        active_request_id=_request_id(state.get("active_package_request_id")),
        preview_loaded=bool(state.get("preview_loaded")),
        resources_loaded=bool(state.get("resources_loaded")),
        started_at=started_at,
        elapsed_s=elapsed_s,
        last_percent=last_percent,
        last_stage=str(state.get("loading_stage", "") or "unknown"),
        restart_count=restart_count,
    )


def alignment_d3d11_stale_loading_restart_allowed(
    *,
    restart_count: int,
    drag_active: bool,
) -> bool:
    if bool(drag_active):
        return False
    return int(restart_count or 0) < 2


def alignment_d3d11_clear_stuck_loading_route(
    *,
    dialog_live: bool,
    preview_loaded: bool,
    resources_loaded: bool,
    process_active: bool,
    active_package_exists: bool,
    host_ready: bool,
    child_ready: bool,
    restart_count: int,
    drag_active: bool,
) -> AlignmentD3D11ClearStuckLoadingRouteState:
    if not bool(dialog_live):
        return AlignmentD3D11ClearStuckLoadingRouteState("dialog_closed", False, False, False, False, False)
    if not bool(process_active) and not bool(active_package_exists):
        return AlignmentD3D11ClearStuckLoadingRouteState("idle", False, True, False, False, False)
    if bool(preview_loaded):
        return AlignmentD3D11ClearStuckLoadingRouteState("watchdog_ready", True, False, False, False, False)
    if bool(resources_loaded) and (not bool(host_ready) or not bool(child_ready)):
        return AlignmentD3D11ClearStuckLoadingRouteState("resources_waiting", False, False, True, False, False)
    if alignment_d3d11_stale_loading_restart_allowed(
        restart_count=restart_count,
        drag_active=drag_active,
    ):
        return AlignmentD3D11ClearStuckLoadingRouteState("restart", False, False, False, True, False)
    return AlignmentD3D11ClearStuckLoadingRouteState("failed", False, False, False, False, True)


def alignment_d3d11_loading_recovery_action(
    route: AlignmentD3D11ClearStuckLoadingRouteState,
) -> AlignmentD3D11LoadingRecoveryAction:
    if route.action == "dialog_closed":
        return AlignmentD3D11LoadingRecoveryAction(
            "dialog_closed", "", "", "", "", True, True, False, False, False, False, False
        )
    if route.should_report_idle:
        return AlignmentD3D11LoadingRecoveryAction(
            "idle", "Preview idle.", "", "", "loading_cleared", False, False, True, False, False, False, False
        )
    if route.should_restore_loaded_preview:
        return AlignmentD3D11LoadingRecoveryAction(
            "restore_loaded", "", "Preview ready.", "", "watchdog_ready", False, False, False, True, False, False, False
        )
    if route.should_report_resources_waiting:
        return AlignmentD3D11LoadingRecoveryAction(
            "resources_waiting",
            "Preview resources loaded; waiting for visible preview panel.",
            "",
            "resources_waiting",
            "resources_waiting",
            False,
            True,
            False,
            False,
            False,
            False,
            False,
        )
    if route.should_restart:
        return AlignmentD3D11LoadingRecoveryAction(
            "restart",
            "Preview reload restarted.",
            "",
            "stale_loading",
            "restart",
            False,
            True,
            False,
            False,
            True,
            True,
            True,
        )
    return AlignmentD3D11LoadingRecoveryAction(
        "failed",
        "Preview reload could not produce a fresh frame.",
        "",
        "stale_loading",
        "failed",
        False,
        True,
        False,
        False,
        False,
        False,
        False,
    )


__all__ = [
    "AlignmentD3D11ClearStuckLoadingRouteState",
    "AlignmentD3D11LoadingRecoveryAction",
    "AlignmentD3D11LoadingWatchdogSnapshot",
    "alignment_d3d11_clear_stuck_loading_route",
    "alignment_d3d11_loading_recovery_action",
    "alignment_d3d11_loading_stuck",
    "alignment_d3d11_loading_watchdog_snapshot",
    "alignment_d3d11_stale_loading_restart_allowed",
]
