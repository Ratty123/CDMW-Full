from __future__ import annotations

from pathlib import Path

from cdmw.ui.mesh_editor.dotnet_update_queue import (
    MESH_EDIT_REVISION_CAPABILITY,
    DotNetRevisionUpdateQueue,
)


def _packet(event: str, owned_path: Path | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"event": event}
    if owned_path is not None:
        payload["vertex_groups"] = (
            {"positions_binary": {"path": str(owned_path), "delete_after": True}},
        )
    return payload


def test_dotnet_revision_queue_is_ack_paced_latest_wins_and_cleans_payloads(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    queue = DotNetRevisionUpdateQueue(lambda payload: not sent.append(dict(payload)))
    queue.observe_capabilities({"capabilities": [MESH_EDIT_REVISION_CAPABILITY]})
    active_path = tmp_path / "active.bin"
    replaced_path = tmp_path / "replaced.bin"
    pending_path = tmp_path / "pending.bin"
    for path in (active_path, replaced_path, pending_path):
        path.write_bytes(b"delta")

    assert queue.enqueue(1, (_packet("preview_vertex_update", active_path), _packet("preview_triangle_update")))
    assert len(sent) == 2
    assert queue.enqueue(2, (_packet("preview_vertex_update", replaced_path),))
    assert queue.enqueue(3, (_packet("preview_vertex_update", pending_path),))
    assert not replaced_path.exists()
    assert len(sent) == 2
    assert queue.acknowledge("preview_vertex_update_ack", {"edit_revision": 1, "status": "applied"})
    assert active_path.exists() and len(sent) == 2
    assert queue.acknowledge("preview_triangle_update_ack", {"edit_revision": 1, "status": "applied"})
    assert not active_path.exists() and len(sent) == 3
    assert sent[-1]["edit_revision"] == 3 and sent[-1]["revision"] == 3
    assert queue.acknowledge("preview_vertex_update_ack", {"edit_revision": 3, "status": "applied"})
    assert not pending_path.exists()
    metrics = queue.metrics()
    assert metrics["pending_depth"] == 0
    assert metrics["last_acked_revision"] == 3
    assert metrics["coalesced_updates"] == 1


def test_dotnet_revision_queue_rejects_stale_pending_and_keeps_legacy_alias(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    queue = DotNetRevisionUpdateQueue(lambda payload: not sent.append(dict(payload)))
    assert queue.enqueue(7, (_packet("preview_vertex_update"),))
    assert sent == [{"event": "preview_vertex_update", "edit_revision": 7, "revision": 7}]

    queue.observe_capabilities({"capabilities": [MESH_EDIT_REVISION_CAPABILITY]})
    timeout_path = tmp_path / "timeout.bin"
    timeout_path.write_bytes(b"delta")
    assert queue.enqueue(8, (_packet("preview_vertex_update", timeout_path),))
    stale_path = tmp_path / "stale.bin"
    stale_path.write_bytes(b"delta")
    assert queue.enqueue(8, (_packet("preview_vertex_update", stale_path),))
    assert not stale_path.exists()
    assert queue.metrics()["discarded_stale_updates"] == 1
    assert queue.acknowledge("preview_vertex_update_ack", {"edit_revision": 99, "status": "applied"})
    assert queue.metrics()["ignored_acks"] == 1
    assert queue.expire_active(8)
    assert timeout_path.exists()
    assert queue.metrics()["ack_timeouts"] == 1
    queue.reset()
    assert not timeout_path.exists()


def test_same_revision_selection_follows_active_topology_without_being_discarded() -> None:
    sent: list[dict[str, object]] = []
    queue = DotNetRevisionUpdateQueue(lambda payload: not sent.append(dict(payload)))
    queue.observe_capabilities({"capabilities": [MESH_EDIT_REVISION_CAPABILITY]})

    assert queue.enqueue(4, (_packet("preview_triangle_update"),))
    assert queue.enqueue(4, ({"event": "selection_update", "selection": {"source_indices": [2]}},))

    assert [packet["event"] for packet in sent] == ["preview_triangle_update", "selection_update"]
    assert queue.metrics()["discarded_stale_updates"] == 0
    assert queue.acknowledge("preview_triangle_update_ack", {"edit_revision": 4, "status": "applied"})
