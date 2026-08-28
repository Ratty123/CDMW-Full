from __future__ import annotations

from pathlib import Path

from cdmw.ui.mesh_editor.dotnet_update_queue import (
    MESH_EDIT_REVISION_CAPABILITY,
    MESH_MUTATION_BATCH_CAPABILITY,
    MESH_MUTATION_ENVELOPE_CAPABILITY,
    DotNetRevisionUpdateQueue,
)
from cdmw.domain.mesh.resident_mutation import ResidentMutationBatch


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


def _atomic_queue(
    sent: list[dict[str, object]],
    *,
    renderer_revision: int = 4,
) -> DotNetRevisionUpdateQueue:
    queue = DotNetRevisionUpdateQueue(lambda payload: not sent.append(dict(payload)))
    queue.set_context(
        session_id="mesh-session",
        process_generation=7,
        renderer_revision=renderer_revision,
    )
    queue.observe_capabilities(
        {
            "capabilities": [
                MESH_EDIT_REVISION_CAPABILITY,
                MESH_MUTATION_ENVELOPE_CAPABILITY,
                MESH_MUTATION_BATCH_CAPABILITY,
            ]
        }
    )
    return queue


def _mutation_batch(
    *,
    request_id: int,
    base_revision: int,
    target_revision: int,
    owned_path: Path | None = None,
) -> ResidentMutationBatch:
    vertex_group: dict[str, object] = {
        "source_submesh_index": 0,
        "source_vertex_indices": [0],
        "positions": [1.0, 0.0, 0.0],
    }
    temporary_payloads: tuple[dict[str, object], ...] = ()
    if owned_path is not None:
        descriptor = {"path": str(owned_path), "delete_after": True}
        vertex_group["positions_binary"] = descriptor
        vertex_group.pop("positions", None)
        temporary_payloads = (descriptor,)
    return ResidentMutationBatch(
        session_id="mesh-session",
        process_generation=7,
        request_id=request_id,
        base_revision=base_revision,
        target_revision=target_revision,
        action="transform",
        vertex_updates=(vertex_group,),
        material_updates=(
            {
                "source_submesh_indices": [0],
                "editor_role": "replacement_preview",
                "roughness": 0.5,
            },
        ),
        selection_update={"vertices_by_submesh": {"0": [0]}},
        affected_submesh_indices=(0,),
        temporary_payloads=temporary_payloads,
    )


def _mutation_ack(
    sent: list[dict[str, object]],
    *,
    status: str = "applied",
    applied_revision: int | None = None,
) -> dict[str, object]:
    active = sent[-1]
    target_revision = int(active["target_revision"])
    return {
        "session_id": active["session_id"],
        "process_generation": active["process_generation"],
        "request_id": active["request_id"],
        "base_revision": active["base_revision"],
        "target_revision": target_revision,
        "edit_revision": target_revision,
        "applied_renderer_revision": (
            target_revision if applied_revision is None else int(applied_revision)
        ),
        "protocol_version": 3,
        "status": status,
        "capabilities": [
            MESH_EDIT_REVISION_CAPABILITY,
            MESH_MUTATION_ENVELOPE_CAPABILITY,
            MESH_MUTATION_BATCH_CAPABILITY,
        ],
    }


def test_resident_mutation_batch_serializes_one_complete_authority() -> None:
    batch = _mutation_batch(request_id=11, base_revision=4, target_revision=5)

    payload = batch.as_protocol_payload()

    assert payload["event"] == "resident_mutation_batch"
    assert payload["session_id"] == "mesh-session"
    assert payload["process_generation"] == 7
    assert payload["request_id"] == 11
    assert payload["base_revision"] == 4
    assert payload["target_revision"] == 5
    assert payload["protocol_version"] == 3
    assert payload["vertex_updates"]
    assert payload["material_updates"]
    assert payload["selection_update"]
    assert payload["affected_submesh_indices"] == [0]
    assert payload["recovery_snapshot"] is False


