from __future__ import annotations

from pathlib import Path

from cdmw.ui.mesh_editor.dotnet_update_queue import (
    MESH_EDIT_REVISION_CAPABILITY,
    MESH_MUTATION_ENVELOPE_CAPABILITY,
    DotNetRevisionUpdateQueue,
)


def _packet(event: str, owned_path: Path | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"event": event}
    if owned_path is not None:
        payload["vertex_groups"] = (
            {"positions_binary": {"path": str(owned_path), "delete_after": True}},
        )
    return payload


def _vertex_packet(indices: list[int], x_values: list[float]) -> dict[str, object]:
    return {
        "event": "preview_vertex_update",
        "vertex_groups": [
            {
                "source_submesh_index": 0,
                "source_vertex_indices": indices,
                "positions": [
                    component
                    for x in x_values
                    for component in (x, 0.0, 0.0)
                ],
            }
        ],
    }


def _ack(sent: list[dict[str, object]], *, status: str = "applied") -> dict[str, object]:
    active = sent[-1]
    return {
        "session_id": active["session_id"],
        "request_id": active["request_id"],
        "process_generation": active["process_generation"],
        "edit_revision": active["edit_revision"],
        "status": status,
        "capabilities": [
            MESH_EDIT_REVISION_CAPABILITY,
            MESH_MUTATION_ENVELOPE_CAPABILITY,
        ],
    }


def _correlated_queue(
    sent: list[dict[str, object]],
    *,
    resync_packets=None,
    max_pending_batches: int = 64,
) -> DotNetRevisionUpdateQueue:
    queue = DotNetRevisionUpdateQueue(
        lambda payload: not sent.append(dict(payload)),
        resync_packets=resync_packets,
        max_pending_batches=max_pending_batches,
    )
    queue.set_context(session_id="mesh-session", process_generation=7)
    queue.observe_capabilities(
        {
            "capabilities": [
                MESH_EDIT_REVISION_CAPABILITY,
                MESH_MUTATION_ENVELOPE_CAPABILITY,
            ]
        }
    )
    return queue


def test_independent_sparse_revisions_are_coalesced_without_losing_items() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)

    assert queue.enqueue(1, (_vertex_packet([0], [1.0]),))
    assert queue.enqueue(2, (_vertex_packet([1], [2.0]),))
    assert queue.enqueue(3, (_vertex_packet([2], [3.0]),))
    assert len(sent) == 1

    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert len(sent) == 2
    merged = sent[-1]["vertex_groups"][0]
    assert merged["source_vertex_indices"] == [1, 2]
    assert merged["positions"][::3] == [2.0, 3.0]
    assert sent[-1]["edit_revision"] == 3
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert queue.metrics()["pending_depth"] == 0
    assert queue.metrics()["last_acked_revision"] == 3


def test_repeated_vertex_edit_coalesces_to_newest_absolute_value() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)

    assert queue.enqueue(1, (_vertex_packet([0], [1.0]),))
    assert queue.enqueue(2, (_vertex_packet([4], [2.0]),))
    assert queue.enqueue(3, (_vertex_packet([4], [9.0]),))
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))

    merged = sent[-1]["vertex_groups"][0]
    assert merged["source_vertex_indices"] == [4]
    assert merged["positions"][::3] == [9.0]
    assert queue.metrics()["coalesced_updates"] == 1


def test_topology_is_a_barrier_and_owned_payloads_survive_until_each_ack(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)
    active_path = tmp_path / "active.bin"
    before_barrier = tmp_path / "before.bin"
    after_barrier = tmp_path / "after.bin"
    for path in (active_path, before_barrier, after_barrier):
        path.write_bytes(b"delta")

    assert queue.enqueue(1, (_packet("preview_vertex_update", active_path),))
    assert queue.enqueue(2, (_packet("preview_vertex_update", before_barrier),))
    assert queue.enqueue(3, (_packet("preview_triangle_update"),))
    assert queue.enqueue(4, (_packet("preview_vertex_update", after_barrier),))
    assert before_barrier.exists()
    assert after_barrier.exists()

    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert not active_path.exists()
    assert sent[-1]["edit_revision"] == 2
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert not before_barrier.exists()
    assert sent[-1]["event"] == "preview_triangle_update"
    assert queue.acknowledge("preview_triangle_update_ack", _ack(sent))
    assert sent[-1]["edit_revision"] == 4
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert not after_barrier.exists()


