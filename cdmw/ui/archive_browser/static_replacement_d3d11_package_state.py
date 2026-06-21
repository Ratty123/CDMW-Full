"""D3D11 package lifecycle state helpers for static replacement previews."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AlignmentD3D11PackageStartRouteState:
    should_start: bool
    should_drop: bool
    drop_reason: str
    display_mode: str
    rebuild_reason: str
    transform_generation: int


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ProcessStartRouteState:
    should_start: bool
    should_drop: bool
    drop_reason: str
    should_pause_loading: bool
    pause_message: str
    should_handle_stale_drag: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11PackageReadyRouteState:
    should_accept: bool
    should_drop: bool
    drop_reason: str
    should_handle_stale_drag: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ProcessReuseState:
    can_reuse_process: bool
    should_report_restart: bool
    host_detail: str


@dataclass(frozen=True, slots=True)
class AlignmentD3D11PackageDropCleanupState:
    package_path: Path | None
    should_cleanup: bool
    active_package_matches: bool


def _request_id(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalized_rebuild_reason(reason: object) -> str:
    normalized = str(reason or "geometry").strip().lower()
    if normalized not in {"geometry", "texture_uv", "material", "mode_missing_original"}:
        normalized = "geometry"
    return normalized


def _package_path(value: object) -> Path | None:
    if value is None:
        return None
    try:
        return Path(value)
    except (TypeError, ValueError):
        return None


def _paths_match(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except (OSError, TypeError, ValueError, RuntimeError):
        return False


def alignment_d3d11_package_start_route(
    *,
    dialog_live: bool,
    preview_active: bool,
    model_is_preview_data: bool,
    display_mode: object,
    fallback_display_mode: object,
    reason: object,
    transform_generation: object,
    current_transform_generation: int,
    active_request_id: object,
) -> AlignmentD3D11PackageStartRouteState:
    if not bool(dialog_live):
        return AlignmentD3D11PackageStartRouteState(
            should_start=False,
            should_drop=True,
            drop_reason="dialog_closing_worker",
            display_mode=str(fallback_display_mode or "side_by_side"),
            rebuild_reason=_normalized_rebuild_reason(reason),
            transform_generation=int(current_transform_generation or 0),
        )
    requested_display_mode = str(display_mode or fallback_display_mode or "side_by_side")
    try:
        request_transform_generation = int(transform_generation)
    except (TypeError, ValueError):
        request_transform_generation = int(current_transform_generation or 0)
    if not bool(preview_active) or not bool(model_is_preview_data):
        return AlignmentD3D11PackageStartRouteState(
            should_start=False,
            should_drop=False,
            drop_reason="",
            display_mode=requested_display_mode,
            rebuild_reason=_normalized_rebuild_reason(reason),
            transform_generation=request_transform_generation,
        )
    return AlignmentD3D11PackageStartRouteState(
        should_start=True,
        should_drop=False,
        drop_reason="",
        display_mode=requested_display_mode,
        rebuild_reason=_normalized_rebuild_reason(reason),
        transform_generation=request_transform_generation,
    )


def alignment_d3d11_process_start_route(
    *,
    dialog_live: bool,
    request_id: object,
    current_request_id: object,
    drag_active: bool,
    drag_reload_stale: bool,
) -> AlignmentD3D11ProcessStartRouteState:
    normalized_request_id = _request_id(request_id)
    if not bool(dialog_live):
        return AlignmentD3D11ProcessStartRouteState(False, True, "dialog_closing", False, "", False)
    if normalized_request_id > 0 and normalized_request_id != _request_id(current_request_id):
        return AlignmentD3D11ProcessStartRouteState(False, True, "stale_request", False, "", False)
    if bool(drag_active):
        return AlignmentD3D11ProcessStartRouteState(
            should_start=False,
            should_drop=True,
            drop_reason="active_drag",
            should_pause_loading=True,
            pause_message="Preview reload paused during movement.",
            should_handle_stale_drag=False,
        )
    if normalized_request_id > 0 and bool(drag_reload_stale):
        return AlignmentD3D11ProcessStartRouteState(False, False, "", False, "", True)
    return AlignmentD3D11ProcessStartRouteState(True, False, "", False, "", False)


def alignment_d3d11_package_ready_route(
    *,
    dialog_live: bool,
    request_id: object,
    current_request_id: object,
    drag_reload_stale: bool,
) -> AlignmentD3D11PackageReadyRouteState:
    normalized_request_id = _request_id(request_id)
    if not bool(dialog_live):
        return AlignmentD3D11PackageReadyRouteState(False, True, "dialog_closing", False)
    if normalized_request_id != _request_id(current_request_id):
        return AlignmentD3D11PackageReadyRouteState(False, True, "stale_request", False)
    if bool(drag_reload_stale):
        return AlignmentD3D11PackageReadyRouteState(False, False, "", True)
    return AlignmentD3D11PackageReadyRouteState(True, False, "", False)


def alignment_d3d11_process_reuse_state(
    *,
    process_active: bool,
    host_ready: bool,
    host_detail: object,
) -> AlignmentD3D11ProcessReuseState:
    return AlignmentD3D11ProcessReuseState(
        can_reuse_process=bool(process_active and host_ready),
        should_report_restart=bool(process_active and not host_ready),
        host_detail=str(host_detail or ""),
    )


def alignment_d3d11_active_package_matches(
    *,
    process_active: bool,
    active_package: object,
    package: object,
) -> bool:
    if not bool(process_active):
        return False
    active_path = _package_path(active_package)
    package_path = _package_path(package)
    if active_path is None or package_path is None:
        return False
    return _paths_match(active_path, package_path)


def alignment_d3d11_package_drop_cleanup_state(
    *,
    package: object,
    active_package: object,
    process_active: bool,
) -> AlignmentD3D11PackageDropCleanupState:
    package_path = _package_path(package)
    active_package_matches = alignment_d3d11_active_package_matches(
        process_active=process_active,
        active_package=active_package,
        package=package_path,
    )
    return AlignmentD3D11PackageDropCleanupState(
        package_path=package_path,
        should_cleanup=package_path is not None and not active_package_matches,
        active_package_matches=active_package_matches,
    )


def alignment_d3d11_active_package_snapshot(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "active_package": state.get("active_package"),
        "active_package_request_id": _request_id(state.get("active_package_request_id")),
        "active_package_display_mode": str(state.get("active_package_display_mode", "") or ""),
        "active_package_quality": str(state.get("active_package_quality", "") or ""),
        "active_package_cache_key": str(state.get("active_package_cache_key", "") or ""),
    }


def alignment_d3d11_prepare_active_package(
    state: MutableMapping[str, object],
    *,
    package: object,
    request_id: int,
    display_mode: str,
    package_quality: str,
    cache_key: str,
    status_file: object,
) -> None:
    state["active_package"] = package
    state["active_package_request_id"] = _request_id(request_id)
    state["active_package_display_mode"] = str(display_mode or "")
    state["active_package_quality"] = str(package_quality or "")
    state["active_package_cache_key"] = str(cache_key or "")
    state["status_file"] = status_file
    state["status_signature"] = (0, 0)
    state["status_payload_text"] = ""
    state["preview_loaded"] = False
    state["resources_loaded"] = False


def alignment_d3d11_restore_active_package(
    state: MutableMapping[str, object],
    snapshot: Mapping[str, object],
) -> None:
    state["active_package"] = snapshot.get("active_package")
    state["active_package_request_id"] = _request_id(snapshot.get("active_package_request_id"))
    state["active_package_display_mode"] = str(snapshot.get("active_package_display_mode", "") or "")
    state["active_package_quality"] = str(snapshot.get("active_package_quality", "") or "")
    state["active_package_cache_key"] = str(snapshot.get("active_package_cache_key", "") or "")


def alignment_d3d11_clear_active_package(
    state: MutableMapping[str, object],
    *,
    clear_process: bool = False,
    clear_request_id: bool = True,
    clear_status: bool = False,
) -> object:
    package = state.get("active_package")
    if clear_process:
        state["process"] = None
    state["active_package"] = None
    if clear_request_id:
        state["active_package_request_id"] = 0
    state["active_package_display_mode"] = ""
    state["active_package_quality"] = ""
    state["active_package_cache_key"] = ""
    if clear_status:
        state["status_file"] = None
        state["status_signature"] = (0, 0)
        state["status_payload_text"] = ""
    return package


def alignment_d3d11_record_process_ref(state: MutableMapping[str, object], process: object) -> None:
    state["process"] = process


def alignment_d3d11_clear_process_status_refs(state: MutableMapping[str, object]) -> None:
    state["process"] = None
    state["status_file"] = None


def alignment_d3d11_record_pending_process_retry(
    state: MutableMapping[str, object],
    *,
    package: object,
) -> int:
    retry_count = int(state.get("pending_process_retry_count", 0) or 0) + 1
    state["pending_process_retry_count"] = retry_count
    state["pending_process_package"] = package
    return retry_count


def alignment_d3d11_clear_pending_process_retry(state: MutableMapping[str, object]) -> None:
    state["pending_process_retry_count"] = 0
    state["pending_process_package"] = None


__all__ = [
    "AlignmentD3D11PackageDropCleanupState",
    "AlignmentD3D11PackageStartRouteState",
    "AlignmentD3D11PackageReadyRouteState",
    "AlignmentD3D11ProcessReuseState",
    "AlignmentD3D11ProcessStartRouteState",
    "alignment_d3d11_active_package_matches",
    "alignment_d3d11_active_package_snapshot",
    "alignment_d3d11_clear_active_package",
    "alignment_d3d11_clear_pending_process_retry",
    "alignment_d3d11_clear_process_status_refs",
    "alignment_d3d11_package_drop_cleanup_state",
    "alignment_d3d11_package_start_route",
    "alignment_d3d11_package_ready_route",
    "alignment_d3d11_prepare_active_package",
    "alignment_d3d11_process_reuse_state",
    "alignment_d3d11_process_start_route",
    "alignment_d3d11_record_pending_process_retry",
    "alignment_d3d11_record_process_ref",
    "alignment_d3d11_restore_active_package",
]
