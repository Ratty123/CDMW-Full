"""Single-flight background dispatcher for native live Mesh Editor strokes."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate


@dataclass(slots=True)
class MeshLiveStrokeRequest:
    sequence: int
    phase: str
    controller: MeshEditorController
    command: MeshEditCommand
    source: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeOutcome:
    sequence: int
    phase: str
    controller: MeshEditorController
    result: MeshEditResult
    native_update: MeshEditorNativeUpdate
    source: str = ""


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeFailure:
    sequence: int
    phase: str
    controller: MeshEditorController
    message: str
    cancelled: bool = False
    source: str = ""


@dataclass(frozen=True, slots=True)
class _RetireControllerRequest:
    controller: MeshEditorController


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
    return MeshEditCommand(
        newest.command.action,
        selection=newest.command.selection,
        params={**newest.command.params, "screen_drag": merged_drag},
        mode=newest.command.mode,
        label=newest.command.label,
    )


class MeshLiveStrokeDispatcher(QObject):
    """Serialize controls and coalesce pending update packets to depth one."""

    completed = Signal(object)
    failed = Signal(object)

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
    ) -> int:
        normalized_phase = str(phase or "").strip().lower()
        if normalized_phase not in {"begin", "update", "end", "cancel"}:
            return 0
        with self._condition:
            if self._stopping:
                return 0
            self._sequence += 1
            request = MeshLiveStrokeRequest(
                sequence=self._sequence,
                phase=normalized_phase,
                controller=controller,
                command=command,
                source=str(source or ""),
            )
            if normalized_phase == "update":
                if self._pending_update is not None:
                    request.command = _merge_pending_screen_drag(self._pending_update, request)
                    self._pending_update.stop_event.set()
                    self._coalesced += 1
                self._pending_update = request
            else:
                if normalized_phase in {"end", "cancel"} and self._pending_update is not None:
                    if normalized_phase == "end":
                        self._controls.append(self._pending_update)
                    else:
                        self._pending_update.stop_event.set()
                    self._pending_update = None
                self._controls.append(request)
            self._condition.notify_all()
            return request.sequence

    def cancel_pending(self) -> None:
        with self._condition:
            if self._active is not None:
                self._active.stop_event.set()
            for request in self._controls:
                request.stop_event.set()
            self._controls.clear()
            if self._pending_update is not None:
                self._pending_update.stop_event.set()
                self._pending_update = None
            self._condition.notify_all()

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
                native_update = request.controller.native_update_for_result(
                    result,
                    stop_event=request.stop_event,
                )
                if not request.stop_event.is_set():
                    self.completed.emit(
                        MeshLiveStrokeOutcome(
                            request.sequence,
                            request.phase,
                            request.controller,
                            result,
                            native_update,
                            request.source,
                        )
                    )
            except Exception as exc:
                self.failed.emit(
                    MeshLiveStrokeFailure(
                        request.sequence,
                        request.phase,
                        request.controller,
                        f"{type(exc).__name__}: {exc}",
                        cancelled=request.stop_event.is_set(),
                        source=request.source,
                    )
                )
            finally:
                with self._condition:
                    self._active = None
                    self._condition.notify_all()


__all__ = [
    "MeshLiveStrokeDispatcher",
    "MeshLiveStrokeFailure",
    "MeshLiveStrokeOutcome",
    "MeshLiveStrokeRequest",
]
