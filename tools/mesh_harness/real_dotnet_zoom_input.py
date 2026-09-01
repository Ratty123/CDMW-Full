from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
import time
from types import SimpleNamespace

from tools.mesh_harness.constants import (
    _MK_LBUTTON,
    _WM_LBUTTONDOWN,
    _WM_LBUTTONUP,
    _WM_MOUSEWHEEL,
)
from tools.mesh_harness.real_dotnet_material import request_full_renderer_status
from tools.mesh_harness.win32_input import (
    _host_window_rect,
    _restore_physical_mouse_state,
    _scoped_input_target_matches,
    _send_physical_mouse_message,
    _send_mouse_message,
    _show_window_without_activation,
    _window_process_id,
)


def _send_scoped_mouse_wheel(
    hwnd: int,
    screen_x: int,
    screen_y: int,
    delta: int,
) -> bool:
    wheel_wparam = (int(delta) & 0xFFFF) << 16
    return _send_mouse_message(
        hwnd,
        _WM_MOUSEWHEEL,
        screen_x,
        screen_y,
        wparam=wheel_wparam,
    )


def _renderer_after_metrics(
    state: SimpleNamespace,
    cursor: int,
    pump_until,
) -> dict[str, object]:
    renderer: dict[str, object] = {}

    def locate() -> bool:
        nonlocal renderer
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) != "metrics":
                continue
            candidate = event.get("renderer")
            if isinstance(candidate, Mapping):
                renderer = dict(candidate)
                return True
        return False

    pump_until(state, locate, 2.0)
    return renderer


