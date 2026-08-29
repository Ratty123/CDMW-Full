from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from PySide6.QtCore import Qt

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.live_stroke_dispatcher import MeshLiveStrokeDispatcher
from cdmw.ui.mesh_editor.stroke_packets import (
    STROKE_MAX_PACKET_BYTES,
    STROKE_MAX_SAMPLES_PER_PACKET,
    STROKE_MAX_SEGMENTS,
    encoded_stroke_command_bytes,
)


class _BlockingController:
    def __init__(self) -> None:
        self.begin_started = threading.Event()
        self.release_begin = threading.Event()
        self.calls: list[str] = []
        self.screen_drags: list[tuple[float, float]] = []
        self.screen_paths: list[tuple[tuple[float, float], ...]] = []
        self.closed = threading.Event()

    def apply(self, action: str, **params: object) -> MeshEditResult:
        marker = str(params.get("marker") or action)
        stop_event = params.get("stop_event")
        assert isinstance(stop_event, threading.Event)
        if marker == "begin":
            self.begin_started.set()
            while not self.release_begin.wait(0.005):
                if stop_event.is_set():
                    break
        screen_drag = params.get("screen_drag")
        if isinstance(screen_drag, Mapping):
            self.screen_drags.append(
                (float(screen_drag["start_x"]), float(screen_drag["end_x"]))
            )
        screen_path = params.get("screen_path")
        if isinstance(screen_path, (tuple, list)):
            self.screen_paths.append(
                tuple(
                    (float(point["x"]), float(point["y"]))
                    for point in screen_path
                    if isinstance(point, Mapping)
                )
            )
        self.calls.append(marker)
        return MeshEditResult(action=action, status="ok", revision=len(self.calls))

    def native_update_for_result(
        self,
        _result: MeshEditResult,
        *,
        stop_event: threading.Event | None = None,
    ) -> MeshEditorNativeUpdate:
        assert isinstance(stop_event, threading.Event)
        return MeshEditorNativeUpdate()

    def close_active_session(self) -> None:
        self.closed.set()


class _FirstUpdateBlockingController(_BlockingController):
    def __init__(self) -> None:
        super().__init__()
        self.release_begin.set()
        self.update_started = threading.Event()
        self.release_update = threading.Event()

    def apply(self, action: str, **params: object) -> MeshEditResult:
        marker = str(params.get("marker") or action)
        stop_event = params.get("stop_event")
        assert isinstance(stop_event, threading.Event)
        if marker == "update-1":
            self.update_started.set()
            while not self.release_update.wait(0.005):
                if stop_event.is_set():
                    break
        return super().apply(action, **params)


def _command(marker: str) -> MeshEditCommand:
    return MeshEditCommand(action="brush", params={"marker": marker})


def _drag_command(start_x: int, end_x: int) -> MeshEditCommand:
    return MeshEditCommand(
        action="transform",
        params={
            "marker": f"update-{end_x}",
            "stroke_id": "cumulative-drag",
            "screen_drag": {
                "start_x": start_x,
                "start_y": 20,
                "end_x": end_x,
                "end_y": 20,
                "viewport_width": 100,
                "viewport_height": 80,
            },
        },
    )


def _selection_command(phase: str, sequence: int) -> MeshEditCommand:
    params: dict[str, object] = {
        "marker": "begin" if phase == "begin" else f"{phase}-{sequence}",
        "selection_stroke_id": "two-minute-selection",
        "selection_stroke_phase": phase,
        "selection_stroke_sequence": sequence,
        "operation": "add",
        "record_history": phase == "end",
    }
    if phase == "update":
        params["_native_screen_selection_payload"] = {
            "target_mode": "vertex",
            "screen_brush": {
                "x": sequence,
                "y": 20,
                "radius_pixels": 12,
            },
        }
    return MeshEditCommand(
        action="select",
        selection=MeshEditSelection(),
        params=params,
    )


def _curved_drag_command(phase: str, sequence: int) -> MeshEditCommand:
    params: dict[str, object] = {
        "marker": "begin" if phase == "begin" else ("end" if phase == "end" else f"drag-{sequence}"),
        "stroke_id": "segmented-drag",
        "stroke_phase": phase,
    }
    if phase == "update":
        start_y = 0 if (sequence - 1) % 2 else 40
        end_y = 0 if sequence % 2 else 40
        params["screen_drag"] = {
            "start_x": sequence - 1,
            "start_y": start_y,
            "end_x": sequence,
            "end_y": end_y,
            "viewport_width": 1920,
            "viewport_height": 1080,
        }
    return MeshEditCommand("transform", params=params)


