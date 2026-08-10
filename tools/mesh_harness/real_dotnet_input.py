from __future__ import annotations

from collections.abc import Mapping
import time
from types import SimpleNamespace

from tools.mesh_harness.win32_input import (
    _activate_window_for_input,
    _foreground_window_matches,
    _host_window_rect,
    _screen_cursor_position,
    _send_left_button_input,
    _set_screen_cursor_position,
    _window_at_screen_point,
    _window_is_same_or_child,
    _window_process_id,
)
from tools.mesh_harness.real_dotnet_zoom_input import (
    _foreground_root_hwnd,
    exercise_side_by_side_wheel_zoom,
)

def drive_viewport_selection(
    state: SimpleNamespace,
    *,
    point: tuple[float, float],
    pump_for,
    pump_until,
) -> dict[str, object]:
    """Drive a real Brush/Replace Select gesture into the editable pane.

    The result intentionally records the helper's emitted ``select_request``
    packets.  The caller must then ask the helper for ``tool_state_applied`` and
    verify the authoritative vertex map; that round trip proves the physical
    gesture, native selection, and PARTS isolation together.
    """

    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    start = (
        int(round(min(max(point[0], 2.0), max(2.0, width - 8.0)))),
        int(round(min(max(point[1], 2.0), max(2.0, height - 2.0)))),
    )
    end = (start[0] + 8, start[1])
    viewport_rect = _host_window_rect(state.viewport_hwnd)
    screen_x = (
        int(state.viewport.get("screen_x", 0) or 0)
        if "screen_x" in state.viewport
        else int(viewport_rect[0]) if viewport_rect else 0
    )
    screen_y = (
        int(state.viewport.get("screen_y", 0) or 0)
        if "screen_y" in state.viewport
        else int(viewport_rect[1]) if viewport_rect else 0
    )
    original_cursor = _screen_cursor_position()
    button_down = False
    moved = False
    down_sent = False
    up_sent = False
    target_hwnd = 0
    target_pid = 0
    request_cursor = len(state.tab.standalone_dotnet_protocol_events)
    settled = False
    try:
        activated = _activate_window_for_input(
            state.viewport_hwnd,
            root_hwnd=_foreground_root_hwnd(state),
        )
        if activated:
            pump_for(state, 0.05)
            moved = _set_screen_cursor_position(screen_x + start[0], screen_y + start[1])
            pump_for(state, 0.03)
            target_hwnd = _window_at_screen_point(screen_x + start[0], screen_y + start[1])
            target_pid = _window_process_id(target_hwnd)
        target_safe = bool(
            activated
            and moved
            and _foreground_window_matches(_foreground_root_hwnd(state))
            and target_pid == state.production_process_pid
            and _window_is_same_or_child(state.viewport_hwnd, target_hwnd)
        )
        if target_safe:
            down_sent = _send_left_button_input(down=True)
            button_down = down_sent
        if down_sent:
            for offset in (2, 4, 6):
                moved = bool(
                    moved
                    and _set_screen_cursor_position(screen_x + start[0] + offset, screen_y + start[1])
                )
                pump_for(state, 0.035)
            # Release two pixels beyond the last sampled point without another
            # cadence wait. The queued MouseMove is too close to become a new
            # sample, so MouseUp emits the mandatory paint_final request instead
            # of mistaking the last intermediate dab for a completed gesture.
            moved = bool(
                moved
                and _set_screen_cursor_position(screen_x + end[0], screen_y + end[1])
            )
            up_sent = _send_left_button_input(down=False)
            button_down = False
            final_request_seen = pump_until(
                state,
                lambda: any(
                    str(event.get("event", "") or "") == "select_request"
                    and event.get("paint_final") is True
                    for event in tuple(state.tab.standalone_dotnet_protocol_events)[request_cursor:]
                ),
                2.0,
            )
            settled = bool(
                final_request_seen
                and pump_until(
                    state,
                    lambda: not state.tab._standalone_action_worker_active(),
                    5.0,
                )
            )
    finally:
        if button_down:
            _send_left_button_input(down=False)
        if original_cursor is not None:
            _set_screen_cursor_position(*original_cursor)
    requests = [
        dict(event)
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[request_cursor:]
        if str(event.get("event", "") or "") == "select_request"
    ]
    return {
        "backend": "win32_physical_cursor",
        "start": list(start),
        "end": list(end),
        "screen_origin": [int(screen_x), int(screen_y)],
        "viewport_hwnd": int(state.viewport_hwnd or 0),
        "viewport_rect": list(viewport_rect) if viewport_rect else None,
        "input_target_hwnd": int(target_hwnd or 0),
        "input_target_pid": int(target_pid or 0),
        "target_is_viewport_hwnd": int(target_hwnd or 0) == int(state.viewport_hwnd or 0),
        "mouse_down_sent": bool(down_sent),
        "mouse_move_sent": bool(moved),
        "mouse_up_sent": bool(up_sent),
        "select_request_count": len(requests),
        "select_requests": requests,
        "authority_settled": bool(settled),
        "ok": bool(down_sent and moved and up_sent and requests and settled),
    }


