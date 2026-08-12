from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from PySide6.QtCore import Qt

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.live_stroke_dispatcher import MeshLiveStrokeDispatcher


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
        assert controller.screen_paths == [tuple((float(x), 20.0) for x in range(6))]
        assert dispatcher.metrics()["coalesced_updates"] == 4
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_two_minute_equivalent_selection_stream_keeps_one_pending_update_and_all_coverage() -> None:
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

        assert dispatcher.submit(
            controller,
            _selection_command("end", update_count + 1),
            "end",
            source="dotnet_selection",
        ) > 0
        metrics = dispatcher.metrics()
        assert metrics["queue_depth"] == 0
        assert metrics["control_depth"] == 2
        assert metrics["coalesced_updates"] == update_count - 1
        queued_update = next(item for item in dispatcher._controls if item.phase == "update")
        screen = queued_update.command.params["_native_screen_selection_payload"]
        assert isinstance(screen, Mapping)
        assert len(screen["screen_brushes"]) == update_count  # type: ignore[arg-type]

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