def _curved_selection_command(phase: str, sequence: int) -> MeshEditCommand:
    command = _selection_command(phase, sequence)
    if phase != "update":
        return command
    params = dict(command.params)
    screen = dict(params["_native_screen_selection_payload"])
    brush = dict(screen["screen_brush"])
    brush["y"] = 0 if sequence % 2 else 40
    screen["screen_brush"] = brush
    params["operation"] = "replace"
    params["_native_screen_selection_payload"] = screen
    return MeshEditCommand("select", selection=command.selection, params=params)


def test_live_stroke_dispatcher_coalesces_pending_updates_latest_wins() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)

        started = time.perf_counter()
        assert dispatcher.submit(controller, _command("update-1"), "update") > 0
        assert dispatcher.submit(controller, _command("update-2"), "update") > 0
        assert dispatcher.submit(controller, _command("update-3"), "update") > 0
        assert dispatcher.submit(controller, _command("end"), "end") > 0
        assert time.perf_counter() - started < 0.05

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "update-3", "end"]
        assert dispatcher.metrics()["coalesced_updates"] == 2
        assert dispatcher.metrics()["queue_depth"] == 0
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_live_stroke_dispatcher_preserves_cumulative_drag_when_updates_coalesce() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    coalesced_request_ids: list[int] = []
    dispatcher.coalesced.connect(
        lambda notice: coalesced_request_ids.extend(
            int(payload["request_id"]) for payload in notice.request_payloads
        )
    )
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin", source="dotnet") > 0
        assert controller.begin_started.wait(1.0)

        for start_x in range(5):
            assert dispatcher.submit(
                controller,
                _drag_command(start_x, start_x + 1),
                "update",
                source="dotnet",
                request_payload={"request_id": start_x + 1},
            ) > 0
        assert dispatcher.submit(controller, _command("end"), "end", source="dotnet") > 0
        pending_update = next(item for item in dispatcher._controls if item.phase == "update")
        assert tuple(payload["request_id"] for payload in pending_update.request_payloads) == (5,)
        assert coalesced_request_ids == [1, 2, 3, 4]

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "update-5", "end"]
        assert controller.screen_drags == [(0.0, 5.0)]
        assert controller.screen_paths == [((0.0, 20.0), (5.0, 20.0))]
        assert dispatcher.metrics()["coalesced_updates"] == 4
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_two_minute_equivalent_selection_stream_keeps_bounded_swept_coverage() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    update_count = 120 * 20
    try:
        assert dispatcher.submit(
            controller,
            _selection_command("begin", 0),
            "begin",
            source="dotnet_selection",
        ) > 0
        assert controller.begin_started.wait(1.0)

        started = time.perf_counter()
        for sequence in range(1, update_count + 1):
            assert dispatcher.submit(
                controller,
                _selection_command("update", sequence),
                "update",
                source="dotnet_selection",
            ) > 0
            metrics = dispatcher.metrics()
            assert metrics["active"] == 1
            assert metrics["queue_depth"] == 1
            assert metrics["control_depth"] == 0
        assert time.perf_counter() - started < 2.0

        terminal_started = time.perf_counter()
        assert dispatcher.submit(
            controller,
            _selection_command("end", update_count + 1),
            "end",
            source="dotnet_selection",
        ) > 0
        assert time.perf_counter() - terminal_started < 0.05
        metrics = dispatcher.metrics()
        assert metrics["queue_depth"] == 0
        assert metrics["control_depth"] == 2
        assert metrics["coalesced_updates"] == update_count - 1
        queued_update = next(item for item in dispatcher._controls if item.phase == "update")
        screen = queued_update.command.params["_native_screen_selection_payload"]
        assert isinstance(screen, Mapping)
        region = screen.get("screen_region")
        assert isinstance(region, Mapping)
        points = region.get("points")
        assert isinstance(points, list)
        assert 2 <= len(points) <= 256
        assert points[0] == [1.0, 20.0]
        assert points[-1] == [float(update_count), 20.0]
        assert "screen_brushes" not in screen
        assert metrics["max_packet_samples"] <= 256
        assert metrics["max_packet_bytes"] <= 64 * 1024
        assert metrics["max_raw_samples"] == update_count

        controller.release_begin.set()
        assert dispatcher.wait_idle(5.0)
        assert controller.calls == ["begin", f"update-{update_count}", f"end-{update_count + 1}"]
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_pending_selection_and_deformation_updates_keep_fifo_stream_boundaries() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    coalesced_request_ids: list[int] = []
    dispatcher.coalesced.connect(
        lambda notice: coalesced_request_ids.extend(
            int(payload["request_id"]) for payload in notice.request_payloads
        )
    )
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)

        assert dispatcher.submit(
            controller,
            _selection_command("update", 1),
            "update",
            source="dotnet_selection",
            request_payload={"request_id": 51},
        ) > 0
        assert dispatcher.submit(
            controller,
            _drag_command(10, 20),
            "update",
            source="dotnet",
            request_payload={"request_id": 52},
        ) > 0
        assert dispatcher.metrics()["control_depth"] == 1
        assert dispatcher.metrics()["queue_depth"] == 1
        assert dispatcher.metrics()["coalesced_updates"] == 0

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "update-1", "update-20"]
        assert coalesced_request_ids == []
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_high_curvature_2400_update_stream_segments_with_bounded_packets_and_outcomes() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    coalesced_ids: list[int] = []
    completed_ids: list[int] = []
    dispatcher.coalesced.connect(
        lambda notice: coalesced_ids.extend(
            int(payload["request_id"]) for payload in notice.request_payloads
        ),
        Qt.ConnectionType.DirectConnection,
    )
    dispatcher.completed.connect(
        lambda outcome: completed_ids.extend(
            int(payload["request_id"]) for payload in outcome.request_payloads
        ),
        Qt.ConnectionType.DirectConnection,
    )
    update_count = 2400
    try:
        assert dispatcher.submit(
            controller,
            _selection_command("begin", 0),
            "begin",
            source="dotnet_selection",
        ) > 0
        assert controller.begin_started.wait(1.0)
        for sequence in range(1, update_count + 1):
            assert dispatcher.submit(
                controller,
                _curved_selection_command("update", sequence),
                "update",
                source="dotnet_selection",
                request_payload={"request_id": sequence},
            ) > 0

        terminal_started = time.perf_counter()
        assert dispatcher.submit(
            controller,
            _selection_command("end", update_count + 1),
            "end",
            source="dotnet_selection",
        ) > 0
        assert time.perf_counter() - terminal_started < 0.05

        updates = [request for request in dispatcher._controls if request.phase == "update"]
        assert 1 < len(updates) <= STROKE_MAX_SEGMENTS
        retained_counts: list[int] = []
        for index, request in enumerate(updates):
            screen = request.command.params["_native_screen_selection_payload"]
            assert isinstance(screen, Mapping)
            region = screen.get("screen_region")
            assert isinstance(region, Mapping)
            points = region.get("points")
            assert isinstance(points, list)
            retained_counts.append(len(points))
            assert len(points) <= STROKE_MAX_SAMPLES_PER_PACKET
            assert encoded_stroke_command_bytes(request.command) <= STROKE_MAX_PACKET_BYTES
            assert request.command.params["selection_stroke_id"] == "two-minute-selection"
            assert request.command.params["record_history"] is False
            assert request.command.params["operation"] == ("replace" if index == 0 else "add")
        assert sum(retained_counts) - (len(retained_counts) - 1) == update_count
        terminal = dispatcher._controls[-1]
        assert terminal.phase == "end"
        assert terminal.command.params["record_history"] is True
        assert terminal.command.params["operation"] == "add"
        metrics = dispatcher.metrics()
        assert metrics["control_depth"] <= STROKE_MAX_SEGMENTS + 1
        assert metrics["max_packet_samples"] <= STROKE_MAX_SAMPLES_PER_PACKET
        assert metrics["max_packet_bytes"] <= STROKE_MAX_PACKET_BYTES

        controller.release_begin.set()
        assert dispatcher.wait_idle(5.0)
        assert sorted((*coalesced_ids, *completed_ids)) == list(range(1, update_count + 1))
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_oversize_update_is_rejected_before_it_enters_the_queue() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        params = dict(_drag_command(0, 1).params)
        params["blob"] = "x" * (STROKE_MAX_PACKET_BYTES + 1)
        command = MeshEditCommand("transform", params=params)

        assert dispatcher.submit(controller, command, "update", source="dotnet") == 0
        assert dispatcher.metrics()["queue_depth"] == 0
        assert dispatcher.metrics()["oversize_rejections"] == 1
        assert dispatcher.metrics()["max_packet_bytes"] == 0
    finally:
        assert dispatcher.stop()


