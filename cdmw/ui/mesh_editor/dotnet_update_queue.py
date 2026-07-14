"""Correlated, ack-paced resident updates for the embedded .NET viewport."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


MESH_EDIT_REVISION_CAPABILITY = "mesh_edit_revision_ack_v1"
MESH_MUTATION_ENVELOPE_CAPABILITY = "resident_mutation_envelope_v2"
_ACK_EVENTS = frozenset(
    {
        "preview_vertex_update_ack",
        "preview_triangle_update_ack",
        "resident_state_resync_ack",
    }
)
_TOPOLOGY_EVENT = "preview_triangle_update"
_SELECTION_EVENT = "selection_update"
_VERTEX_EVENT = "preview_vertex_update"


def _owned_payload_paths(value: object) -> tuple[Path, ...]:
    paths: set[Path] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            if bool(item.get("delete_after")):
                raw_path = str(item.get("path", "") or "").strip()
                if raw_path:
                    paths.add(Path(raw_path))
            for child in item.values():
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(paths)


def _remove_paths(paths: Sequence[Path]) -> None:
    from cdmw.services.mesh_workflow_service import release_native_preview_delta_path

    for path in paths:
        if release_native_preview_delta_path(path):
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class _PendingBatch:
    revision: int
    packets: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


def _event(packet: Mapping[str, object]) -> str:
    return str(packet.get("event", "") or "")


def _packet_has_topology(packets: Sequence[Mapping[str, object]]) -> bool:
    return any(_event(packet) == _TOPOLOGY_EVENT for packet in packets)


def _inline_indices(group: Mapping[str, object]) -> tuple[int, ...] | None:
    raw = group.get("source_vertex_indices")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        try:
            return tuple(int(value) for value in raw)
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        start = int(group.get("source_vertex_start", -1))
        count = int(group.get("source_vertex_count", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    if start >= 0 and count > 0:
        return tuple(range(start, start + count))
    return None


def _inline_values(
    group: Mapping[str, object],
    key: str,
    count: int,
    components: int,
) -> tuple[float, ...] | None:
    raw = group.get(key)
    if raw in (None, (), []):
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return values if len(values) == count * components else None


def _merge_inline_vertex_packets(
    older: Mapping[str, object],
    newer: Mapping[str, object],
) -> dict[str, object] | None:
    raw_groups = tuple(older.get("vertex_groups", ()) or ()) + tuple(newer.get("vertex_groups", ()) or ())
    grouped: dict[tuple[int, bool, bool], dict[int, tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]]] = {}
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            return None
        if any(
            key in raw_group
            for key in (
                "source_vertex_indices_binary",
                "positions_binary",
                "normals_binary",
                "uvs_binary",
            )
        ):
            return None
        try:
            submesh = int(raw_group.get("source_submesh_index", -1))
        except (TypeError, ValueError, OverflowError):
            return None
        indices = _inline_indices(raw_group)
        if submesh < 0 or not indices:
            return None
        positions = _inline_values(raw_group, "positions", len(indices), 3)
        normals = _inline_values(raw_group, "normals", len(indices), 3)
        uvs = _inline_values(raw_group, "uvs", len(indices), 2)
        if positions is None or normals is None or uvs is None or not positions:
            return None
        channel_key = (submesh, bool(normals), bool(uvs))
        target = grouped.setdefault(channel_key, {})
        for offset, source_index in enumerate(indices):
            target[source_index] = (
                positions[offset * 3 : offset * 3 + 3],
                normals[offset * 3 : offset * 3 + 3] if normals else (),
                uvs[offset * 2 : offset * 2 + 2] if uvs else (),
            )
    merged_groups: list[dict[str, object]] = []
    for (submesh, has_normals, has_uvs), values_by_index in sorted(grouped.items()):
        indices = tuple(sorted(values_by_index))
        group: dict[str, object] = {
            "source_submesh_index": submesh,
            "source_vertex_indices": list(indices),
            "positions": [
                component
                for source_index in indices
                for component in values_by_index[source_index][0]
            ],
        }
        if has_normals:
            group["normals"] = [
                component
                for source_index in indices
                for component in values_by_index[source_index][1]
            ]
        if has_uvs:
            group["uvs"] = [
                component
                for source_index in indices
                for component in values_by_index[source_index][2]
            ]
        merged_groups.append(group)
    return {
        **dict(older),
        **dict(newer),
        "event": _VERTEX_EVENT,
        "vertex_groups": merged_groups,
    }


def _coalesce_packets(
    older: Sequence[Mapping[str, object]],
    newer: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...] | None:
    if _packet_has_topology(older) or _packet_has_topology(newer):
        return None
    result = [dict(packet) for packet in older]
    for packet in newer:
        event = _event(packet)
        if event == _SELECTION_EVENT:
            result = [candidate for candidate in result if _event(candidate) != _SELECTION_EVENT]
            result.append(dict(packet))
            continue
        if event == _VERTEX_EVENT:
            existing_index = next(
                (index for index, candidate in enumerate(result) if _event(candidate) == _VERTEX_EVENT),
                -1,
            )
            if existing_index >= 0:
                merged = _merge_inline_vertex_packets(result[existing_index], packet)
                if merged is None:
                    return None
                result[existing_index] = merged
                continue
        result.append(dict(packet))
    return tuple(result)


class DotNetRevisionUpdateQueue:
    """Keep one active batch and a bounded, lossless pending accumulator."""

    def __init__(
        self,
        send: Callable[[Mapping[str, object]], bool],
        *,
        max_pending_batches: int = 64,
        resync_packets: Callable[[], Sequence[Mapping[str, object]]] | None = None,
    ) -> None:
        self._send = send
        self._max_pending_batches = max(1, int(max_pending_batches))
        self._resync_packets = resync_packets
        self._capable = False
        self._correlated = False
        self._session_id = ""
        self._process_generation = 0
        self._request_sequence = 0
        self._active_revision = 0
        self._active_request_id = 0
        self._active_acks: set[str] = set()
        self._active_packets: tuple[dict[str, object], ...] = ()
        self._active_paths: tuple[Path, ...] = ()
        self._pending: deque[_PendingBatch] = deque()
        self._legacy_paths: deque[tuple[Path, ...]] = deque()
        self._uncertain_paths: tuple[Path, ...] = ()
        self._last_acked_revision = 0
        self._coalesced = 0
        self._ignored_acks = 0
        self._rejected = 0
        self._discarded_stale = 0
        self._timeouts = 0
        self._backpressure = 0
        self._resync_attempts = 0
        self._resync_active = False
        self._recovery_failed = False

    def set_context(self, *, session_id: str, process_generation: int) -> None:
        normalized = str(session_id or "").strip()
        generation = max(0, int(process_generation))
        if (normalized, generation) == (self._session_id, self._process_generation):
            return
        self.reset()
        self._session_id = normalized
        self._process_generation = generation

    def set_resync_factory(
        self,
        factory: Callable[[], Sequence[Mapping[str, object]]] | None,
    ) -> None:
        self._resync_packets = factory

    def reset(self) -> None:
        _remove_paths(self._active_paths)
        _remove_paths(self._uncertain_paths)
        for pending in self._pending:
            _remove_paths(pending.paths)
        for paths in self._legacy_paths:
            _remove_paths(paths)
        self._capable = False
        self._correlated = False
        self._active_revision = 0
        self._active_request_id = 0
        self._active_acks.clear()
        self._active_packets = ()
        self._active_paths = ()
        self._pending.clear()
        self._legacy_paths.clear()
        self._uncertain_paths = ()
        self._last_acked_revision = 0
        self._coalesced = 0
        self._ignored_acks = 0
        self._rejected = 0
        self._discarded_stale = 0
        self._timeouts = 0
        self._backpressure = 0
        self._resync_attempts = 0
        self._resync_active = False
        self._recovery_failed = False

    def observe_capabilities(self, payload: Mapping[str, object]) -> bool:
        raw = payload.get("capabilities", ())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            capabilities = {str(item) for item in raw}
            self._capable = self._capable or MESH_EDIT_REVISION_CAPABILITY in capabilities
            self._correlated = self._correlated or MESH_MUTATION_ENVELOPE_CAPABILITY in capabilities
        return self._capable

    @staticmethod
    def _packets(revision: int, packets: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                **dict(packet),
                "edit_revision": max(0, int(revision)),
                "revision": max(0, int(revision)),
            }
            for packet in packets
        )

    def enqueue(self, revision: int, packets: Sequence[Mapping[str, object]]) -> bool:
        prepared = self._packets(revision, packets)
        if not prepared:
            return True
        paths = _owned_payload_paths(prepared)
        expected_acks = self._expected_acks(prepared)
        if not self._capable or revision <= 0:
            sent = all(self._send(packet) for packet in prepared)
            if paths and sent:
                self._retain_deferred_paths(paths)
            elif paths:
                _remove_paths(paths)
            return sent
        if self._recovery_failed:
            _remove_paths(paths)
            return False
        if self._active_revision > 0 or self._resync_active:
            if int(revision) == self._active_revision and not expected_acks and not self._resync_active:
                return self._send_uncorrelated_supplement(prepared, paths)
            return self._accumulate_pending(int(revision), prepared, paths)
        return self._send_batch(int(revision), prepared, paths)

    def _send_uncorrelated_supplement(
        self,
        packets: tuple[dict[str, object], ...],
        paths: tuple[Path, ...],
    ) -> bool:
        prepared = self._envelope_packets(
            packets,
            request_id=self._active_request_id,
            revision=self._active_revision,
        )
        sent = all(self._send(packet) for packet in prepared)
        if paths and sent:
            self._active_paths += paths
        elif paths:
            _remove_paths(paths)
        return sent

    def _accumulate_pending(
        self,
        revision: int,
        packets: tuple[dict[str, object], ...],
        paths: tuple[Path, ...],
    ) -> bool:
        if revision < self._last_acked_revision:
            _remove_paths(paths)
            self._discarded_stale += 1
            return True
        if self._pending:
            tail = self._pending[-1]
            merged = _coalesce_packets(tail.packets, packets)
            if merged is not None:
                self._pending[-1] = _PendingBatch(
                    max(tail.revision, revision),
                    self._packets(max(tail.revision, revision), merged),
                    tail.paths + paths,
                )
                self._coalesced += 1
                return True
        if len(self._pending) >= self._max_pending_batches:
            _remove_paths(paths)
            self._backpressure += 1
            return False
        self._pending.append(_PendingBatch(revision, packets, paths))
        return True

    @staticmethod
    def _expected_acks(packets: Sequence[Mapping[str, object]]) -> set[str]:
        return {
            f"{_event(packet)}_ack"
            for packet in packets
            if f"{_event(packet)}_ack" in _ACK_EVENTS
        }

    def _envelope_packets(
        self,
        packets: Sequence[Mapping[str, object]],
        *,
        request_id: int,
        revision: int,
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                **dict(packet),
                "session_id": self._session_id,
                "request_id": request_id,
                "base_revision": self._last_acked_revision,
                "edit_revision": revision,
                "revision": revision,
                "process_generation": self._process_generation,
                "protocol_version": 2,
            }
            for packet in packets
        )

    def _send_batch(
        self,
        revision: int,
        packets: tuple[dict[str, object], ...],
        paths: tuple[Path, ...],
        *,
        resync: bool = False,
    ) -> bool:
        supplied_request_ids = {
            int(packet.get("request_id", 0) or 0)
            for packet in packets
            if not isinstance(packet.get("request_id"), bool)
        }
        supplied_request_ids.discard(0)
        if len(supplied_request_ids) == 1:
            request_id = supplied_request_ids.pop()
            self._request_sequence = max(self._request_sequence, request_id)
        else:
            self._request_sequence += 1
            request_id = self._request_sequence
        self._active_revision = revision
        self._active_request_id = request_id
        self._active_acks = self._expected_acks(packets)
        self._active_packets = packets
        self._active_paths = paths
        self._resync_active = bool(resync)
        prepared = self._envelope_packets(
            packets,
            request_id=self._active_request_id,
            revision=revision,
        )
        for packet in prepared:
            if not self._send(packet):
                self._clear_active(remove_paths=True)
                self._fail_recovery() if resync else self._begin_resync()
                return False
        if not self._active_acks:
            self._finish_active()
        return True

    def acknowledge(self, event: str, payload: Mapping[str, object]) -> bool:
        if str(event) not in _ACK_EVENTS:
            return False
        self.observe_capabilities(payload)
        try:
            revision = int(payload.get("edit_revision", payload.get("revision", 0)) or 0)
            request_id = int(payload.get("request_id", 0) or 0)
            process_generation = int(payload.get("process_generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            revision = request_id = process_generation = 0
        if self._correlated and (
            str(payload.get("session_id", "") or "").strip() != self._session_id
            or request_id != self._active_request_id
            or process_generation != self._process_generation
        ):
            self._ignored_acks += 1
            return True
        if revision != self._active_revision or event not in self._active_acks:
            self._ignored_acks += 1
            return True
        status = str(payload.get("status", "applied") or "applied").strip().lower()
        if status == "rejected":
            self._rejected += 1
            if self._resync_active:
                self._fail_recovery()
            else:
                self._begin_resync()
            return True
        self._active_acks.discard(event)
        if not self._active_acks:
            if self._resync_active:
                _remove_paths(self._uncertain_paths)
                self._uncertain_paths = ()
            self._last_acked_revision = max(self._last_acked_revision, revision)
            self._finish_active()
        return True

    def _finish_active(self) -> None:
        _remove_paths(self._active_paths)
        self._clear_active(remove_paths=False)
        if self._pending and not self._recovery_failed:
            pending = self._pending.popleft()
            self._send_batch(pending.revision, pending.packets, pending.paths)

    def _clear_active(self, *, remove_paths: bool) -> None:
        if remove_paths:
            _remove_paths(self._active_paths)
        self._active_revision = 0
        self._active_request_id = 0
        self._active_acks.clear()
        self._active_packets = ()
        self._active_paths = ()
        self._resync_active = False

    def _begin_resync(self) -> None:
        if self._resync_active or self._recovery_failed:
            return
        self._uncertain_paths += self._active_paths
        revision = max(self._active_revision, self._last_acked_revision)
        uncertain_packets = self._active_packets
        self._clear_active(remove_paths=False)
        self._resync_attempts += 1
        try:
            packets = tuple(
                dict(packet)
                for packet in (
                    self._resync_packets()
                    if self._resync_packets
                    else (
                        {
                            "event": "resident_state_resync",
                            "packets": [dict(packet) for packet in uncertain_packets],
                            "target_revision": revision,
                        },
                    )
                )
            )
        except Exception:
            packets = ()
        if not packets:
            self._fail_recovery()
            return
        owned_resync_paths = _owned_payload_paths(packets)
        fresh_resync_paths = tuple(path for path in owned_resync_paths if path not in self._uncertain_paths)
        self._send_batch(revision, packets, fresh_resync_paths, resync=True)

    def _fail_recovery(self) -> None:
        _remove_paths(self._active_paths)
        _remove_paths(self._uncertain_paths)
        self._uncertain_paths = ()
        self._clear_active(remove_paths=False)
        self._recovery_failed = True

    def _retain_deferred_paths(self, paths: tuple[Path, ...]) -> None:
        if not paths:
            return
        self._legacy_paths.append(paths)
        while len(self._legacy_paths) > 64:
            _remove_paths(self._legacy_paths.popleft())

    def expire_active(self, revision: int) -> bool:
        if self._active_revision <= 0 or int(revision) != self._active_revision:
            return False
        self._timeouts += 1
        if self._resync_active:
            self._fail_recovery()
        else:
            self._begin_resync()
        return True

    def metrics(self) -> dict[str, object]:
        return {
            "revision_ack_capable": self._capable,
            "correlated_ack_capable": self._correlated,
            "active_revision": self._active_revision,
            "active_request_id": self._active_request_id,
            "pending_depth": len(self._pending),
            "last_acked_revision": self._last_acked_revision,
            "coalesced_updates": self._coalesced,
            "ignored_acks": self._ignored_acks,
            "rejected_updates": self._rejected,
            "discarded_stale_updates": self._discarded_stale,
            "ack_timeouts": self._timeouts,
            "pending_backpressure": self._backpressure,
            "resync_attempts": self._resync_attempts,
            "resync_active": self._resync_active,
            "recovery_failed": self._recovery_failed,
            "legacy_cleanup_depth": len(self._legacy_paths),
        }


__all__ = [
    "DotNetRevisionUpdateQueue",
    "MESH_EDIT_REVISION_CAPABILITY",
    "MESH_MUTATION_ENVELOPE_CAPABILITY",
]
