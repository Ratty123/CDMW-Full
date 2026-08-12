"""Single-flight background dispatcher for native live Mesh Editor strokes."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeRequest:
    sequence: int
    phase: str
    controller: MeshEditorController
    command: MeshEditCommand
    source: str = ""
    request_payloads: tuple[dict[str, object], ...] = ()
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeOutcome:
    sequence: int
    phase: str
    controller: MeshEditorController
    result: MeshEditResult
    native_update: MeshEditorNativeUpdate
    source: str = ""
    request_payloads: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeFailure:
    sequence: int
    phase: str
    controller: MeshEditorController
    message: str
    cancelled: bool = False
    source: str = ""
    request_payloads: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeCoalesced:
    controller: MeshEditorController
    source: str
    command_name: str
    request_payloads: tuple[dict[str, object], ...]
    survivor_sequence: int


@dataclass(frozen=True, slots=True)
class _RetireControllerRequest:
    controller: MeshEditorController


def _request_stream_id(request: MeshLiveStrokeRequest) -> str:
    params = request.command.params
    if request.source == "dotnet_selection":
        return str(params.get("selection_stroke_id", "") or "")
    if request.source == "dotnet_morph":
        return str(params.get("change_id", "") or "")
    return str(params.get("stroke_id", "") or "")


def _same_pending_update_stream(
    previous: MeshLiveStrokeRequest,
    newest: MeshLiveStrokeRequest,
) -> bool:
    return (
        previous.controller is newest.controller
        and previous.source == newest.source
        and previous.command.action == newest.command.action
        and _request_stream_id(previous) == _request_stream_id(newest)
    )


def _merge_pending_screen_drag(
    previous: MeshLiveStrokeRequest,
    newest: MeshLiveStrokeRequest,
) -> MeshEditCommand:
    if (
        previous.controller is not newest.controller
        or previous.source != newest.source
        or previous.command.action != newest.command.action
    ):
        return newest.command
    previous_stroke_id = str(previous.command.params.get("stroke_id", "") or "")
    newest_stroke_id = str(newest.command.params.get("stroke_id", "") or "")
    previous_drag = previous.command.params.get("screen_drag")
    newest_drag = newest.command.params.get("screen_drag")
    if (
        not previous_stroke_id
        or previous_stroke_id != newest_stroke_id
        or not isinstance(previous_drag, Mapping)
        or not isinstance(newest_drag, Mapping)
        or "start_x" not in previous_drag
        or "start_y" not in previous_drag
        or "end_x" not in newest_drag
        or "end_y" not in newest_drag
    ):
        return newest.command
    merged_drag = {
        **newest_drag,
        "start_x": previous_drag["start_x"],
        "start_y": previous_drag["start_y"],
    }
    def _path_points(command: MeshEditCommand, drag: Mapping[str, object]) -> list[dict[str, object]]:
        raw_path = command.params.get("screen_path")
        if isinstance(raw_path, (tuple, list)):
            points = [
                {"x": point["x"], "y": point["y"]}
                for point in raw_path
                if isinstance(point, Mapping) and "x" in point and "y" in point
            ]
            if len(points) >= 2:
                return points
        return [
            {"x": drag["start_x"], "y": drag["start_y"]},
            {"x": drag["end_x"], "y": drag["end_y"]},
        ]

    merged_path = _path_points(previous.command, previous_drag)
    for point in _path_points(newest.command, newest_drag):
        if merged_path and point == merged_path[-1]:
            continue
        merged_path.append(point)
    return MeshEditCommand(
        newest.command.action,
        selection=newest.command.selection,
        params={
            **newest.command.params,
            "screen_drag": merged_drag,
            "screen_path": tuple(merged_path),
        },
        mode=newest.command.mode,
        label=newest.command.label,
    )


def _screen_selection_items(payload: Mapping[str, object], singular: str, plural: str) -> list[object]:
    items: list[object] = []
    raw_many = payload.get(plural)
    if isinstance(raw_many, (tuple, list)):
        items.extend(item for item in raw_many if isinstance(item, Mapping))
    raw_one = payload.get(singular)
    if isinstance(raw_one, Mapping):
        items.append(raw_one)
    return items


def _merge_pending_screen_selection(
    previous: MeshLiveStrokeRequest,
    newest: MeshLiveStrokeRequest,
) -> MeshEditCommand:
    if (
        previous.controller is not newest.controller
        or previous.source != "dotnet_selection"
        or newest.source != "dotnet_selection"
        or previous.command.action != "select"
        or newest.command.action != "select"
    ):
        return newest.command
    previous_params = dict(previous.command.params)
    newest_params = dict(newest.command.params)
    previous_stroke_id = str(previous_params.get("selection_stroke_id", "") or "")
    newest_stroke_id = str(newest_params.get("selection_stroke_id", "") or "")
    previous_screen = previous_params.get("_native_screen_selection_payload")
    newest_screen = newest_params.get("_native_screen_selection_payload")
    if (
        not previous_stroke_id
        or previous_stroke_id != newest_stroke_id
        or not isinstance(previous_screen, Mapping)
        or not isinstance(newest_screen, Mapping)
    ):
        return newest.command
    merged_screen = dict(newest_screen)
    brushes = _screen_selection_items(previous_screen, "screen_brush", "screen_brushes")
    brushes.extend(_screen_selection_items(newest_screen, "screen_brush", "screen_brushes"))
    regions = _screen_selection_items(previous_screen, "screen_region", "screen_regions")
    regions.extend(_screen_selection_items(newest_screen, "screen_region", "screen_regions"))
    merged_screen.pop("screen_brush", None)
    merged_screen.pop("screen_region", None)
    if brushes:
        merged_screen["screen_brushes"] = brushes
    if regions:
        merged_screen["screen_regions"] = regions
    return MeshEditCommand(
        newest.command.action,
        selection=newest.command.selection,
        params={
            **newest_params,
            "operation": previous_params.get("operation", newest_params.get("operation", "add")),
            "_native_screen_selection_payload": merged_screen,
        },
        mode=newest.command.mode,
        label=newest.command.label,
    )


class MeshLiveStrokeDispatcher(QObject):
    """Serialize controls and coalesce pending update packets to depth one."""

    completed = Signal(object)
    failed = Signal(object)
    coalesced = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._condition = threading.Condition()
        self._controls: deque[MeshLiveStrokeRequest] = deque()
        self._pending_update: MeshLiveStrokeRequest | None = None
        self._active: MeshLiveStrokeRequest | None = None
        self._retired_controllers: deque[MeshEditorController] = deque()
        self._retiring_controller: MeshEditorController | None = None
        self._stopping = False
        self._sequence = 0
        self._coalesced = 0
        self._thread = threading.Thread(
            target=self._run,
            name="cdmw-mesh-live-stroke",
            daemon=True,
        )
        self._thread.start()
        if parent is not None:
            parent.destroyed.connect(lambda *_args: self.request_stop())

    def submit(
        self,
        controller: MeshEditorController,
        command: MeshEditCommand,
        phase: str,
        *,
        source: str = "",
        request_payload: Mapping[str, object] | None = None,
    ) -> int:
        normalized_phase = str(phase or "").strip().lower()
        if normalized_phase not in {"begin", "update", "end", "cancel"}:
            return 0
        cancelled_pending: MeshLiveStrokeRequest | None = None
        with self._condition:
            if self._stopping:
                return 0
            self._sequence += 1
            request_payloads = (dict(request_payload),) if request_payload is not None else ()
            request_source = str(source or "")
            if normalized_phase == "update":
                candidate = MeshLiveStrokeRequest(
                    self._sequence,
                    normalized_phase,
                    controller,
                    command,
                    request_source,
                    request_payloads,
                )
                if (
                    self._pending_update is not None
                    and not _same_pending_update_stream(self._pending_update, candidate)
                ):
                    # A pending update from another gesture is an ordering
                    # boundary, not a sample that the newer gesture may
                    # supersede. Preserve it in FIFO order before installing
                    # the new stream's coalescing slot.
                    self._controls.append(self._pending_update)
                    self._pending_update = None
                if self._pending_update is not None:
                    superseded_payloads = self._pending_update.request_payloads
                    command = _merge_pending_screen_selection(
                        self._pending_update,
                        candidate,
                    )
                    command = _merge_pending_screen_drag(
                        self._pending_update,
                        MeshLiveStrokeRequest(
                            self._sequence,
                            normalized_phase,
                            controller,
                            command,
                            request_source,
                            request_payloads,
                        ),
                    )
                    self._pending_update.stop_event.set()
                    self._coalesced += 1
                    if superseded_payloads:
                        self.coalesced.emit(
                            MeshLiveStrokeCoalesced(
                                controller,
                                request_source,
                                command.action,
                                superseded_payloads,
                                self._sequence,
                            )
                        )
                request = MeshLiveStrokeRequest(
                    self._sequence,
                    normalized_phase,
                    controller,
                    command,
                    request_source,
                    request_payloads,
                )
                self._pending_update = request
            else:
                request = MeshLiveStrokeRequest(
                    self._sequence,
                    normalized_phase,
                    controller,
                    command,
                    request_source,
                    request_payloads,
                )
                if normalized_phase in {"end", "cancel"} and self._pending_update is not None:
                    if normalized_phase == "end":
                        self._controls.append(self._pending_update)
                    else:
                        self._pending_update.stop_event.set()
                        cancelled_pending = self._pending_update
                    self._pending_update = None
                self._controls.append(request)
            self._condition.notify_all()
            sequence = request.sequence
        if cancelled_pending is not None:
            self.failed.emit(
                MeshLiveStrokeFailure(
                    cancelled_pending.sequence,
                    cancelled_pending.phase,
                    cancelled_pending.controller,
                    "Mesh Editor live-stroke update was cancelled by its terminal request.",
                    cancelled=True,
                    source=cancelled_pending.source,
                    request_payloads=cancelled_pending.request_payloads,
                )
            )
        return sequence

    def cancel_pending(self) -> None:
        cancelled: list[MeshLiveStrokeRequest] = []
        with self._condition:
            if self._active is not None:
                self._active.stop_event.set()
            for request in self._controls:
                request.stop_event.set()
                cancelled.append(request)
            self._controls.clear()
            if self._pending_update is not None:
                self._pending_update.stop_event.set()
                cancelled.append(self._pending_update)
                self._pending_update = None
            self._condition.notify_all()
        for request in cancelled:
            self.failed.emit(
                MeshLiveStrokeFailure(
                    request.sequence,
                    request.phase,
                    request.controller,
                    "Mesh Editor live-stroke request was cancelled.",
                    cancelled=True,
                    source=request.source,
                    request_payloads=request.request_payloads,
                )
            )

    def wait_idle(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            while (
                self._active is not None
                or self._controls
                or self._pending_update is not None
                or self._retired_controllers
                or self._retiring_controller is not None
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True

    def retire_controller(self, controller: MeshEditorController) -> None:
        """Close a detached controller after its active request releases it."""

        with self._condition:
            if not any(item is controller for item in self._retired_controllers):
                self._retired_controllers.append(controller)
            self._condition.notify_all()

    def request_stop(self) -> None:
        """Request cooperative shutdown without blocking the caller."""

        self.cancel_pending()
        with self._condition:
            self._stopping = True
            self._condition.notify_all()

    def stop(self, timeout_seconds: float = 2.5) -> bool:
        self.request_stop()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, float(timeout_seconds)))
        return not self._thread.is_alive()

    def metrics(self) -> dict[str, int]:
        with self._condition:
            return {
                "queue_depth": int(self._pending_update is not None),
                "control_depth": len(self._controls),
                "active": int(self._active is not None),
                "retired_controller_depth": len(self._retired_controllers),
                "retiring_controller": int(self._retiring_controller is not None),
                "coalesced_updates": self._coalesced,
                "latest_sequence": self._sequence,
            }

    def _next_request(self) -> MeshLiveStrokeRequest | _RetireControllerRequest | None:
        with self._condition:
            while (
                not self._stopping
                and not self._controls
                and self._pending_update is None
                and not self._retired_controllers
            ):
                self._condition.wait()
            if self._retired_controllers:
                self._retiring_controller = self._retired_controllers.popleft()
                return _RetireControllerRequest(self._retiring_controller)
            if self._controls:
                request = self._controls.popleft()
            elif self._pending_update is not None:
                request = self._pending_update
                self._pending_update = None
            else:
                return None
            self._active = request
            return request

    def _run(self) -> None:
        while True:
            request = self._next_request()
            if request is None:
                return
            if isinstance(request, _RetireControllerRequest):
                try:
                    request.controller.close_active_session()
                except Exception:
                    pass
                finally:
                    with self._condition:
                        self._retiring_controller = None
                        self._condition.notify_all()
                continue
            try:
                params = dict(request.command.params)
                params["stop_event"] = request.stop_event
                result = request.controller.apply(
                    request.command.action,
                    selection=request.command.selection,
                    mode=request.command.mode,
                    **params,
                )
                if request.source == "dotnet_selection" and not result.ok:
                    diagnostic = "; ".join(str(item) for item in result.diagnostics if str(item).strip())
                    raise RuntimeError(diagnostic or f"selection stroke {request.phase} failed")
                native_update = request.controller.native_update_for_result(
                    result,
                    stop_event=request.stop_event,
                )
                if request.stop_event.is_set():
                    self.failed.emit(
                        MeshLiveStrokeFailure(
                            request.sequence,
                            request.phase,
                            request.controller,
                            "Mesh Editor live-stroke request was cancelled.",
                            cancelled=True,
                            source=request.source,
                            request_payloads=request.request_payloads,
                        )
                    )
                else:
                    self.completed.emit(
                        MeshLiveStrokeOutcome(
                            request.sequence,
                            request.phase,
                            request.controller,
                            result,
                            native_update,
                            request.source,
                            request.request_payloads,
                        )
                    )
            except Exception as exc:
                restore_error = ""
                failed_payloads = list(request.request_payloads)
                if (
                    request.source == "dotnet_selection"
                    and request.phase != "cancel"
                    and not request.stop_event.is_set()
                ):
                    stroke_id = str(request.command.params.get("selection_stroke_id", "") or "").strip()
                    with self._condition:
                        if self._pending_update is not None and str(
                            self._pending_update.command.params.get("selection_stroke_id", "") or ""
                        ) == stroke_id:
                            self._pending_update.stop_event.set()
                            failed_payloads.extend(self._pending_update.request_payloads)
                            self._pending_update = None
                        retained_controls: deque[MeshLiveStrokeRequest] = deque()
                        for queued in self._controls:
                            if str(queued.command.params.get("selection_stroke_id", "") or "") == stroke_id:
                                queued.stop_event.set()
                                failed_payloads.extend(queued.request_payloads)
                            else:
                                retained_controls.append(queued)
                        self._controls = retained_controls
                    try:
                        if stroke_id:
                            request.controller.apply(
                                "select",
                                selection=MeshEditSelection(),
                                operation="replace",
                                selection_stroke_id=stroke_id,
                                selection_stroke_phase="cancel",
                                selection_stroke_sequence=int(
                                    request.command.params.get("selection_stroke_sequence", 0) or 0
                                ) + 1,
                                record_history=False,
                            )
                    except Exception as restore_exc:
                        restore_error = f"; selection restore failed: {type(restore_exc).__name__}: {restore_exc}"
                self.failed.emit(
                    MeshLiveStrokeFailure(
                        request.sequence,
                        request.phase,
                        request.controller,
                        f"{type(exc).__name__}: {exc}{restore_error}",
                        cancelled=request.stop_event.is_set(),
                        source=request.source,
                        request_payloads=tuple(failed_payloads),
                    )
                )
            finally:
                with self._condition:
                    self._active = None
                    self._condition.notify_all()


__all__ = [
    "MeshLiveStrokeDispatcher",
    "MeshLiveStrokeCoalesced",
    "MeshLiveStrokeFailure",
    "MeshLiveStrokeOutcome",
    "MeshLiveStrokeRequest",
]