def test_oversize_terminal_becomes_a_correlated_cancel() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    failures = []
    dispatcher.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    try:
        assert dispatcher.submit(
            controller,
            _selection_command("begin", 0),
            "begin",
            source="dotnet_selection",
        ) > 0
        assert controller.begin_started.wait(1.0)
        assert dispatcher.submit(
            controller,
            _selection_command("update", 1),
            "update",
            source="dotnet_selection",
        ) > 0
        terminal = _selection_command("end", 2)
        terminal = MeshEditCommand(
            terminal.action,
            selection=terminal.selection,
            params={**terminal.params, "blob": "x" * (STROKE_MAX_PACKET_BYTES + 1)},
        )

        assert dispatcher.submit(
            controller,
            terminal,
            "end",
            source="dotnet_selection",
        ) > 0
        assert dispatcher.metrics()["oversize_rejections"] == 1
        assert len(failures) == 1
        assert failures[0].phase == "update"

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "select"]
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_high_curvature_deformation_stream_segments_without_cross_id_coalescing() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    coalesced_ids: list[int] = []
    completed_ids: list[int] = []
    dispatcher.coalesced.connect(
        lambda notice: coalesced_ids.extend(
            int(payload["request_id"]) for payload in notice.request_payloads
        ),
        Qt.ConnectionType.DirectConnection,
    )
    dispatcher.completed.connect(
        lambda outcome: completed_ids.extend(
            int(payload["request_id"]) for payload in outcome.request_payloads
        ),
        Qt.ConnectionType.DirectConnection,
    )
    update_count = 700
    try:
        assert dispatcher.submit(
            controller,
            _curved_drag_command("begin", 0),
            "begin",
            source="dotnet",
        ) > 0
        assert controller.begin_started.wait(1.0)
        for sequence in range(1, update_count + 1):
            assert dispatcher.submit(
                controller,
                _curved_drag_command("update", sequence),
                "update",
                source="dotnet",
                request_payload={"request_id": sequence},
            ) > 0
        assert dispatcher.submit(
            controller,
            _curved_drag_command("end", update_count + 1),
            "end",
            source="dotnet",
        ) > 0

        updates = [request for request in dispatcher._controls if request.phase == "update"]
        assert 1 < len(updates) <= STROKE_MAX_SEGMENTS
        assert all(request.command.params["stroke_id"] == "segmented-drag" for request in updates)
        assert all(
            len(request.command.params["screen_path"]) <= STROKE_MAX_SAMPLES_PER_PACKET  # type: ignore[arg-type]
            for request in updates
        )
        assert all(
            encoded_stroke_command_bytes(request.command) <= STROKE_MAX_PACKET_BYTES
            for request in updates
        )

        controller.release_begin.set()
        assert dispatcher.wait_idle(5.0)
        assert sorted((*coalesced_ids, *completed_ids)) == list(range(1, update_count + 1))
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_queued_segment_memory_plateaus_after_the_configured_bound() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    update_count = STROKE_MAX_SEGMENTS * STROKE_MAX_SAMPLES_PER_PACKET + 900
    try:
        assert dispatcher.submit(
            controller,
            _selection_command("begin", 0),
            "begin",
            source="dotnet_selection",
        ) > 0
        assert controller.begin_started.wait(1.0)
        for sequence in range(1, update_count + 1):
            assert dispatcher.submit(
                controller,
                _curved_selection_command("update", sequence),
                "update",
                source="dotnet_selection",
            ) > 0

        metrics = dispatcher.metrics()
        assert metrics["control_depth"] == STROKE_MAX_SEGMENTS - 1
        assert metrics["queue_depth"] == 1
        retained = 0
        for request in (*dispatcher._controls, dispatcher._pending_update):
            assert request is not None
            screen = request.command.params["_native_screen_selection_payload"]
            assert isinstance(screen, Mapping)
            region = screen.get("screen_region")
            assert isinstance(region, Mapping)
            retained += len(region["points"])  # type: ignore[arg-type]
        assert retained <= STROKE_MAX_SEGMENTS * STROKE_MAX_SAMPLES_PER_PACKET

        terminal_started = time.perf_counter()
        assert dispatcher.submit(
            controller,
            _selection_command("cancel", update_count + 1),
            "cancel",
            source="dotnet_selection",
        ) > 0
        assert time.perf_counter() - terminal_started < 0.05
        controller.release_begin.set()
        assert dispatcher.wait_idle(5.0)
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_active_update_counts_toward_the_sixteen_packet_stroke_bound() -> None:
    controller = _FirstUpdateBlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    update_count = STROKE_MAX_SEGMENTS * STROKE_MAX_SAMPLES_PER_PACKET + 300
    try:
        assert dispatcher.submit(
            controller,
            _selection_command("begin", 0),
            "begin",
            source="dotnet_selection",
        ) > 0
        assert dispatcher.wait_idle(1.0)
        assert dispatcher.submit(
            controller,
            _curved_selection_command("update", 1),
            "update",
            source="dotnet_selection",
        ) > 0
        assert controller.update_started.wait(1.0)
        for sequence in range(2, update_count + 1):
            assert dispatcher.submit(
                controller,
                _curved_selection_command("update", sequence),
                "update",
                source="dotnet_selection",
            ) > 0
        assert dispatcher.submit(
            controller,
            _selection_command("end", update_count + 1),
            "end",
            source="dotnet_selection",
        ) > 0

        assert dispatcher.metrics()["max_segments_per_stroke"] == STROKE_MAX_SEGMENTS
        controller.release_update.set()
        assert dispatcher.wait_idle(5.0)
        update_calls = [marker for marker in controller.calls if marker.startswith("update-")]
        assert len(update_calls) == STROKE_MAX_SEGMENTS
    finally:
        controller.release_update.set()
        assert dispatcher.stop()


