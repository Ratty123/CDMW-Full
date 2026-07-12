from __future__ import annotations

import time
from types import SimpleNamespace

from tools.mesh_harness.native_protocol import (
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


def drive_viewport_stroke(
    state: SimpleNamespace,
    *,
    base_error,
    pump_for,
    pump_until,
    wait_protocol_event,
    capture_viewport,
) -> dict[str, object] | None:
    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    start = (
        int(round(min(max(state.projected_center[0], 1.0), max(1.0, width - 2.0)))),
        int(round(min(max(state.projected_center[1], 1.0), max(1.0, height - 2.0)))),
    )
    state.mouse_drag_start = start
    state.mouse_drag_points = tuple((start[0] + offset, start[1]) for offset in range(1, 41))
    state.mouse_drag_end = state.mouse_drag_points[-1]
    if state.mouse_drag_end[0] >= width:
        return base_error(state, "Projected drag would leave the .NET viewport.")
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
    input_error = ""
    original_cursor = _screen_cursor_position()
    viewport_rect = state.viewport_rect_before
    screen_x = int(viewport_rect[0]) if viewport_rect else int(state.viewport.get("screen_x", 0) or 0)
    screen_y = int(viewport_rect[1]) if viewport_rect else int(state.viewport.get("screen_y", 0) or 0)
    button_down = False
    try:
        state.input_window_activated = _activate_window_for_input(
            state.viewport_hwnd,
            root_hwnd=state.form_hwnd,
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
                _foreground_window_matches(state.form_hwnd)
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
        for index, (x, y) in enumerate(state.mouse_drag_points):
            if input_error:
                break
            cursor = len(state.tab.standalone_dotnet_protocol_events)
            state.mouse_move_sent = bool(
                state.mouse_move_sent and _set_screen_cursor_position(screen_x + x, screen_y + y)
            )
            update = wait_protocol_event(state, "stroke_update", cursor, 2.0)
            if not update:
                input_error = f"The .NET viewport missed physical drag update {index + 1}."
                break
            state.stroke_updates.append(update)
        cursor = len(state.tab.standalone_dotnet_protocol_events)
        state.mouse_up_sent = _send_left_button_input(down=False) if button_down else False
        button_down = False
        state.stroke_finished = wait_protocol_event(state, "stroke_end", cursor, 2.0)
    finally:
        if button_down:
            _send_left_button_input(down=False)
        if original_cursor is not None:
            _set_screen_cursor_position(*original_cursor)
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
    if input_error:
        return base_error(state, input_error)
    if len(state.stroke_updates) != len(state.mouse_drag_points):
        return base_error(state, "The .NET viewport did not deliver every drag update through the production protocol.")
    return None


__all__ = ["drive_viewport_stroke"]
