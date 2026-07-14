from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.live_stroke_dispatcher import MeshLiveStrokeDispatcher


class _BlockingController:
    def __init__(self) -> None:
        self.begin_started = threading.Event()
        self.release_begin = threading.Event()
        self.calls: list[str] = []
        self.screen_drags: list[tuple[float, float]] = []
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
        assert tuple(payload["request_id"] for payload in pending_update.request_payloads) == (
            1,
            2,
            3,
            4,
            5,
        )

        controller.release_begin.set()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin", "update-5", "end"]
        assert controller.screen_drags == [(0.0, 5.0)]
        assert dispatcher.metrics()["coalesced_updates"] == 4
    finally:
        controller.release_begin.set()
        assert dispatcher.stop()


def test_live_stroke_dispatcher_cancellation_reaches_active_request() -> None:
    controller = _BlockingController()
    dispatcher = MeshLiveStrokeDispatcher()
    try:
        assert dispatcher.submit(controller, _command("begin"), "begin") > 0
        assert controller.begin_started.wait(1.0)
        dispatcher.cancel_pending()
        assert dispatcher.wait_idle(2.0)
        assert controller.calls == ["begin"]
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
