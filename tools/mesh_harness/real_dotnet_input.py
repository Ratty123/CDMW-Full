from __future__ import annotations

from collections.abc import Mapping
import time
from types import SimpleNamespace

from cdmw.services.mesh_interaction_diagnostics import (
    mesh_interaction_diagnostics_snapshot,
)
from tools.mesh_harness.win32_input import (
    _host_window_rect,
)
from tools.mesh_harness.real_dotnet_zoom_input import (
    _harness_root_hwnd,
    exercise_side_by_side_wheel_zoom,
)


_RESIDENT_COMMIT_INT_CORRELATION_FIELDS = (
    "process_generation",
    "helper_process_id",
    "request_id",
    "gesture_id",
    "transaction_sequence",
    "base_revision",
    "target_revision",
    "base_selection_revision",
    "target_selection_revision",
    "topology_generation",
)


def _resident_interaction_probe_result(
    state: SimpleNamespace,
    *,
    cursor: int,
    request_id: int,
) -> dict[str, object]:
    for event in reversed(
        tuple(state.tab.standalone_dotnet_protocol_events)[max(0, int(cursor)) :]
    ):
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event", "") or "") != "resident_interaction_probe_applied":
            continue
        if int(event.get("request_id", 0) or 0) != int(request_id):
            continue
        return dict(event)
    return {}


def request_resident_interaction_probe(
    state: SimpleNamespace,
    *,
    mode: str,
    start: tuple[int, int],
    end: tuple[int, int],
    sample_count: int,
    pump_until,
) -> dict[str, object]:
    """Drive one resident gesture without touching global desktop input.

    The request is consumed by the existing helper protocol drain on the
    WinForms UI thread.  Its diagnostic acknowledgement proves dispatch, while
    the separately emitted resident transaction and commit-v2 ACK remain the
    authority proof.
    """

    cursor = len(state.tab.standalone_dotnet_protocol_events)
    commit_ack_cursor = time.perf_counter_ns()
    request_id = int(time.monotonic_ns() & 0x7FFFFFFF) or 1
    payload = {
        "event": "resident_interaction_probe",
        "request_id": request_id,
        "mode": str(mode),
        "start_x": int(start[0]),
        "start_y": int(start[1]),
        "end_x": int(end[0]),
        "end_y": int(end[1]),
        "sample_count": max(1, min(512, int(sample_count))),
    }
    sent = bool(state.tab._send_dotnet_protocol_message(payload))
    if not sent:
        return {
            "ok": False,
            "backend": "helper_ui_thread_resident_probe",
            "request": payload,
            "reason": "protocol_send_rejected",
        }

    def terminal_observed() -> bool:
        events = tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        return bool(
            _resident_interaction_probe_result(
                state,
                cursor=cursor,
                request_id=request_id,
            )
            and any(
                isinstance(event, Mapping)
                and str(event.get("event", "") or "")
                == "resident_interaction_transaction"
                for event in events
            )
        )

    observed = bool(pump_until(state, terminal_observed, 10.0))
    probe = _resident_interaction_probe_result(
        state,
        cursor=cursor,
        request_id=request_id,
    )
    transactions = [
        dict(event)
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        if isinstance(event, Mapping)
        and str(event.get("event", "") or "") == "resident_interaction_transaction"
    ]
    transaction = transactions[0] if len(transactions) == 1 else {}
    acknowledgement: dict[str, object] = {}

    def authority_settled() -> bool:
        nonlocal acknowledgement
        if not transaction:
            return False
        acknowledgement = resident_interaction_commit_ack(
            transaction,
            after_monotonic_ns=commit_ack_cursor,
        )
        return bool(
            acknowledgement
            and str(acknowledgement.get("status", "") or "").lower()
            == "applied"
            and not state.tab._standalone_action_worker_active()
        )

    settled = bool(observed and pump_until(state, authority_settled, 20.0))
    probe_status = str(probe.get("status", "") or "").strip().lower()
    probe_ok = probe.get("ok") is True or probe_status in {"applied", "ok"}
    terminal_request_id = int(transaction.get("request_id", 0) or 0)
    mutation_echoes = [
        dict(event)
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        if isinstance(event, Mapping)
        and str(event.get("event", "") or "") == "resident_mutation_batch_ack"
        and int(event.get("request_id", 0) or 0) == terminal_request_id
    ]
    return {
        "ok": bool(
            observed
            and probe_ok
            and len(transactions) == 1
            and settled
            and not mutation_echoes
        ),
        "backend": "helper_ui_thread_resident_probe",
        "request": payload,
        "probe_acknowledgement": probe,
        "resident_interaction_transaction_count": len(transactions),
        "resident_interaction_transactions": transactions,
        "authority_acknowledgement": acknowledgement,
        "authority_settled": settled,
        "helper_originated_mutation_echo_count": len(mutation_echoes),
    }


