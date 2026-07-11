"""Ack-paced latest-wins edit updates for the embedded .NET viewport."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


MESH_EDIT_REVISION_CAPABILITY = "mesh_edit_revision_ack_v1"
_ACK_EVENTS = frozenset({"preview_vertex_update_ack", "preview_triangle_update_ack"})


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


class DotNetRevisionUpdateQueue:
    """Keep one active revision and one replaceable pending revision."""

    def __init__(self, send: Callable[[Mapping[str, object]], bool]) -> None:
        self._send = send
        self._capable = False
        self._active_revision = 0
        self._active_acks: set[str] = set()
        self._active_paths: tuple[Path, ...] = ()
        self._pending: tuple[int, tuple[dict[str, object], ...], tuple[Path, ...]] | None = None
        self._legacy_paths: deque[tuple[Path, ...]] = deque()
        self._last_acked_revision = 0
        self._coalesced = 0
        self._ignored_acks = 0
        self._rejected = 0
        self._discarded_stale = 0
        self._timeouts = 0

    def reset(self) -> None:
        _remove_paths(self._active_paths)
        if self._pending is not None:
            _remove_paths(self._pending[2])
        for paths in self._legacy_paths:
            _remove_paths(paths)
        self._capable = False
        self._active_revision = 0
        self._active_acks.clear()
        self._active_paths = ()
        self._pending = None
        self._legacy_paths.clear()
        self._last_acked_revision = 0
        self._coalesced = 0
        self._ignored_acks = 0
        self._rejected = 0
        self._discarded_stale = 0
        self._timeouts = 0

    def observe_capabilities(self, payload: Mapping[str, object]) -> bool:
        raw = payload.get("capabilities", ())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            self._capable = self._capable or MESH_EDIT_REVISION_CAPABILITY in {str(item) for item in raw}
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
        if not self._capable or revision <= 0:
            sent = all(self._send(packet) for packet in prepared)
            if paths and sent:
                self._retain_deferred_paths(paths)
            elif paths:
                _remove_paths(paths)
            return sent
        if self._active_revision > 0:
            newest_queued = self._pending[0] if self._pending is not None else self._active_revision
            if int(revision) <= newest_queued:
                _remove_paths(paths)
                self._discarded_stale += 1
                return True
            if self._pending is not None:
                _remove_paths(self._pending[2])
                self._coalesced += 1
            self._pending = (int(revision), prepared, paths)
            return True
        return self._send_batch(int(revision), prepared, paths)

    def _send_batch(
        self,
        revision: int,
        packets: tuple[dict[str, object], ...],
        paths: tuple[Path, ...],
    ) -> bool:
        self._active_revision = revision
        self._active_acks = {
            f"{str(packet.get('event', '') or '')}_ack"
            for packet in packets
            if f"{str(packet.get('event', '') or '')}_ack" in _ACK_EVENTS
        }
        self._active_paths = paths
        for packet in packets:
            if not self._send(packet):
                self._finish_active()
                self._discard_pending()
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
        except (TypeError, ValueError):
            revision = 0
        if revision != self._active_revision or event not in self._active_acks:
            self._ignored_acks += 1
            return True
        if str(payload.get("status", "applied") or "applied").strip().lower() == "rejected":
            self._rejected += 1
        self._active_acks.discard(event)
        if not self._active_acks:
            self._last_acked_revision = max(self._last_acked_revision, revision)
            self._finish_active()
        return True

    def _finish_active(self) -> None:
        _remove_paths(self._active_paths)
        self._active_revision = 0
        self._active_acks.clear()
        self._active_paths = ()
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._send_batch(*pending)

    def _discard_pending(self) -> None:
        if self._pending is not None:
            _remove_paths(self._pending[2])
        self._pending = None

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
        self._retain_deferred_paths(self._active_paths)
        self._active_paths = ()
        self._finish_active()
        return True

    def metrics(self) -> dict[str, object]:
        return {
            "revision_ack_capable": self._capable,
            "active_revision": self._active_revision,
            "pending_depth": int(self._pending is not None),
            "last_acked_revision": self._last_acked_revision,
            "coalesced_updates": self._coalesced,
            "ignored_acks": self._ignored_acks,
            "rejected_updates": self._rejected,
            "discarded_stale_updates": self._discarded_stale,
            "ack_timeouts": self._timeouts,
            "legacy_cleanup_depth": len(self._legacy_paths),
        }


__all__ = ["DotNetRevisionUpdateQueue", "MESH_EDIT_REVISION_CAPABILITY"]