def test_missing_stroke_id_cannot_create_an_unbounded_segment_queue() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)
        for sequence in range(1, 1001):
            command = _curved_drag_command("update", sequence)
            command = MeshEditCommand(
                command.action,
                params={
                    key: value
                    for key, value in command.params.items()
                    if key != "stroke_id"
                },
            )
            assert dispatcher.submit(controller, command, "update", source="dotnet") > 0

        assert dispatcher.metrics()["control_depth"] == 0
        assert dispatcher.metrics()["queue_depth"] == 1
        assert dispatcher.metrics()["max_packet_samples"] <= STROKE_MAX_SAMPLES_PER_PACKET
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_distinct_deformation_stroke_updates_are_not_coalesced() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)
        first = _drag_command(0, 1)
        second_params = dict(_drag_command(1, 2).params)
        second_params["marker"] = "other-stroke"
        second_params["stroke_id"] = "other-stroke"
        second = MeshEditCommand("transform", params=second_params)

        assert dispatcher.submit(controller, first, "update", source="dotnet") > 0
        assert dispatcher.submit(controller, second, "update", source="dotnet") > 0
        assert dispatcher.metrics()["control_depth"] == 1
        assert dispatcher.metrics()["queue_depth"] == 1
        assert dispatcher.metrics()["coalesced_updates"] == 0

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "update-1", "other-stroke"]
        assert dispatcher._stroke_segment_counts == {}
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_cancel_phase_terminalizes_the_discarded_pending_update() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    failures = []
    dispatcher.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)
        assert dispatcher.submit(
            controller,
            _command("update"),
            "update",
            source="dotnet",
            request_payload={"request_id": 61},
        ) > 0
        assert dispatcher.submit(
            controller,
            _command("cancel"),
            "cancel",
            source="dotnet",
            request_payload={"request_id": 62},
        ) > 0

        assert len(failures) == 1
        assert failures[0].cancelled is True
        assert failures[0].request_payloads == ({"request_id": 61},)
        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "cancel"]
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_live_stroke_dispatcher_cancellation_reaches_active_request() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    failures = []
    dispatcher.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    try:
        assert dispatcher.submit(
            controller,
            _command("begin"),
            "begin",
            source="dotnet",
            request_payload={"request_id": 70},
        ) > 0
        assert controller.begin_started.wait(1.0)
        dispatcher.cancel_pending()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin"]
        assert len(failures) == 1
        assert failures[0].cancelled is True
        assert failures[0].request_payloads == ({"request_id": 70},)
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_live_stroke_dispatcher_retires_controller_without_blocking_caller() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)
        started = time.perf_counter()
        dispatcher.cancel_pending()
        dispatcher.retire_controller(controller)  # type: ignore[arg-type]
        assert time.perf_counter() - started < 0.05
        assert controller.closed.wait(1.0)
        assert dispatcher.wait_idle(1.0)
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()