def resident_interaction_commit_ack(
    transaction: Mapping[str, object],
    *,
    after_monotonic_ns: int = 0,
) -> dict[str, object]:
    """Return the exact host-to-helper commit-v2 ACK for one transaction."""

    if not transaction:
        return {}
    expected_session = str(transaction.get("session_id", "") or "")
    expected_digest = str(transaction.get("sha256", "") or "").lower()
    if not expected_session or not expected_digest:
        return {}
    recent = mesh_interaction_diagnostics_snapshot(recent_limit=512).get(
        "recent_events", ()
    )
    if not isinstance(recent, (list, tuple)):
        return {}
    for candidate in reversed(recent):
        if not isinstance(candidate, Mapping):
            continue
        if str(candidate.get("event", "") or "") != "resident_interaction_commit_ack":
            continue
        if str(candidate.get("direction", "") or "") != "host_to_helper":
            continue
        if candidate.get("sent") is not True:
            continue
        if int(candidate.get("monotonic_ns", 0) or 0) <= int(after_monotonic_ns):
            continue
        if str(candidate.get("session_id", "") or "") != expected_session:
            continue
        if str(candidate.get("sha256", "") or "").lower() != expected_digest:
            continue
        if any(
            int(candidate.get(field, 0) or 0)
            != int(transaction.get(field, 0) or 0)
            for field in _RESIDENT_COMMIT_INT_CORRELATION_FIELDS
        ):
            continue
        return dict(candidate)
    return {}


def drive_viewport_selection(
    state: SimpleNamespace,
    *,
    point: tuple[float, float],
    pump_for,
    pump_until,
) -> dict[str, object]:
    """Drive a Brush/Replace Select gesture on the helper's own UI thread."""

    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    start = (
        int(round(min(max(point[0], 2.0), max(2.0, width - 8.0)))),
        int(round(min(max(point[1], 2.0), max(2.0, height - 2.0)))),
    )
    end = (start[0] + 8, start[1])
    result = request_resident_interaction_probe(
        state,
        mode="select_brush_vertex",
        start=start,
        end=end,
        sample_count=4,
        pump_until=pump_until,
    )
    result.update(
        {
            "start": list(start),
            "end": list(end),
            "viewport_hwnd": int(state.viewport_hwnd or 0),
            "global_mouse_input_used": False,
            "authority_settlement": {
                "action_worker_active_after_wait": bool(
                    state.tab._standalone_action_worker_active()
                ),
                "live_stroke_dispatcher": (
                    dict(state.tab.standalone_live_stroke_dispatcher.metrics())
                    if getattr(state.tab, "standalone_live_stroke_dispatcher", None)
                    is not None
                    else {}
                ),
                "update_queue": dict(
                    state.tab.standalone_dotnet_update_queue.metrics()
                ),
            },
        }
    )
    return result


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
    state.mouse_move_sent = False
    state.mouse_down_sent = False
    state.mouse_up_sent = False
    state.resident_interaction_transactions = []
    state.resident_interaction_acknowledgements = []
    state.resident_interaction_transaction = {}
    state.resident_interaction_acknowledgement = {}
    state.resident_interaction_action_settled = False
    state.resident_interaction_authority_settled = False
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


