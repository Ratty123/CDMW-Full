"""Pure camera-state helpers for static replacement previews."""

from __future__ import annotations

from collections.abc import Mapping


QtCameraState = tuple[float, float, bool, float, float, tuple[float, float, float]]
CameraStateMapping = dict[str, object]


def alignment_d3d11_camera_active(renderer_kind: object, d3d11_available: bool) -> bool:
    return str(renderer_kind or "").strip().lower() == "d3d11" and bool(d3d11_available)


def alignment_preview_view_sync_should_apply(
    sync_state: Mapping[str, object],
    preview_mode: object,
) -> bool:
    if bool(sync_state.get("active")):
        return False
    return str(preview_mode or "side_by_side") == "side_by_side"


def alignment_active_qt_camera_role(preview_mode: object) -> str:
    active_mode = str(preview_mode or "side_by_side")
    if active_mode == "replacement_only":
        return "replacement_only"
    if active_mode == "overlay":
        return "overlay"
    return "side_by_side"


def alignment_preview_mode_key(mode: object) -> str:
    return str(mode or "side_by_side")


def alignment_preview_mode_saved_state(
    view_states: Mapping[str, object],
    mode: object,
) -> Mapping[str, object] | None:
    state = view_states.get(alignment_preview_mode_key(mode))
    return state if isinstance(state, Mapping) else None


def fixed_alignment_camera_state(
    yaw: float,
    pitch: float,
    *,
    role: str = "replacement",
) -> CameraStateMapping:
    return {
        "role": str(role or "replacement"),
        "yaw": float(yaw),
        "pitch": float(pitch),
        "fit_to_view": True,
        "zoom_factor": 1.0,
        "pan": (0.0, 0.0, 0.0),
    }


def nudged_alignment_camera_state(
    state: Mapping[str, object],
    *,
    delta_yaw: float = 0.0,
    delta_pitch: float = 0.0,
    role: str = "replacement",
) -> CameraStateMapping:
    nudged = dict(state)
    nudged["yaw"] = float(state.get("yaw", -35.0)) + float(delta_yaw)
    nudged["pitch"] = max(-89.0, min(89.0, float(state.get("pitch", 20.0)) + float(delta_pitch)))
    nudged["role"] = str(role or "replacement")
    return nudged


def qt_alignment_camera_state_mapping(
    state: QtCameraState,
    *,
    role: str = "replacement",
) -> CameraStateMapping:
    yaw, pitch, fit_to_view, zoom_factor, _distance, pan = state
    return {
        "role": str(role or "replacement"),
        "yaw": float(yaw),
        "pitch": float(pitch),
        "fit_to_view": bool(fit_to_view),
        "zoom_factor": float(zoom_factor),
        "pan": tuple(float(value) for value in tuple(pan or (0.0, 0.0, 0.0))[:3]),
    }


def qt_alignment_camera_tuple(state: Mapping[str, object], *, fit_distance: float) -> QtCameraState:
    zoom_factor = max(0.1, min(16.0, float(state.get("zoom_factor", 1.0) or 1.0)))
    fit_to_view = bool(state.get("fit_to_view", True))
    pan_value = state.get("pan", (0.0, 0.0, 0.0))
    try:
        pan_tuple = tuple(float(value) for value in tuple(pan_value)[:3])
    except (TypeError, ValueError):
        pan_tuple = (0.0, 0.0, 0.0)
    while len(pan_tuple) < 3:
        pan_tuple = (*pan_tuple, 0.0)
    return (
        float(state.get("yaw", -35.0)),
        float(state.get("pitch", 20.0)),
        fit_to_view,
        zoom_factor,
        float(fit_distance) if fit_to_view else float(fit_distance) / zoom_factor,
        pan_tuple,
    )


__all__ = [
    "CameraStateMapping",
    "QtCameraState",
    "alignment_active_qt_camera_role",
    "alignment_d3d11_camera_active",
    "alignment_preview_mode_key",
    "alignment_preview_mode_saved_state",
    "alignment_preview_view_sync_should_apply",
    "fixed_alignment_camera_state",
    "nudged_alignment_camera_state",
    "qt_alignment_camera_state_mapping",
    "qt_alignment_camera_tuple",
]