def _prepare_viewport_stroke(
    state: SimpleNamespace,
) -> tuple[tuple[int, int], int, int, int, float] | str:
    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    start = (
        int(round(min(max(state.projected_center[0], 1.0), max(1.0, width - 2.0)))),
        int(round(min(max(state.projected_center[1], 1.0), max(1.0, height - 2.0)))),
    )
    state.mouse_drag_start = start
    state.mouse_drag_points = tuple((start[0] + offset, start[1]) for offset in range(1, 41))
    state.mouse_drag_end = state.mouse_drag_points[-1]
    projection_width = int(getattr(state, "projection_viewport_width", 0) or 0)
    projection_height = int(getattr(state, "projection_viewport_height", 0) or 0)
    if projection_width and projection_height and (projection_width, projection_height) != (width, height):
        return (
            "The .NET viewport rectangle disagrees with the surface its projection was built for: "
            f"stroke bounds {width}x{height}, projection {projection_width}x{projection_height}."
        )
    if state.mouse_drag_end[0] >= width:
        return (
            "Projected drag would leave the .NET viewport. "
            f"projected_center={state.projected_center} clamped_start={start} viewport={width}x{height}"
        )

    state.form_rect_before = _host_window_rect(state.form_hwnd)
    state.viewport_rect_before = _host_window_rect(state.viewport_hwnd)
    state.action_started = time.perf_counter()
    heartbeat_index = len(state.heartbeat_ms)
    heartbeat_origin = (time.perf_counter() - state.heartbeat_started) * 1000.0
    state.measure_stroke_handlers = True
    state.stroke_updates = []
    state.mouse_move_sent = False
    state.mouse_down_sent = False
    state.mouse_up_sent = False
    state.stroke_started = {}
    state.stroke_finished = {}
    viewport_rect = state.viewport_rect_before
    screen_x = (
        int(state.viewport.get("screen_x", 0) or 0)
        if "screen_x" in state.viewport
        else int(viewport_rect[0]) if viewport_rect else 0
    )
    screen_y = (
        int(state.viewport.get("screen_y", 0) or 0)
        if "screen_y" in state.viewport
        else int(viewport_rect[1]) if viewport_rect else 0
    )
    return start, screen_x, screen_y, heartbeat_index, heartbeat_origin


def _drive_physical_viewport_stroke(
    state: SimpleNamespace,
    *,
    start: tuple[int, int],
    screen_x: int,
    screen_y: int,
    pump_for,
    wait_protocol_event,
) -> str:
    input_error = ""
    original_cursor = _screen_cursor_position()
    button_down = False
    try:
        state.input_window_activated = _activate_window_for_input(
            state.viewport_hwnd,
            root_hwnd=_foreground_root_hwnd(state),
        )
        if not state.input_window_activated:
            input_error = "The .NET viewport could not be made the foreground input target."
        else:
            pump_for(state, 0.05)
            state.mouse_move_sent = _set_screen_cursor_position(screen_x + start[0], screen_y + start[1])
            pump_for(state, 0.03)
            state.input_target_hwnd = _window_at_screen_point(screen_x + start[0], screen_y + start[1])
            state.input_target_pid = _window_process_id(state.input_target_hwnd)
            target_safe = bool(
                _foreground_window_matches(_foreground_root_hwnd(state))
                and state.input_target_pid == state.production_process_pid
                and _window_is_same_or_child(state.viewport_hwnd, state.input_target_hwnd)
            )
            if not target_safe:
                input_error = "The .NET viewport was not the foreground visible input target."
        if not input_error:
            cursor = len(state.tab.standalone_dotnet_protocol_events)
            state.mouse_down_sent = _send_left_button_input(down=True)
            button_down = state.mouse_down_sent
            state.stroke_started = wait_protocol_event(state, "stroke_begin", cursor, 2.0)
            if not state.stroke_started:
                input_error = "The .NET viewport did not begin the physical mouse stroke."

        update_cursor = len(state.tab.standalone_dotnet_protocol_events)
        for x, y in state.mouse_drag_points:
            if input_error:
                break
            state.mouse_move_sent = bool(
                state.mouse_move_sent and _set_screen_cursor_position(screen_x + x, screen_y + y)
            )
            # Authoritative packets are bounded to the protocol cadence. Keep
            # the physical path moving and let the terminal packet prove that
            # coalescing retained the full cursor travel.
            pump_for(state, 0.004)
        pump_for(state, 0.02)
        state.mouse_drag_actual_screen_end = _screen_cursor_position()
        state.viewport_rect_at_release = _host_window_rect(state.viewport_hwnd)
        state.mouse_drag_effective_end = state.mouse_drag_end
        if state.mouse_drag_actual_screen_end is not None and state.viewport_rect_at_release is not None:
            state.mouse_drag_effective_end = (
                int(state.mouse_drag_actual_screen_end[0]) - int(state.viewport_rect_at_release[0]),
                int(state.mouse_drag_actual_screen_end[1]) - int(state.viewport_rect_at_release[1]),
            )
        cursor = len(state.tab.standalone_dotnet_protocol_events)
        state.mouse_up_sent = _send_left_button_input(down=False) if button_down else False
        button_down = False
        state.stroke_finished = wait_protocol_event(state, "stroke_end", cursor, 2.0)
        state.stroke_updates = [
            dict(event)
            for event in tuple(state.tab.standalone_dotnet_protocol_events)[update_cursor:]
            if str(event.get("event", "") or "") == "stroke_update"
        ]
    finally:
        if button_down:
            _send_left_button_input(down=False)
        if original_cursor is not None:
            _set_screen_cursor_position(*original_cursor)
    return input_error