def _drive_scoped_viewport_stroke(
    state: SimpleNamespace,
    *,
    start: tuple[int, int],
    screen_x: int,
    screen_y: int,
    pump_for,
    pump_until,
    wait_protocol_event,
) -> str:
    result = request_resident_interaction_probe(
        state,
        mode="move",
        start=start,
        end=state.mouse_drag_end,
        sample_count=max(1, len(state.mouse_drag_points)),
        pump_until=pump_until,
    )
    state.resident_interaction_probe = dict(result)
    state.input_window_verified = True
    state.input_target_hwnd = 0
    state.input_target_pid = 0
    # These legacy booleans are consumed by the report as gesture phase
    # coverage.  They now describe the helper-local begin/update/end sequence,
    # not Windows mouse injection; the backend field makes that explicit.
    probe_applied = bool(result.get("ok"))
    state.mouse_down_sent = probe_applied
    state.mouse_move_sent = probe_applied
    state.mouse_up_sent = probe_applied
    state.mouse_drag_injected_client_end = state.mouse_drag_end
    state.mouse_drag_target_screen_end = (
        screen_x + state.mouse_drag_end[0],
        screen_y + state.mouse_drag_end[1],
    )
    state.viewport_rect_at_release = _host_window_rect(state.viewport_hwnd)
    state.mouse_drag_effective_end = state.mouse_drag_end
    state.resident_interaction_transactions = list(
        result.get("resident_interaction_transactions", ()) or ()
    )
    acknowledgement = result.get("authority_acknowledgement", {})
    state.resident_interaction_acknowledgements = (
        [dict(acknowledgement)] if isinstance(acknowledgement, Mapping) and acknowledgement else []
    )
    state.resident_interaction_action_settled = probe_applied
    state.resident_interaction_authority_settled = bool(
        result.get("authority_settled")
    )
    state.resident_interaction_transaction = (
        dict(state.resident_interaction_transactions[0])
        if len(state.resident_interaction_transactions) == 1
        else {}
    )
    state.resident_interaction_acknowledgement = (
        dict(state.resident_interaction_acknowledgements[0])
        if len(state.resident_interaction_acknowledgements) == 1
        else {}
    )
    if probe_applied:
        return ""
    transaction_count = len(state.resident_interaction_transactions)
    if transaction_count == 0:
        return "The .NET viewport published no terminal resident interaction transaction."
    if transaction_count != 1:
        return "The .NET viewport published duplicate terminal resident interaction transactions."
    if not state.resident_interaction_acknowledgements:
        return "The terminal resident interaction transaction was not authoritatively correlated."
    if not state.resident_interaction_authority_settled:
        return "The terminal resident interaction transaction did not settle with one accepted acknowledgement."
    return (
        "The helper-local UI-thread Move probe did not produce one durable "
        f"resident transaction: {result!r}"
    )


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
    if not state.mouse_down_sent or not state.mouse_move_sent or not state.mouse_up_sent:
        return base_error(state, "The .NET viewport did not complete the scoped input stroke.")
    transactions = list(state.resident_interaction_transactions)
    acknowledgements = list(state.resident_interaction_acknowledgements)
    transaction = dict(state.resident_interaction_transaction)
    acknowledgement = dict(state.resident_interaction_acknowledgement)
    state.stroke_terminal_coverage = {
        "requested_end": list(state.mouse_drag_end),
        "effective_end": list(state.mouse_drag_effective_end),
        "injected_client_end": list(state.mouse_drag_injected_client_end),
        "target_screen_end": list(state.mouse_drag_target_screen_end),
        "viewport_rect_at_release": list(state.viewport_rect_at_release)
        if state.viewport_rect_at_release is not None
        else None,
        "viewport_stationary_to_release": bool(
            state.viewport_rect_before
            and state.viewport_rect_before == state.viewport_rect_at_release
        ),
        "input_point_count": len(state.mouse_drag_points),
        "terminal_transaction_count": len(transactions),
        "terminal_request_id": int(transaction.get("request_id", 0) or 0),
        "terminal_gesture_id": int(transaction.get("gesture_id", 0) or 0),
        "correlated_acknowledgement_count": len(acknowledgements),
        "authority_acknowledgement": acknowledgement,
        "action_settled": bool(state.resident_interaction_action_settled),
        "authority_settled": bool(state.resident_interaction_authority_settled),
    }
    state.stroke_terminal_coverage["ok"] = bool(
        len(transactions) == 1
        and len(acknowledgements) == 1
        and state.resident_interaction_authority_settled
    )
    if not transactions:
        return base_error(state, "The .NET viewport published no terminal resident interaction transaction.")
    if len(transactions) != 1:
        return base_error(state, "The .NET viewport published duplicate terminal resident interaction transactions.")
    if not acknowledgements:
        return base_error(state, "The terminal resident interaction transaction was not authoritatively correlated.")
    if len(acknowledgements) != 1 or not state.resident_interaction_authority_settled:
        return base_error(state, "The terminal resident interaction transaction did not settle with one accepted acknowledgement.")
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
    input_error = _drive_scoped_viewport_stroke(
        state,
        start=start,
        screen_x=screen_x,
        screen_y=screen_y,
        pump_for=pump_for,
        pump_until=pump_until,
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


__all__ = [
    "drive_viewport_selection",
    "drive_viewport_stroke",
    "exercise_side_by_side_wheel_zoom",
    "request_resident_interaction_probe",
    "resident_interaction_commit_ack",
]
