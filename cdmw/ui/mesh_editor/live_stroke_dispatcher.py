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
from cdmw.ui.mesh_editor.stroke_packets import (
    STROKE_MAX_SEGMENTS,
    StrokePacketBuild,
    bound_live_stroke_command,
    cancel_live_stroke_command,
    carry_live_stroke_segment_boundary,
    command_for_live_stroke_apply,
    continue_selection_terminal,
    merge_live_stroke_commands,
)


@dataclass(frozen=True, slots=True)
class MeshLiveStrokeRequest:
    sequence: int
    phase: str
    controller: MeshEditorController
    command: MeshEditCommand
    source: str = ""
    request_payloads: tuple[dict[str, object], ...] = ()
    submitted_at: float = field(default_factory=time.monotonic)
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


def _stroke_stream_key(request: MeshLiveStrokeRequest) -> tuple[int, str, str, str]:
    return (
        id(request.controller),
        request.source,
        request.command.action,
        _request_stream_id(request),
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
        self._segmented_batches = 0
        self._oversize_rejections = 0
        self._max_packet_bytes = 0
        self._max_packet_samples = 0
        self._max_raw_samples = 0
        self._max_segments_per_stroke = 0
        self._stroke_segment_counts: dict[tuple[int, str, str, str], int] = {}
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
        submitted_at = time.monotonic()
        request_source = str(source or "")
        packet = bound_live_stroke_command(
            command,
            source=request_source,
            timestamp_seconds=submitted_at,
        )
        cancelled_pending: MeshLiveStrokeRequest | None = None
        with self._condition:
            if self._stopping:
                return 0
            if packet.too_large:
                self._oversize_rejections += 1
                if normalized_phase not in {"end", "cancel"}:
                    return 0
                normalized_phase = "cancel"
                packet = bound_live_stroke_command(
                    cancel_live_stroke_command(command, source=request_source),
                    source=request_source,
                    timestamp_seconds=submitted_at,
                )
                if packet.too_large:
                    return 0
            self._record_packet_metrics_locked(packet)
            self._sequence += 1
            request_payloads = (dict(request_payload),) if request_payload is not None else ()
            request = MeshLiveStrokeRequest(
                self._sequence,
                normalized_phase,
                controller,
                packet.command,
                request_source,
                request_payloads,
                submitted_at=submitted_at,
            )
            if normalized_phase == "update":
                request = self._submit_update_locked(request)
            else:
                request, cancelled_pending = self._submit_control_locked(request)
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

    def _submit_update_locked(self, request: MeshLiveStrokeRequest) -> MeshLiveStrokeRequest:
        pending = self._pending_update
        if pending is not None and not _same_pending_update_stream(pending, request):
            self._controls.append(pending)
            self._note_segment_locked(pending)
            pending = None
            self._pending_update = None
        if pending is None:
            self._pending_update = request
            return request

        merged = merge_live_stroke_commands(
            pending.command,
            request.command,
            source=request.source,
            timestamp_seconds=request.submitted_at,
        )
        self._record_packet_metrics_locked(merged)
        stream_key = _stroke_stream_key(request)
        segment_count = self._stroke_segment_counts.get(stream_key, 0)
        if (
            merged.overflowed
            and stream_key[-1]
            and segment_count < STROKE_MAX_SEGMENTS - 1
        ):
            self._controls.append(pending)
            self._note_segment_locked(pending)
            carried = carry_live_stroke_segment_boundary(
                pending.command,
                request.command,
                source=request.source,
                timestamp_seconds=request.submitted_at,
            )
            self._record_packet_metrics_locked(carried)
            request = self._request_with_command(request, carried.command)
            self._pending_update = request
            return request

        pending.stop_event.set()
        self._coalesced += 1
        if pending.request_payloads:
            self.coalesced.emit(
                MeshLiveStrokeCoalesced(
                    request.controller,
                    request.source,
                    merged.command.action,
                    pending.request_payloads,
                    request.sequence,
                )
            )
        request = self._request_with_command(request, merged.command)
        self._pending_update = request
        return request

    def _submit_control_locked(
        self,
        request: MeshLiveStrokeRequest,
    ) -> tuple[MeshLiveStrokeRequest, MeshLiveStrokeRequest | None]:
        stream_key = _stroke_stream_key(request)
        if request.phase == "begin":
            self._stroke_segment_counts[stream_key] = 0
        cancelled_pending: MeshLiveStrokeRequest | None = None
        pending = self._pending_update
        if pending is not None:
            same_stream = _same_pending_update_stream(pending, request)
            if request.phase == "cancel" and same_stream:
                pending.stop_event.set()
                cancelled_pending = pending
            else:
                self._controls.append(pending)
                self._note_segment_locked(pending)
            self._pending_update = None
        if request.source == "dotnet_selection" and request.phase in {"end", "cancel"}:
            if self._stroke_segment_counts.get(stream_key, 0) > 0:
                request = self._request_with_command(
                    request,
                    continue_selection_terminal(request.command),
                )
        self._controls.append(request)
        if request.phase in {"end", "cancel"}:
            self._stroke_segment_counts.pop(stream_key, None)
        return request, cancelled_pending

    @staticmethod
    def _request_with_command(
        request: MeshLiveStrokeRequest,
        command: MeshEditCommand,
    ) -> MeshLiveStrokeRequest:
        return MeshLiveStrokeRequest(
            request.sequence,
            request.phase,
            request.controller,
            command,
            request.source,
            request.request_payloads,
            submitted_at=request.submitted_at,
            stop_event=request.stop_event,
        )

    def _note_segment_locked(
        self,
        request: MeshLiveStrokeRequest,
        *,
        segmented_batch: bool = True,
    ) -> None:
        stream_key = _stroke_stream_key(request)
        if not stream_key[-1]:
            return
        segment_count = self._stroke_segment_counts.get(stream_key, 0) + 1
        self._stroke_segment_counts[stream_key] = segment_count
        if segmented_batch:
            self._segmented_batches += 1
        self._max_segments_per_stroke = max(self._max_segments_per_stroke, segment_count)

    def _record_packet_metrics_locked(self, packet: StrokePacketBuild) -> None:
        self._max_packet_bytes = max(self._max_packet_bytes, packet.encoded_bytes)
        self._max_packet_samples = max(self._max_packet_samples, packet.retained_samples)
        self._max_raw_samples = max(self._max_raw_samples, packet.raw_samples)

    def _retire_stream_if_idle_locked(self, request: MeshLiveStrokeRequest) -> None:
        stream_key = _stroke_stream_key(request)
        if any(_stroke_stream_key(queued) == stream_key for queued in self._controls):
            return
        if self._pending_update is not None and _stroke_stream_key(self._pending_update) == stream_key:
            return
        self._stroke_segment_counts.pop(stream_key, None)

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
            self._stroke_segment_counts.clear()
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
                "segmented_batches": self._segmented_batches,
                "oversize_rejections": self._oversize_rejections,
                "max_packet_bytes": self._max_packet_bytes,
                "max_packet_samples": self._max_packet_samples,
                "max_raw_samples": self._max_raw_samples,
                "max_segments_per_stroke": self._max_segments_per_stroke,
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
                self._note_segment_locked(request, segmented_batch=False)
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
                apply_command = command_for_live_stroke_apply(request.command)
                params = dict(apply_command.params)
                params["stop_event"] = request.stop_event
                result = request.controller.apply(
                    apply_command.action,
                    selection=apply_command.selection,
                    mode=apply_command.mode,
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
                    self._retire_stream_if_idle_locked(request)
                    self._condition.notify_all()


__all__ = [
    "MeshLiveStrokeDispatcher",
    "MeshLiveStrokeCoalesced",
    "MeshLiveStrokeFailure",
    "MeshLiveStrokeOutcome",
    "MeshLiveStrokeRequest",
]
