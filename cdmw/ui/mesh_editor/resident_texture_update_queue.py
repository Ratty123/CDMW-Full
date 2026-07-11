"""Latest-wins resident texture-region transport for the .NET viewport."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal


TEXTURE_REGION_CAPABILITY = "resident_texture_region_updates_v1"
TEXTURE_REGION_ACK_EVENTS = frozenset({"texture_region_applied", "texture_region_failed"})


@dataclass(frozen=True, slots=True)
class ResidentTextureRegionRequest:
    session_id: str
    edit_revision: int
    document_texture_revision: int
    resource_id: str
    channel: str
    affected_submeshes: tuple[int, ...]
    texture_width: int
    texture_height: int
    rect: tuple[int, int, int, int]
    row_pitch: int
    bgra: bytes
    current_rgba: np.ndarray
    composite_lease: object | None
    logical_path: str = ""
    mesh_service: object | None = None
    output_root: Path | None = None


@dataclass(frozen=True, slots=True)
class _PreparedTextureRegion:
    resource_id: str
    generation: int
    texture_revision: int
    rect: tuple[int, int, int, int]
    payload: dict[str, object]
    path: Path
    retry_request: ResidentTextureRegionRequest


@dataclass(slots=True)
class _WorkerTextureState:
    width: int
    height: int
    bgra: bytearray
    texture_revision: int = 0
    service_snapshot_committed: bool = False


@dataclass(slots=True)
class _ResourceQueueState:
    generation: int = 0
    preparing: bool = False
    active: Optional[_PreparedTextureRegion] = None
    pending: list[ResidentTextureRegionRequest] = field(default_factory=list)
    preparing_requests: tuple[ResidentTextureRegionRequest, ...] = ()
    retry_rect: Optional[tuple[int, int, int, int]] = None
    deadline: float = 0.0
    retry_count: int = 0


def _merged_rect(
    first: Optional[tuple[int, int, int, int]],
    second: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    if first is None:
        return second
    x0 = min(first[0], second[0])
    y0 = min(first[1], second[1])
    x1 = max(first[0] + first[2], second[0] + second[2])
    y1 = max(first[1] + first[3], second[1] + second[3])
    return x0, y0, x1 - x0, y1 - y0


def _remove_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class ResidentTextureRegionUpdateQueue(QObject):
    update_applied = Signal(object)
    update_failed = Signal(object)
    _worker_completed = Signal(object)

    def __init__(
        self,
        send: Callable[[Mapping[str, object]], bool],
        *,
        output_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._send = send
        self._output_root = Path(output_root or Path(tempfile.gettempdir()) / "cdmw-resident-texture-regions")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cdmw-texture-region")
        self._states: dict[str, _ResourceQueueState] = {}
        self._worker_states: dict[tuple[int, str, str], _WorkerTextureState] = {}
        self._deferred_paths: list[Path] = []
        self._epoch = 0
        self._closed = False
        self._idle_event = threading.Event()
        self._idle_event.set()
        self._coalesced = 0
        self._ignored_acks = 0
        self._failed = 0
        self._timeouts = 0
        self._worker_completed.connect(self._handle_worker_completed)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setInterval(250)
        self._timeout_timer.timeout.connect(self._expire_timeouts)

    def enqueue(self, request: ResidentTextureRegionRequest) -> bool:
        if self._closed:
            return False
        self._validate_request(request)
        self._idle_event.clear()
        state = self._states.setdefault(request.resource_id, _ResourceQueueState())
        if state.pending:
            self._coalesced += 1
            previous = state.pending[0]
            union = _merged_rect(previous.rect, request.rect)
            x, y, width, height = union
            current = np.asarray(request.current_rgba)
            expected_shape = (request.texture_height, request.texture_width, 4)
            if current.dtype != np.uint8 or current.shape != expected_shape:
                raise ValueError("resident texture current RGBA dimensions changed")
            region = np.ascontiguousarray(
                current[y : y + height, x : x + width][:, :, (2, 1, 0, 3)]
            )
            request = replace(
                request,
                rect=union,
                row_pitch=width * 4,
                bgra=region.tobytes(order="C"),
            )
            state.pending[:] = [request]
            self._release_request_lease(previous)
        else:
            state.pending.append(request)
        state.retry_count = 0
        self._start_pending(request.resource_id, state)
        return True

    @staticmethod
    def _validate_request(request: ResidentTextureRegionRequest) -> None:
        x, y, width, height = request.rect
        if not request.session_id or not request.resource_id:
            raise ValueError("resident texture update requires session and resource ids")
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            raise ValueError("resident texture update rect is invalid")
        if x + width > request.texture_width or y + height > request.texture_height:
            raise ValueError("resident texture update rect exceeds texture bounds")
        if request.row_pitch < width * 4 or len(request.bgra) != request.row_pitch * height:
            raise ValueError("resident texture update BGRA payload size is invalid")

    def _start_pending(self, resource_id: str, state: _ResourceQueueState) -> None:
        if state.active is not None or state.preparing or not state.pending or self._closed:
            return
        requests = tuple(state.pending)
        state.pending.clear()
        state.preparing_requests = requests
        self._idle_event.clear()
        state.preparing = True
        state.generation += 1
        generation = state.generation
        retry_rect = state.retry_rect
        state.retry_rect = None
        epoch = self._epoch
        future = self._executor.submit(
            self._prepare_batch,
            requests,
            generation,
            retry_rect,
            epoch,
        )
        future.add_done_callback(
            lambda completed, target_epoch=epoch, target_resource=resource_id, target_generation=generation, target_requests=requests: self._complete_future(
                completed,
                target_epoch,
                target_resource,
                target_generation,
                target_requests,
            )
        )

    def _complete_future(
        self,
        future: Future[_PreparedTextureRegion],
        epoch: int,
        resource_id: str,
        generation: int,
        requests: tuple[ResidentTextureRegionRequest, ...],
    ) -> None:
        try:
            result: object = future.result()
        except Exception as exc:
            result = exc
        finally:
            for request in requests:
                self._release_request_lease(request)
        self._worker_completed.emit((epoch, resource_id, generation, result))

    def _prepare_batch(
        self,
        requests: tuple[ResidentTextureRegionRequest, ...],
        generation: int,
        retry_rect: Optional[tuple[int, int, int, int]],
        epoch: int,
    ) -> _PreparedTextureRegion:
        return self._prepare_batch_owned(requests, generation, retry_rect, epoch)

    def _prepare_batch_owned(
        self,
        requests: tuple[ResidentTextureRegionRequest, ...],
        generation: int,
        retry_rect: Optional[tuple[int, int, int, int]],
        epoch: int,
    ) -> _PreparedTextureRegion:
        if epoch != self._epoch:
            raise RuntimeError("resident texture update was retired")
        latest = requests[-1]
        key = (epoch, latest.session_id, latest.resource_id)
        worker_state = self._worker_states.get(key)
        snapshot_committed_this_batch = False
        if worker_state is None:
            original = np.asarray(latest.current_rgba)
            expected_shape = (latest.texture_height, latest.texture_width, 4)
            if original.dtype != np.uint8 or original.shape != expected_shape:
                raise ValueError("resident texture current RGBA dimensions changed")
            original_bgra = np.ascontiguousarray(original[:, :, (2, 1, 0, 3)])
            worker_state = _WorkerTextureState(
                width=latest.texture_width,
                height=latest.texture_height,
                bgra=bytearray(original_bgra.tobytes(order="C")),
            )
            self._worker_states[key] = worker_state
            retry_rect = (0, 0, latest.texture_width, latest.texture_height)
            if epoch != self._epoch:
                raise RuntimeError("resident texture update was retired")
            commit_snapshot = getattr(latest.mesh_service, "commit_texture_snapshot", None)
            if callable(commit_snapshot):
                worker_state.texture_revision = int(
                    commit_snapshot(
                        latest.session_id,
                        latest.resource_id,
                        channel=latest.channel,
                        affected_submeshes=latest.affected_submeshes,
                        width=latest.texture_width,
                        height=latest.texture_height,
                        row_pitch=latest.texture_width * 4,
                        bgra=worker_state.bgra,
                        logical_path=latest.logical_path,
                    )
                )
                worker_state.service_snapshot_committed = True
                snapshot_committed_this_batch = True
        elif (worker_state.width, worker_state.height) != (latest.texture_width, latest.texture_height):
            raise ValueError("resident texture dimensions changed for an active resource")

        union = retry_rect
        full_pitch = worker_state.width * 4
        for request in requests:
            union = _merged_rect(union, request.rect)
            x, y, width, height = request.rect
            for row in range(height):
                source_start = row * request.row_pitch
                target_start = (y + row) * full_pitch + x * 4
                worker_state.bgra[target_start : target_start + width * 4] = request.bgra[
                    source_start : source_start + width * 4
                ]
        if union is None:
            raise ValueError("resident texture update batch has no region")
        x, y, width, height = union
        row_pitch = width * 4
        patch = bytearray(row_pitch * height)
        for row in range(height):
            source_start = (y + row) * full_pitch + x * 4
            target_start = row * row_pitch
            patch[target_start : target_start + row_pitch] = worker_state.bgra[
                source_start : source_start + row_pitch
            ]

        commit_region = getattr(latest.mesh_service, "commit_texture_region", None)
        if epoch != self._epoch:
            raise RuntimeError("resident texture update was retired")
        if not snapshot_committed_this_batch:
            if callable(commit_region) and worker_state.service_snapshot_committed:
                worker_state.texture_revision = int(
                    commit_region(
                        latest.session_id,
                        latest.resource_id,
                        channel=latest.channel,
                        affected_submeshes=latest.affected_submeshes,
                        rect=union,
                        row_pitch=row_pitch,
                        bgra=patch,
                        expected_revision=worker_state.texture_revision,
                    )
                )
            else:
                worker_state.texture_revision = max(
                    worker_state.texture_revision + 1,
                    int(latest.document_texture_revision),
                )
        if epoch != self._epoch:
            raise RuntimeError("resident texture update was retired")
        patch_bytes = bytes(patch)
        path, digest = self._write_patch(latest, generation, patch_bytes)
        payload = {
            "schema": "cdmw_resident_texture_region_update_v1",
            "version": 1,
            "event": "texture_region_update",
            "session_id": latest.session_id,
            "edit_revision": max(0, int(latest.edit_revision)),
            "texture_revision": max(0, int(worker_state.texture_revision)),
            "generation": int(generation),
            "resource_id": latest.resource_id,
            "channel": latest.channel,
            "affected_submeshes": list(latest.affected_submeshes),
            "texture_width": latest.texture_width,
            "texture_height": latest.texture_height,
            "rect": {"x": x, "y": y, "width": width, "height": height},
            "pixel_format": "bgra8_unorm",
            "row_pitch": row_pitch,
            "binary": {
                "path": str(path),
                "offset": 0,
                "length": len(patch_bytes),
                "sha256": digest,
                "delete_after": True,
            },
        }
        return _PreparedTextureRegion(
            resource_id=latest.resource_id,
            generation=generation,
            texture_revision=worker_state.texture_revision,
            rect=union,
            payload=payload,
            path=path,
            retry_request=replace(
                latest,
                rect=union,
                row_pitch=row_pitch,
                bgra=patch_bytes,
                composite_lease=None,
            ),
        )

    def _write_patch(
        self,
        request: ResidentTextureRegionRequest,
        generation: int,
        patch: bytes,
    ) -> tuple[Path, str]:
        session_key = hashlib.sha256(request.session_id.encode("utf-8")).hexdigest()[:16]
        resource_key = hashlib.sha256(request.resource_id.encode("utf-8")).hexdigest()[:16]
        directory = Path(request.output_root or self._output_root) / session_key
        directory.mkdir(parents=True, exist_ok=True)
        final_path = directory / f"{resource_key}-{generation}-{uuid.uuid4().hex}.bgra"
        descriptor, temporary = tempfile.mkstemp(prefix=".texture-region-", suffix=".tmp", dir=directory)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(patch)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, final_path)
        except BaseException:
            _remove_path(temporary_path)
            raise
        return final_path, hashlib.sha256(patch).hexdigest()

    def _handle_worker_completed(self, completion: object) -> None:
        epoch, resource_id, generation, result = completion
        prepared = result if isinstance(result, _PreparedTextureRegion) else None
        if epoch != self._epoch or self._closed:
            if prepared is not None:
                _remove_path(prepared.path)
            self._discard_worker_epoch(int(epoch))
            return
        state = self._states.get(str(resource_id))
        if state is None or int(generation) != state.generation:
            if prepared is not None:
                _remove_path(prepared.path)
            return
        state.preparing = False
        state.preparing_requests = ()
        if prepared is None:
            self._failed += 1
            self.update_failed.emit({"resource_id": resource_id, "generation": generation, "message": str(result)})
            self._start_pending(str(resource_id), state)
            self._sync_idle_event()
            return
        if not self._send(prepared.payload):
            _remove_path(prepared.path)
            self._failed += 1
            self.update_failed.emit({**prepared.payload, "message": "protocol write failed"})
            self._schedule_single_retry(prepared.resource_id, state, prepared)
            self._sync_idle_event()
            return
        state.active = prepared
        state.deadline = time.monotonic() + 1.0
        if not self._timeout_timer.isActive():
            self._timeout_timer.start()
        self._sync_idle_event()

    def acknowledge(self, event: str, payload: Mapping[str, object]) -> bool:
        if event not in TEXTURE_REGION_ACK_EVENTS:
            return False
        resource_id = str(payload.get("resource_id", "") or "")
        try:
            generation = int(payload.get("generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            generation = 0
        state = self._states.get(resource_id)
        active = state.active if state is not None else None
        if state is None or active is None or generation != active.generation:
            self._ignored_acks += 1
            return True
        _remove_path(active.path)
        state.active = None
        state.deadline = 0.0
        if event == "texture_region_failed":
            self._failed += 1
            self.update_failed.emit(dict(payload))
            self._schedule_single_retry(resource_id, state, active)
        else:
            state.retry_count = 0
            self.update_applied.emit(dict(payload))
            self._start_pending(resource_id, state)
        self._sync_timeout_timer()
        self._sync_idle_event()
        return True

    def _expire_timeouts(self) -> None:
        now = time.monotonic()
        for resource_id, state in tuple(self._states.items()):
            active = state.active
            if active is None or state.deadline > now:
                continue
            state.active = None
            state.deadline = 0.0
            self._deferred_paths.append(active.path)
            self._timeouts += 1
            self.update_failed.emit({**active.payload, "message": "texture region acknowledgement timed out"})
            self._schedule_single_retry(resource_id, state, active)
        while len(self._deferred_paths) > 64:
            _remove_path(self._deferred_paths.pop(0))
        self._sync_timeout_timer()
        self._sync_idle_event()

    def _schedule_single_retry(
        self,
        resource_id: str,
        state: _ResourceQueueState,
        prepared: _PreparedTextureRegion,
    ) -> None:
        if self._closed:
            return
        if state.retry_count >= 1:
            self._start_pending(resource_id, state)
            return
        state.retry_count += 1
        if state.pending:
            pending = state.pending[-1]
            union = _merged_rect(prepared.rect, pending.rect)
            x, y, width, height = union
            current = np.asarray(pending.current_rgba)
            region = np.ascontiguousarray(
                current[y : y + height, x : x + width][:, :, (2, 1, 0, 3)]
            )
            state.pending[:] = [
                replace(
                    pending,
                    rect=union,
                    row_pitch=width * 4,
                    bgra=region.tobytes(order="C"),
                )
            ]
        else:
            state.pending.append(prepared.retry_request)
        QTimer.singleShot(50, lambda key=resource_id, target=state: self._start_scheduled_retry(key, target))

    def _start_scheduled_retry(self, resource_id: str, state: _ResourceQueueState) -> None:
        if self._states.get(resource_id) is state:
            self._start_pending(resource_id, state)

    def _sync_timeout_timer(self) -> None:
        if any(state.active is not None for state in self._states.values()):
            if not self._timeout_timer.isActive():
                self._timeout_timer.start()
        else:
            self._timeout_timer.stop()

    def idle(self) -> bool:
        return self._idle_event.is_set()

    def wait_idle(self, timeout_seconds: float = 5.0) -> bool:
        return self._idle_event.wait(max(0.0, float(timeout_seconds)))

    def _sync_idle_event(self) -> None:
        if any(state.active is not None or state.preparing or state.pending for state in self._states.values()):
            self._idle_event.clear()
        else:
            self._idle_event.set()

    def metrics(self) -> dict[str, int]:
        return {
            "active_depth": sum(state.active is not None for state in self._states.values()),
            "pending_depth": sum(bool(state.pending) or state.preparing for state in self._states.values()),
            "pending_patch_count": sum(len(state.pending) for state in self._states.values()),
            "resource_count": len(self._states),
            "coalesced_updates": self._coalesced,
            "ignored_acks": self._ignored_acks,
            "failed_updates": self._failed,
            "ack_timeouts": self._timeouts,
            "deferred_cleanup_depth": len(self._deferred_paths),
            "worker_resource_count": len(self._worker_states),
        }

    def _discard_worker_epoch(self, epoch: int) -> None:
        for key in tuple(self._worker_states):
            if key[0] == int(epoch):
                self._worker_states.pop(key, None)

    @staticmethod
    def _release_request_lease(request: ResidentTextureRegionRequest) -> None:
        release = getattr(request.composite_lease, "release", None)
        if callable(release):
            release()

    def reset(self) -> None:
        self._epoch += 1
        self._timeout_timer.stop()
        for state in self._states.values():
            if state.active is not None:
                _remove_path(state.active.path)
            for request in state.pending:
                self._release_request_lease(request)
        for path in self._deferred_paths:
            _remove_path(path)
        self._states.clear()
        self._deferred_paths.clear()
        self._worker_states.clear()
        self._idle_event.set()

    def shutdown(self) -> None:
        if self._closed:
            return
        self.reset()
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "ResidentTextureRegionRequest",
    "ResidentTextureRegionUpdateQueue",
    "TEXTURE_REGION_ACK_EVENTS",
    "TEXTURE_REGION_CAPABILITY",
]