def test_atomic_batch_waits_for_one_ack_before_releasing_payload(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    owned = tmp_path / "positions.bin"
    owned.write_bytes(b"positions")
    queue = _atomic_queue(sent)

    assert queue.enqueue_mutation_batch(
        _mutation_batch(
            request_id=11,
            base_revision=4,
            target_revision=5,
            owned_path=owned,
        )
    )

    assert len(sent) == 1
    assert sent[0]["event"] == "resident_mutation_batch"
    assert owned.exists()
    assert queue.metrics()["active_revision"] == 5
    assert queue.acknowledge("resident_mutation_batch_ack", _mutation_ack(sent))
    assert not owned.exists()
    assert queue.metrics()["last_acked_revision"] == 5
    assert queue.metrics()["active_revision"] == 0


def test_atomic_batches_preserve_distinct_positive_request_order() -> None:
    sent: list[dict[str, object]] = []
    queue = _atomic_queue(sent)

    assert queue.enqueue_mutation_batch(
        _mutation_batch(request_id=11, base_revision=4, target_revision=5)
    )
    assert queue.enqueue_mutation_batch(
        _mutation_batch(request_id=12, base_revision=5, target_revision=6)
    )
    assert len(sent) == 1
    assert queue.metrics()["pending_depth"] == 1

    assert queue.acknowledge("resident_mutation_batch_ack", _mutation_ack(sent))
    assert len(sent) == 2
    assert [int(payload["request_id"]) for payload in sent] == [11, 12]
    assert queue.acknowledge("resident_mutation_batch_ack", _mutation_ack(sent))
    assert queue.metrics()["last_acked_revision"] == 6


def test_atomic_timeout_replays_same_request_once_and_restores_equality(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    owned = tmp_path / "positions.bin"
    owned.write_bytes(b"positions")
    queue = _atomic_queue(sent)
    assert queue.enqueue_mutation_batch(
        _mutation_batch(
            request_id=11,
            base_revision=4,
            target_revision=5,
            owned_path=owned,
        )
    )

    assert queue.expire_active(5)
    assert len(sent) == 2
    assert sent[-1]["request_id"] == sent[0]["request_id"] == 11
    assert sent[-1]["recovery_snapshot"] is True
    assert sent[-1]["mutation_kind"] == "recovery_snapshot"
    assert queue.metrics()["resync_attempts"] == 1
    assert owned.exists()

    assert queue.acknowledge("resident_mutation_batch_ack", _mutation_ack(sent))
    assert queue.metrics()["recovery_failed"] is False
    assert queue.metrics()["last_acked_revision"] == 5
    assert not owned.exists()


def test_invalid_atomic_ack_replays_then_failed_recovery_cleans_payload(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    owned = tmp_path / "positions.bin"
    owned.write_bytes(b"positions")
    queue = _atomic_queue(sent)
    assert queue.enqueue_mutation_batch(
        _mutation_batch(
            request_id=11,
            base_revision=4,
            target_revision=5,
            owned_path=owned,
        )
    )

    invalid = _mutation_ack(sent, applied_revision=4)
    assert queue.acknowledge("resident_mutation_batch_ack", invalid)
    assert sent[-1]["recovery_snapshot"] is True
    assert owned.exists()

    assert queue.acknowledge(
        "resident_mutation_batch_ack",
        _mutation_ack(sent, status="rejected"),
    )
    assert queue.metrics()["recovery_failed"] is True
    assert not owned.exists()


def test_atomic_batch_rejects_a_broken_revision_chain_without_sending() -> None:
    sent: list[dict[str, object]] = []
    queue = _atomic_queue(sent)

    assert not queue.enqueue_mutation_batch(
        _mutation_batch(request_id=11, base_revision=3, target_revision=5)
    )

    assert sent == []
    assert queue.metrics()["correlation_conflicts"] == 1


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


def test_correlated_vertex_requests_are_not_coalesced_across_mutations() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)

    active = _vertex_packet([0], [1.0])
    active["request_id"] = 1
    stroke_terminal = _vertex_packet([1], [2.0])
    stroke_terminal["request_id"] = 2
    later_morph = _vertex_packet([2], [3.0])
    later_morph["request_id"] = 3

    assert queue.enqueue(1, (active,))
    assert queue.enqueue(2, (stroke_terminal,))
    assert queue.enqueue(3, (later_morph,))
    assert queue.metrics()["pending_depth"] == 2
    assert queue.metrics()["coalesced_updates"] == 0

    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert sent[-1]["request_id"] == 2
    assert sent[-1]["edit_revision"] == 2
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert sent[-1]["request_id"] == 3
    assert sent[-1]["edit_revision"] == 3
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert queue.metrics()["pending_depth"] == 0


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


def test_same_revision_terminal_selection_keeps_its_own_mutation_request_id() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)
    geometry = _vertex_packet([0], [1.0])
    geometry["request_id"] = 40
    selection = {
        "event": "selection_update",
        "request_id": 55,
        "selection": {"faces_by_submesh": {"0": [3]}},
    }

    assert queue.enqueue(7, (geometry,))
    assert queue.enqueue(7, (selection,))
    assert [(packet["event"], packet["request_id"]) for packet in sent] == [
        ("preview_vertex_update", 40),
    ]

    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert [(packet["event"], packet["request_id"]) for packet in sent] == [
        ("preview_vertex_update", 40),
        ("selection_update", 55),
    ]
    assert queue.metrics()["recovery_failed"] is False


def test_pending_geometry_and_selection_mutations_remain_separate_batches() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)
    active = _vertex_packet([0], [1.0])
    active["request_id"] = 100
    pending_geometry = _vertex_packet([1], [2.0])
    pending_geometry["request_id"] = 101
    terminal_selection = {
        "event": "selection_update",
        "request_id": 102,
        "selection": {"vertices_by_submesh": {"0": [1]}},
    }

    assert queue.enqueue(10, (active,))
    assert queue.enqueue(11, (pending_geometry,))
    assert queue.enqueue(12, (terminal_selection,))
    assert queue.metrics()["pending_depth"] == 2
    assert queue.metrics()["coalesced_updates"] == 0

    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert sent[-1]["event"] == "preview_vertex_update"
    assert sent[-1]["request_id"] == 101
    assert sent[-1]["edit_revision"] == 11
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    assert sent[-1]["event"] == "selection_update"
    assert sent[-1]["request_id"] == 102
    assert sent[-1]["edit_revision"] == 12