def _settle_viewport_stroke(
    state: SimpleNamespace,
    *,
    heartbeat_index: int,
    heartbeat_origin: float,
    pump_for,
    pump_until,
    capture_viewport,
) -> None:
    state.measure_stroke_handlers = False
    if state.stroke_started:
        pump_until(
            state,
            lambda: (
                state.tab.standalone_live_stroke_dispatcher is not None
                and not any(
                    int(state.tab.standalone_live_stroke_dispatcher.metrics().get(key, 0) or 0)
                    for key in ("queue_depth", "control_depth", "active")
                )
            ),
            5.0,
        )
    pump_for(state, 0.05)
    pump_until(
        state,
        lambda: int(state.tab.standalone_dotnet_update_queue.metrics().get("active_revision", 0) or 0) == 0,
        5.0,
    )
    state.action_elapsed_ms = (time.perf_counter() - state.action_started) * 1000.0
    state.form_rect_after = _host_window_rect(state.form_hwnd)
    state.viewport_rect_after = _host_window_rect(state.viewport_hwnd)
    heartbeat_elapsed = (time.perf_counter() - state.action_started) * 1000.0
    heartbeat_samples = [value - heartbeat_origin for value in state.heartbeat_ms[heartbeat_index:]]
    heartbeat_points = [0.0, *heartbeat_samples, heartbeat_elapsed]
    state.heartbeat_gaps = [
        heartbeat_points[index] - heartbeat_points[index - 1]
        for index in range(1, len(heartbeat_points))
    ]
    state.max_heartbeat_gap_ms = max(state.heartbeat_gaps, default=heartbeat_elapsed)
    state.after_capture_summary = capture_viewport(state, state.after_capture_path)


def _validate_viewport_stroke(state: SimpleNamespace, input_error: str, base_error):
    if input_error:
        return base_error(state, input_error)
    if not state.mouse_move_sent or not state.mouse_up_sent or not state.stroke_finished:
        return base_error(state, "The .NET viewport did not complete the physical mouse stroke.")
    terminal_drag = state.stroke_finished.get("screen_drag", {})
    terminal_drag = terminal_drag if isinstance(terminal_drag, Mapping) else {}
    state.stroke_terminal_coverage = {
        "requested_end": list(state.mouse_drag_end),
        "expected_end": list(state.mouse_drag_effective_end),
        "reported_end": [
            int(terminal_drag.get("end_x", -1)),
            int(terminal_drag.get("end_y", -1)),
        ],
        "actual_screen_end": list(state.mouse_drag_actual_screen_end)
        if state.mouse_drag_actual_screen_end is not None
        else None,
        "viewport_rect_at_release": list(state.viewport_rect_at_release)
        if state.viewport_rect_at_release is not None
        else None,
        "viewport_stationary_to_release": bool(
            state.viewport_rect_before
            and state.viewport_rect_before == state.viewport_rect_at_release
        ),
        "protocol_update_count": len(state.stroke_updates),
        "physical_point_count": len(state.mouse_drag_points),
    }
    state.stroke_terminal_coverage["ok"] = bool(
        state.stroke_terminal_coverage["reported_end"]
        == state.stroke_terminal_coverage["expected_end"]
    )
    if not state.stroke_updates:
        return base_error(state, "The .NET viewport published no bounded update during the physical mouse stroke.")
    if not state.stroke_terminal_coverage["ok"]:
        return base_error(state, "The .NET viewport coalesced away terminal cursor travel.")
    return None


def drive_viewport_stroke(
    state: SimpleNamespace,
    *,
    base_error,
    pump_for,
    pump_until,
    wait_protocol_event,
    capture_viewport,
) -> dict[str, object] | None:
    prepared = _prepare_viewport_stroke(state)
    if isinstance(prepared, str):
        return base_error(state, prepared)
    start, screen_x, screen_y, heartbeat_index, heartbeat_origin = prepared
    input_error = _drive_physical_viewport_stroke(
        state,
        start=start,
        screen_x=screen_x,
        screen_y=screen_y,
        pump_for=pump_for,
        wait_protocol_event=wait_protocol_event,
    )
    _settle_viewport_stroke(
        state,
        heartbeat_index=heartbeat_index,
        heartbeat_origin=heartbeat_origin,
        pump_for=pump_for,
        pump_until=pump_until,
        capture_viewport=capture_viewport,
    )
    return _validate_viewport_stroke(state, input_error, base_error)


__all__ = ["drive_viewport_stroke", "exercise_side_by_side_wheel_zoom"]