def _latest_view_state_presentation(
    state: SimpleNamespace,
    cursor: int,
    pump_until,
    timeout_seconds: float = 5.0,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Read the newest presentation the renderer actually published.

    A ``view_state_changed`` event carries the presentation status payload
    directly: pane rectangles plus a camera per view context, republished
    whenever a camera moves. The per-frame metrics payload carries neither
    since the frame-pacing work slimmed it, so it cannot say where the panes
    are or where their cameras ended up after a wheel. Reading the pre-wheel
    status instead would answer every post-wheel question with the camera the
    wheel was supposed to change, turning this proof into a tautology.
    """

    latest: dict[str, object] = {}

    def locate() -> bool:
        nonlocal latest
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) == "view_state_changed":
                latest = dict(event)
        return bool(latest)

    pump_until(state, locate, timeout_seconds)
    cameras: dict[str, dict[str, object]] = {}
    for raw_context in tuple(latest.get("view_contexts", ()) or ()):
        if not isinstance(raw_context, Mapping):
            continue
        context_id = str(raw_context.get("id", "") or "")
        raw_camera = raw_context.get("camera")
        if context_id and isinstance(raw_camera, Mapping):
            cameras[context_id] = dict(raw_camera)
    return latest, cameras


def _presentation_cameras(renderer: Mapping[str, object]) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    raw_presentation = renderer.get("presentation")
    presentation = dict(raw_presentation) if isinstance(raw_presentation, Mapping) else {}
    cameras: dict[str, dict[str, object]] = {}
    for raw_context in tuple(presentation.get("view_contexts", ()) or ()):
        if not isinstance(raw_context, Mapping):
            continue
        context_id = str(raw_context.get("id", "") or "")
        raw_camera = raw_context.get("camera")
        if context_id and isinstance(raw_camera, Mapping):
            cameras[context_id] = dict(raw_camera)
    return presentation, cameras


def _camera_without_zoom_or_pan(camera: Mapping[str, object]) -> dict[str, object]:
    # fit_relative_zoom is the same zoom expressed against the fitted distance,
    # so a zoom step necessarily moves it (206.34 -> 154.75 alongside 1 -> 0.75)
    # and comparing it here asked the camera not to zoom while being zoomed.
    # The zoom magnitude is asserted separately as an exact 0.75 archive step,
    # and the anchor by the world-space pan below; everything else -- yaw,
    # pitch, fit mode, bounds, context -- still has to match exactly.
    return {
        str(key): value
        for key, value in camera.items()
        if str(key) not in {"zoom", "pan", "fit_relative_zoom"}
    }


def _camera_world_pan(camera: Mapping[str, object]) -> tuple[float, float] | None:
    raw_pan = camera.get("pan")
    if not isinstance(raw_pan, (list, tuple)) or len(raw_pan) < 2:
        return None
    try:
        zoom = float(camera.get("zoom", 0.0) or 0.0)
        if zoom <= 0.0:
            return None
        return (float(raw_pan[0]) / zoom, float(raw_pan[1]) / zoom)
    except (TypeError, ValueError, OverflowError):
        return None


def _camera_preserves_native_zoom_anchor(
    initial: Mapping[str, object],
    zoomed: Mapping[str, object],
) -> bool:
    initial_world_pan = _camera_world_pan(initial)
    zoomed_world_pan = _camera_world_pan(zoomed)
    return bool(
        initial_world_pan is not None
        and zoomed_world_pan is not None
        and _camera_without_zoom_or_pan(zoomed) == _camera_without_zoom_or_pan(initial)
        and abs(zoomed_world_pan[0] - initial_world_pan[0]) <= 0.00001
        and abs(zoomed_world_pan[1] - initial_world_pan[1]) <= 0.00001
    )


def _harness_root_hwnd(state: SimpleNamespace) -> int:
    win_id = getattr(getattr(state, "tab", None), "winId", None)
    if callable(win_id):
        try:
            return int(win_id())
        except (TypeError, ValueError, RuntimeError):
            pass
    return int(getattr(state, "form_hwnd", 0) or 0)


def _pane_image_evidence(path: Path, rectangle: Mapping[str, object]) -> dict[str, object]:
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        x = max(0, int(rectangle.get("x", 0) or 0))
        y = max(0, int(rectangle.get("y", 0) or 0))
        width = max(1, int(rectangle.get("width", 0) or 0))
        height = max(1, int(rectangle.get("height", 0) or 0))
        right = min(image.width, x + width)
        bottom = min(image.height, y + height)
        crop = image.crop((x, y, right, bottom))
        inset = min(16, max(0, min(crop.width, crop.height) // 8))
        hash_region = crop.crop(
            (
                inset,
                inset,
                max(inset + 1, crop.width - inset),
                max(inset + 1, crop.height - inset),
            )
        )
        center = crop.crop(
            (
                crop.width // 4,
                crop.height // 4,
                max(crop.width // 4 + 1, crop.width * 3 // 4),
                max(crop.height // 4 + 1, crop.height * 3 // 4),
            )
        )
        sampled = list(center.getdata())
        foreground = [
            pixel
            for pixel in sampled
            if abs(pixel[0] - 18) + abs(pixel[1] - 20) + abs(pixel[2] - 25) > 36
        ]
        return {
            "sha256": sha256(hash_region.tobytes()).hexdigest(),
            "hash_region": "rendered_interior_16px_inset",
            "width": crop.width,
            "height": crop.height,
            "center_sample_count": len(sampled),
            "center_foreground_count": len(foreground),
            "center_unique_color_count": len(set(sampled)),
            "model_still_visible": bool(len(foreground) >= 64 and len(set(sampled)) >= 16),
        }


def _capture_settled_panes(
    state: SimpleNamespace,
    path: Path,
    rectangles: Mapping[str, object],
    *,
    pump_for,
    capture_viewport,
) -> dict[str, object]:
    """Capture until two consecutive frames hash identically in every role pane."""

    previous_hashes: tuple[str, ...] | None = None
    summary: dict[str, object] = {}
    if not any(
        role in {"reference", "editable"} and isinstance(rectangle, Mapping)
        for role, rectangle in rectangles.items()
    ):
        # Without pane rectangles the hash tuple below is empty, and an
        # empty tuple can never satisfy the settle comparison: the loop
        # would spin its full budget and then blame the GPU. Report the
        # missing input instead.
        return {
            "ok": False,
            "error": (
                "The renderer reported no side-by-side pane rectangles to compare; "
                "the presentation payload was unavailable."
            ),
            "settle_pane_rectangles": dict(rectangles),
        }
    # Ten samples with slightly longer late pumps: a transient frame (a
    # metrics repaint, a focus flash) must not fail the settle proof.
    attempts: list[dict[str, object]] = []
    for capture_index in range(10):
        pump_for(state, 0.2 if capture_index < 5 else 0.35)
        summary = dict(capture_viewport(state, path) or {})
        if not summary.get("ok"):
            return summary
        pane_evidence = {
            role: _pane_image_evidence(path, rectangle)
            for role, rectangle in sorted(rectangles.items())
            if role in {"reference", "editable"} and isinstance(rectangle, Mapping)
        }
        current_hashes = tuple(
            str(evidence.get("sha256", "") or "") for evidence in pane_evidence.values()
        )
        attempts.append(
            {
                "attempt": capture_index + 1,
                "pane_hashes": list(current_hashes),
                "matched_previous": bool(current_hashes and current_hashes == previous_hashes),
                "panes": {
                    role: {
                        key: value
                        for key, value in evidence.items()
                        if key != "sha256" and isinstance(value, (int, float, str, bool))
                    }
                    for role, evidence in pane_evidence.items()
                },
            }
        )
        if current_hashes and current_hashes == previous_hashes:
            summary["settled_frame_count"] = capture_index + 1
            summary["settle_attempts"] = attempts
            return summary
        previous_hashes = current_hashes
    # Carry the per-attempt evidence so an unsettled viewport reports which
    # pane kept changing and by how much, instead of only that it did.
    distinct_hashes = {tuple(row["pane_hashes"]) for row in attempts}  # type: ignore[index]
    return {
        **summary,
        "ok": False,
        "error": "The side-by-side GPU panes did not settle to two identical frames.",
        "settle_attempts": attempts,
        "settle_distinct_frame_count": len(distinct_hashes),
        "settle_pane_rectangles": {
            role: dict(rectangle)
            for role, rectangle in rectangles.items()
            if role in {"reference", "editable"} and isinstance(rectangle, Mapping)
        },
    }


def _resolve_side_by_side_presentation(
    state: SimpleNamespace,
    cursor: int,
    pump_until,
) -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, object]]:
    """Return the presentation, per-role cameras and pane rectangles to wheel against.

    Ask the renderer where the panes are right now. No camera has moved yet,
    so no view_state_changed is pending, and the ready status predates the
    side-by-side package: reading it reported a single pane and pane
    rectangles for a layout that no longer existed, which sent the wheel at
    the wrong screen position and left every camera gate failing.
    """

    presentation, cameras = _presentation_cameras(request_full_renderer_status(state, pump_until))
    if not cameras:
        presentation, cameras = _latest_view_state_presentation(state, cursor, pump_until)
    if not cameras:
        presentation, cameras = _presentation_cameras(dict(getattr(state, "renderer", {}) or {}))
    raw_rectangles = presentation.get("pane_rectangles")
    rectangles = dict(raw_rectangles) if isinstance(raw_rectangles, Mapping) else {}
    return presentation, cameras, rectangles


def _activate_side_by_side_divider(
    state: SimpleNamespace,
    viewport_rect,
    rectangles: Mapping[str, object],
    harness_root_hwnd: int,
    pump_for,
) -> tuple[dict[str, object], bool]:
    """Click the pane divider so both panes own input, reporting whether it took."""

    reference_rectangle = rectangles.get("reference")
    editable_rectangle = rectangles.get("editable")
    if not (isinstance(reference_rectangle, Mapping) and isinstance(editable_rectangle, Mapping)):
        return {}, False
    reference_right = int(reference_rectangle.get("x", 0) or 0) + int(
        reference_rectangle.get("width", 0) or 0
    )
    editable_left = int(editable_rectangle.get("x", 0) or 0)
    divider_client_x = (reference_right + editable_left) // 2
    divider_client_y = min(
        24, max(1, int(reference_rectangle.get("height", 0) or 0) // 2)
    )
    divider_x = int(viewport_rect[0]) + divider_client_x
    divider_y = int(viewport_rect[1]) + divider_client_y
    target_visible = _show_window_without_activation(state.viewport_hwnd)
    pump_for(state, 0.04)
    divider_hwnd = int(state.viewport_hwnd)
    divider_pid = _window_process_id(divider_hwnd)
    divider_owned = bool(
        target_visible
        and _scoped_input_target_matches(
            state.viewport_hwnd, state.production_process_pid
        )
        and divider_hwnd == int(state.viewport_hwnd)
    )
    divider_down = bool(
        divider_owned
        and _send_physical_mouse_message(
            state.viewport_hwnd,
            _WM_LBUTTONDOWN,
            divider_client_x,
            divider_client_y,
            wparam=_MK_LBUTTON,
        )
    )
    divider_up = bool(
        divider_down
        and _send_physical_mouse_message(
            state.viewport_hwnd,
            _WM_LBUTTONUP,
            divider_client_x,
            divider_client_y,
        )
    )
    pump_for(state, 0.1)
    activation = {
        "screen_position": [divider_x, divider_y],
        "client_position": [divider_client_x, divider_client_y],
        "target_hwnd": divider_hwnd,
        "target_pid": divider_pid,
        "viewport_owned_before_click": divider_owned,
        "button_down_sent": divider_down,
        "button_up_sent": divider_up,
        "scoped_target_after_click": _scoped_input_target_matches(
            state.viewport_hwnd, state.production_process_pid
        ),
        "ok": bool(
            divider_owned
            and divider_down
            and divider_up
            and _scoped_input_target_matches(
                state.viewport_hwnd, state.production_process_pid
            )
        ),
    }
    return activation, bool(divider_down and not divider_up)


def _point_at_pane(
    state: SimpleNamespace,
    client_x: int,
    client_y: int,
    harness_root_hwnd: int,
    pump_for,
) -> tuple[bool, int, int]:
    """Reveal the viewport without activation and prove its scoped input target.

    The wheel-out and wheel-back halves of a zoom cycle need the identical
    sequence, and a wheel delivered without ownership silently does nothing --
    so both halves must prove it the same way rather than approximately.
    """

    target_visible = _show_window_without_activation(state.viewport_hwnd)
    pump_for(state, 0.04)
    target_hwnd = int(state.viewport_hwnd)
    target_pid = _window_process_id(target_hwnd)
    ownership_ok = bool(
        target_visible
        and _scoped_input_target_matches(
            state.viewport_hwnd, state.production_process_pid
        )
        and target_hwnd == int(state.viewport_hwnd)
        and client_x >= 0
        and client_y >= 0
    )
    return ownership_ok, target_hwnd, target_pid


def _wheel_zoom_role_gates(
    *,
    role: str,
    other_role: str,
    ownership_ok: bool,
    restore_ownership_ok: bool,
    wheel_out_sent: bool,
    wheel_restore_sent: bool,
    initial_zoom: float,
    zoomed_zoom: float,
    zoom_tolerance: float,
    initial_target: Mapping[str, object],
    zoomed_target: Mapping[str, object],
    initial_other: Mapping[str, object],
    zoomed_other: Mapping[str, object],
    initial_presentation: Mapping[str, object],
    zoomed_presentation: Mapping[str, object],
    initial_cameras: Mapping[str, object],
    restored_cameras: Mapping[str, object],
    fitted_panes: Mapping[str, object],
    zoomed_panes: Mapping[str, object],
    restored_panes: Mapping[str, object],
) -> dict[str, bool]:
    """Score one role's wheel cycle: isolation, anchor lock and exact inverse."""

    return {
        "viewport_input_owned": bool(ownership_ok and restore_ownership_ok),
        "wheel_events_sent": bool(wheel_out_sent and wheel_restore_sent),
        "target_zoomed_out_one_archive_step": bool(
            initial_zoom > 0.0
            and abs(zoomed_zoom - initial_zoom * 0.75) <= zoom_tolerance
        ),
        "target_panned_anchor_locked": _camera_preserves_native_zoom_anchor(
            initial_target,
            zoomed_target,
        ),
        "non_target_camera_unchanged": bool(zoomed_other == initial_other),
        "active_camera_context_unchanged": bool(
            zoomed_presentation.get("active_camera_context")
            == initial_presentation.get("active_camera_context")
        ),
        "inverse_camera_restored_exactly": bool(restored_cameras == initial_cameras),
        "target_pixels_changed": bool(
            fitted_panes.get(role, {}).get("sha256")
            and fitted_panes.get(role, {}).get("sha256")
            != zoomed_panes.get(role, {}).get("sha256")
        ),
        "non_target_pixels_unchanged": bool(
            fitted_panes.get(other_role, {}).get("sha256")
            == zoomed_panes.get(other_role, {}).get("sha256")
        ),
        "zoomed_out_model_still_visible": bool(
            zoomed_panes.get(role, {}).get("model_still_visible")
        ),
        "inverse_pixels_restored_exactly": bool(
            fitted_panes
            and all(
                fitted_panes.get(pane_role, {}).get("sha256")
                == restored_panes.get(pane_role, {}).get("sha256")
                for pane_role in ("reference", "editable")
            )
        ),
    }


def _run_wheel_zoom_for_role(
    state: SimpleNamespace,
    role: str,
    other_role: str,
    rectangle: Mapping[str, object],
    *,
    rectangles: Mapping[str, object],
    initial_presentation: Mapping[str, object],
    initial_cameras: Mapping[str, dict[str, object]],
    fitted_panes: Mapping[str, object],
    viewport_rect,
    harness_root_hwnd: int,
    capture_settled,
    captures: dict[str, dict[str, object]],
    pump_for,
    pump_until,
) -> dict[str, object]:
    """Wheel one role pane out and back, returning that role's evidence row."""

    client_x = int(rectangle.get("x", 0) or 0) + max(
        1, int(rectangle.get("width", 0) or 0) // 2
    )
    client_y = int(rectangle.get("y", 0) or 0) + max(
        1, int(rectangle.get("height", 0) or 0) // 2
    )
    screen_x = int(viewport_rect[0]) + client_x
    screen_y = int(viewport_rect[1]) + client_y
    ownership_ok, target_hwnd, target_pid = _point_at_pane(
        state, client_x, client_y, harness_root_hwnd, pump_for
    )
    metrics_cursor = len(state.tab.standalone_dotnet_protocol_events)
    wheel_out_sent = bool(
        ownership_ok
        and _send_scoped_mouse_wheel(
            state.viewport_hwnd,
            screen_x,
            screen_y,
            -120,
        )
    )
    zoomed_presentation, zoomed_cameras = (
        _latest_view_state_presentation(state, metrics_cursor, pump_until)
        if wheel_out_sent
        else ({}, {})
    )
    zoomed_path = state.output_dir / f"real_archive_dotnet_{role}_zoomed_out.png"
    zoomed_capture = capture_settled(zoomed_path)
    captures[f"{role}_zoomed_out"] = zoomed_capture

    restore_ownership_ok, _restore_target_hwnd, _restore_target_pid = _point_at_pane(
        state, client_x, client_y, harness_root_hwnd, pump_for
    )
    restore_cursor = len(state.tab.standalone_dotnet_protocol_events)
    wheel_restore_sent = bool(
        restore_ownership_ok
        and _send_scoped_mouse_wheel(
            state.viewport_hwnd,
            screen_x,
            screen_y,
            120,
        )
    )
    restored_presentation, restored_cameras = (
        _latest_view_state_presentation(state, restore_cursor, pump_until)
        if wheel_restore_sent
        else ({}, {})
    )
    restored_path = state.output_dir / f"real_archive_dotnet_{role}_zoom_restored.png"
    restored_capture = capture_settled(restored_path)
    captures[f"{role}_restored"] = restored_capture

    initial_target = initial_cameras.get(role, {})
    initial_other = initial_cameras.get(other_role, {})
    zoomed_target = zoomed_cameras.get(role, {})
    zoomed_other = zoomed_cameras.get(other_role, {})
    initial_zoom = float(initial_target.get("zoom", 0.0) or 0.0)
    zoomed_zoom = float(zoomed_target.get("zoom", 0.0) or 0.0)
    zoom_tolerance = max(0.00001, abs(initial_zoom) * 0.000001)
    zoomed_panes = (
        {
            pane_role: _pane_image_evidence(zoomed_path, pane_rectangle)
            for pane_role, pane_rectangle in rectangles.items()
            if pane_role in {"reference", "editable"}
            and isinstance(pane_rectangle, Mapping)
        }
        if zoomed_capture.get("ok")
        else {}
    )
    restored_panes = (
        {
            pane_role: _pane_image_evidence(restored_path, pane_rectangle)
            for pane_role, pane_rectangle in rectangles.items()
            if pane_role in {"reference", "editable"}
            and isinstance(pane_rectangle, Mapping)
        }
        if restored_capture.get("ok")
        else {}
    )
    gates = _wheel_zoom_role_gates(
        role=role,
        other_role=other_role,
        ownership_ok=ownership_ok,
        restore_ownership_ok=restore_ownership_ok,
        wheel_out_sent=wheel_out_sent,
        wheel_restore_sent=wheel_restore_sent,
        initial_zoom=initial_zoom,
        zoomed_zoom=zoomed_zoom,
        zoom_tolerance=zoom_tolerance,
        initial_target=initial_target,
        zoomed_target=zoomed_target,
        initial_other=initial_other,
        zoomed_other=zoomed_other,
        initial_presentation=initial_presentation,
        zoomed_presentation=zoomed_presentation,
        initial_cameras=initial_cameras,
        restored_cameras=restored_cameras,
        fitted_panes=fitted_panes,
        zoomed_panes=zoomed_panes,
        restored_panes=restored_panes,
    )
    return {
        "role": role,
        "pointer_client_position": [client_x, client_y],
        "pointer_screen_position": [screen_x, screen_y],
        "target_hwnd": target_hwnd,
        "target_pid": target_pid,
        "initial_zoom": initial_zoom,
        "zoomed_out_zoom": zoomed_zoom,
        "expected_ratio": 0.75,
        "initial_active_camera_context": initial_presentation.get(
            "active_camera_context"
        ),
        "zoomed_active_camera_context": zoomed_presentation.get(
            "active_camera_context"
        ),
        "restored_active_camera_context": restored_presentation.get(
            "active_camera_context"
        ),
        "fitted_pane": fitted_panes.get(role, {}),
        "zoomed_out_pane": zoomed_panes.get(role, {}),
        "restored_pane": restored_panes.get(role, {}),
        "initial_cameras": initial_cameras,
        "zoomed_cameras": zoomed_cameras,
        "restored_cameras": restored_cameras,
        "gates": gates,
        "ok": all(gates.values()),
    }


def exercise_side_by_side_wheel_zoom(
    state: SimpleNamespace,
    *,
    pump_for,
    pump_until,
    capture_viewport,
) -> dict[str, object]:
    """Wheel each resident role pane through scoped input and prove exact inverse restoration."""

    cursor = len(state.tab.standalone_dotnet_protocol_events)
    initial_presentation, initial_cameras, rectangles = _resolve_side_by_side_presentation(
        state,
        cursor,
        pump_until,
    )

    def capture_settled(path: Path) -> dict[str, object]:
        return _capture_settled_panes(
            state,
            path,
            rectangles,
            pump_for=pump_for,
            capture_viewport=capture_viewport,
        )

    fitted_path = state.output_dir / "real_archive_dotnet_zoom_fitted.png"
    viewport_rect = _host_window_rect(state.viewport_hwnd)
    if viewport_rect is None:
        return {"ok": False, "error": "The .NET viewport has no visible wheel-test rectangle."}
    harness_root_hwnd = _harness_root_hwnd(state)
    divider_activation: dict[str, object] = {}
    divider_button_down = False
    rows: list[dict[str, object]] = []
    captures: dict[str, dict[str, object]] = {}
    try:
        divider_activation, divider_button_down = _activate_side_by_side_divider(
            state,
            viewport_rect,
            rectangles,
            harness_root_hwnd,
            pump_for,
        )
        fitted_capture = capture_settled(fitted_path)
        captures["fitted"] = fitted_capture
        if not fitted_capture.get("ok"):
            return {
                "ok": False,
                "error": "The fitted side-by-side state could not be captured.",
                "fitted_capture": fitted_capture,
            }
        fitted_panes = {
            role: _pane_image_evidence(fitted_path, rectangle)
            for role, rectangle in rectangles.items()
            if role in {"reference", "editable"} and isinstance(rectangle, Mapping)
        }
        for role, other_role in (("reference", "editable"), ("editable", "reference")):
            rectangle = rectangles.get(role)
            if not isinstance(rectangle, Mapping) or role not in initial_cameras or other_role not in initial_cameras:
                return {"ok": False, "error": f"Missing side-by-side camera or rectangle for {role}."}
            rows.append(
                _run_wheel_zoom_for_role(
                    state,
                    role,
                    other_role,
                    rectangle,
                    rectangles=rectangles,
                    initial_presentation=initial_presentation,
                    initial_cameras=initial_cameras,
                    fitted_panes=fitted_panes,
                    viewport_rect=viewport_rect,
                    harness_root_hwnd=harness_root_hwnd,
                    capture_settled=capture_settled,
                    captures=captures,
                    pump_for=pump_for,
                    pump_until=pump_until,
                )
            )
    finally:
        if divider_button_down:
            client_position = tuple(divider_activation.get("client_position", (1, 1)))
            _send_physical_mouse_message(
                state.viewport_hwnd,
                _WM_LBUTTONUP,
                int(client_position[0]),
                int(client_position[1]),
            )
        # The physical divider click must remain focused until the layout
        # change has been pumped, then restore the user's cursor/focus even if
        # the side-by-side proof aborts midway.
        _restore_physical_mouse_state()
    gates = {
        "production_d3d11_backend": dict(getattr(state, "renderer", {}) or {}).get("backend") == "d3d11_vortice_shader",
        "simultaneous_role_panes": initial_presentation.get("simultaneous_role_panes") is True,
        "scoped_divider_activation_owned": divider_activation.get("ok") is True,
        "correct_viewport_ownership": bool(rows and all(row["gates"]["viewport_input_owned"] for row in rows)),
        "each_pane_zoomed_independently": bool(rows and all(row["ok"] for row in rows)),
        "models_remained_visible_and_panned_anchor_locked": bool(
            rows
            and all(
                row["gates"]["zoomed_out_model_still_visible"]
                and row["gates"]["target_panned_anchor_locked"]
                for row in rows
            )
        ),
        "exact_inverse_restoration": bool(
            rows
            and all(
                row["gates"]["inverse_camera_restored_exactly"]
                and row["gates"]["inverse_pixels_restored_exactly"]
                for row in rows
            )
        ),
    }
    return {
        "schema": "cdmw_real_pac_side_by_side_wheel_zoom_v1",
        "input_backend": "restored_physical_mouse_input",
        "renderer_backend": str(dict(getattr(state, "renderer", {}) or {}).get("backend", "") or ""),
        "process_pid": int(state.production_process_pid),
        "window_identity": {
            "form_hwnd": int(state.form_hwnd),
            "viewport_hwnd": int(state.viewport_hwnd),
        },
        "divider_activation": divider_activation,
        "fitted_capture_path": str(fitted_path),
        "captures": captures,
        "roles": rows,
        "gates": gates,
        "ok": all(gates.values()),
    }


__all__ = ["exercise_side_by_side_wheel_zoom"]