def test_distinct_correlated_selection_mutations_never_collapse() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)
    active = _vertex_packet([0], [1.0])
    active["request_id"] = 200
    first = {"event": "selection_update", "request_id": 201, "selection": {}}
    second = {"event": "selection_update", "request_id": 202, "selection": {}}

    assert queue.enqueue(20, (active,))
    assert queue.enqueue(21, (first,))
    assert queue.enqueue(21, (second,))
    assert queue.metrics()["pending_depth"] == 2
    assert queue.acknowledge("preview_vertex_update_ack", _ack(sent))
    # No ack is required for selection, so finishing the first batch sends the
    # second one immediately without rewriting either envelope.
    assert [(packet["event"], packet["request_id"]) for packet in sent] == [
        ("preview_vertex_update", 200),
        ("selection_update", 201),
        ("selection_update", 202),
    ]


def test_one_batch_cannot_mix_independent_correlated_requests() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent)

    assert not queue.enqueue(
        4,
        (
            {"event": "selection_update", "request_id": 10, "selection": {}},
            {"event": "selection_update", "request_id": 11, "selection": {}},
        ),
    )
    assert sent == []
    assert queue.metrics()["correlation_conflicts"] == 1


def test_bounded_pending_state_applies_backpressure_without_dropping_existing_work() -> None:
    sent: list[dict[str, object]] = []
    queue = _correlated_queue(sent, max_pending_batches=1)

    assert queue.enqueue(1, (_packet("preview_vertex_update"),))
    assert queue.enqueue(2, (_packet("preview_vertex_update"),))
    assert not queue.enqueue(3, (_packet("preview_triangle_update"),))
    assert queue.metrics()["pending_depth"] == 1
    assert queue.metrics()["pending_backpressure"] == 1