def test_wrong_session_request_and_process_generation_acks_are_ignored() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)
    assert queue.enqueue(8, (_vertex_packet([0], [1.0]),))
    good = _ack(sent)
    for key, value in (
        ("session_id", "wrong-session"),
        ("request_id", 999),
        ("process_generation", 99),
    ):
        bad = dict(good)
        bad[key] = value
        assert queue.acknowledge("preview_vertex_update_ack", bad)
        assert queue.metrics()["active_revision"] == 8
    assert queue.metrics()["ignored_acks"] == 3
    assert queue.acknowledge("preview_vertex_update_ack", good)


def test_rejection_and_timeout_attempt_exactly_one_in_process_resync() -> None:
    sent: list[dict[str, object]] = []

    def resync_packets():
        return ({"event": "resident_state_resync", "snapshot": "authoritative"},)

    queue = _correlated_queue(sent, resync_packets=resync_packets)
    assert queue.enqueue(5, (_vertex_packet([0], [1.0]),))
    assert queue.acknowledge(
        "preview_vertex_update_ack",
        _ack(sent, status="rejected"),
    )
    assert sent[-1]["event"] == "resident_state_resync"
    assert queue.metrics()["resync_attempts"] == 1
    assert queue.acknowledge("resident_state_resync_ack", _ack(sent))
    assert queue.metrics()["recovery_failed"] is False

    assert queue.enqueue(6, (_vertex_packet([1], [2.0]),))
    assert queue.expire_active(6)
    assert sent[-1]["event"] == "resident_state_resync"
    assert queue.metrics()["resync_attempts"] == 2
    assert queue.expire_active(6)
    assert queue.metrics()["recovery_failed"] is True
    assert queue.metrics()["resync_attempts"] == 2


def test_failed_resync_exposes_recovery_and_shutdown_cleans_all_payloads(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    resync_path = tmp_path / "resync.bin"
    active_path = tmp_path / "active.bin"
    pending_path = tmp_path / "pending.bin"
    for path in (resync_path, active_path, pending_path):
        path.write_bytes(b"delta")

    queue = _correlated_queue(
        sent,
        resync_packets=lambda: (
            {
                "event": "resident_state_resync",
                "snapshot_binary": {
                    "path": str(resync_path),
                    "delete_after": True,
                },
            },
        ),
    )
    assert queue.enqueue(1, (_packet("preview_vertex_update", active_path),))
    assert queue.enqueue(2, (_packet("preview_vertex_update", pending_path),))
    assert queue.acknowledge(
        "preview_vertex_update_ack",
        _ack(sent, status="rejected"),
    )
    assert queue.acknowledge(
        "resident_state_resync_ack",
        _ack(sent, status="rejected"),
    )
    assert queue.metrics()["recovery_failed"] is True
    assert not active_path.exists()
    assert not resync_path.exists()
    queue.reset()
    assert not pending_path.exists()


def test_selection_snapshot_follows_active_topology_without_waiting_for_a_second_ack() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)

    assert queue.enqueue(4, (_packet("preview_triangle_update"),))
    assert queue.enqueue(
        4,
        ({"event": "selection_update", "selection": {"source_indices": [2]}},),
    )

    assert [packet["event"] for packet in sent] == [
        "preview_triangle_update",
        "selection_update",
    ]
    assert sent[0]["request_id"] == sent[1]["request_id"]
    assert queue.acknowledge("preview_triangle_update_ack", _ack(sent))


def test_bounded_pending_state_applies_backpressure_without_dropping_existing_work() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent, max_pending_batches=1)

    assert queue.enqueue(1, (_packet("preview_vertex_update"),))
    assert queue.enqueue(2, (_packet("preview_vertex_update"),))
    assert not queue.enqueue(3, (_packet("preview_triangle_update"),))
    assert queue.metrics()["pending_depth"] == 1
    assert queue.metrics()["pending_backpressure"] == 1
