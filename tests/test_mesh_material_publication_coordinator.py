"""Queue rules for resident material publication.

Every case here is one of the ordering accidents the pending-boolean model
allowed: work vanishing because another compile started, an answer from a
replaced compile being applied to the request that replaced it, a role's
failure taking a healthy role down with it, and a restarted renderer's old
generation settling a pane it no longer owns.
"""

from __future__ import annotations

import pytest

from cdmw.services.mesh_material_publication import (
    MaterialPublicationCoordinator,
    MaterialPublicationStatus,
    MaterialRole,
    normalize_material_role,
    normalize_material_roles,
)


IMPORTED = MaterialRole.EDITABLE_IMPORTED.value
ORIGINAL = MaterialRole.ORIGINAL_REFERENCE.value


def _coordinator() -> MaterialPublicationCoordinator:
    return MaterialPublicationCoordinator()


def _request(
    coordinator: MaterialPublicationCoordinator,
    *,
    roles: object = MaterialRole.EDITABLE_IMPORTED,
    reason: str = "changed",
    signature: str = "",
    priority: int = 0,
    session_id: str = "session-1",
    process_generation: int = 3,
    package_generation: int = 7,
    payload: object = None,
):
    return coordinator.build_request(
        session_id=session_id,
        process_generation=process_generation,
        package_generation=package_generation,
        roles=roles,
        reason=reason,
        signature=signature,
        priority=priority,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("original", ORIGINAL),
        ("Original-Reference", ORIGINAL),
        ("reference", ORIGINAL),
        ("editable_imported", IMPORTED),
        ("replacement", IMPORTED),
        ("", IMPORTED),
        (None, IMPORTED),
        (MaterialRole.ORIGINAL_REFERENCE, ORIGINAL),
    ],
)
def test_role_normalization_matches_the_resident_keys(value: object, expected: str) -> None:
    assert normalize_material_role(value) == expected


def test_role_sequences_keep_order_without_repeats() -> None:
    assert normalize_material_roles(["reference", "replacement", "original"]) == (
        ORIGINAL,
        IMPORTED,
    )
    assert normalize_material_roles("replacement") == (IMPORTED,)
    assert normalize_material_roles(None) == ()


def test_publish_ids_are_unique_and_monotonic() -> None:
    coordinator = _coordinator()
    ids = [_request(coordinator).publish_id for _ in range(4)]
    assert ids == sorted(set(ids))


def test_first_request_starts_and_a_second_waits_behind_it() -> None:
    coordinator = _coordinator()
    first, superseded = coordinator.enqueue(_request(coordinator, reason="imported"))
    assert superseded == ()
    second, _ = coordinator.enqueue(_request(coordinator, roles=ORIGINAL, reason="reference"))

    started = coordinator.begin_next(material_generation=11)
    assert started is not None and started.publish_id == first.publish_id
    assert started.material_generation == 11
    # The second must not displace the running one, which is the whole point of
    # the queue: the old model stopped the active worker instead.
    assert coordinator.begin_next() is None
    assert coordinator.queued and coordinator.queued[0].publish_id == second.publish_id

    result = coordinator.complete_active(first.publish_id)
    assert result is not None and result.succeeded
    assert coordinator.begin_next(material_generation=12).publish_id == second.publish_id


def test_newer_work_supersedes_queued_work_for_the_same_role_only() -> None:
    coordinator = _coordinator()
    active, _ = coordinator.enqueue(_request(coordinator, reason="first"))
    coordinator.begin_next(material_generation=1)
    stale_queued, _ = coordinator.enqueue(_request(coordinator, reason="second"))
    other_role, _ = coordinator.enqueue(_request(coordinator, roles=ORIGINAL, reason="reference"))

    newest, superseded = coordinator.enqueue(_request(coordinator, reason="third"))
    assert [result.publish_id for result in superseded] == [stale_queued.publish_id]
    assert superseded[0].status is MaterialPublicationStatus.SUPERSEDED
    queued_ids = [request.publish_id for request in coordinator.queued]
    assert other_role.publish_id in queued_ids
    assert newest.publish_id in queued_ids
    assert stale_queued.publish_id not in queued_ids
    # Active work is never touched by an enqueue.
    assert coordinator.active is not None
    assert coordinator.active.publish_id == active.publish_id


def test_identical_queued_work_is_coalesced_rather_than_repeated() -> None:
    coordinator = _coordinator()
    coordinator.enqueue(_request(coordinator, reason="first", signature="sig-a"))
    coordinator.begin_next(material_generation=1)
    queued, _ = coordinator.enqueue(_request(coordinator, reason="retry", signature="sig-b"))
    again, superseded = coordinator.enqueue(
        _request(coordinator, reason="retry", signature="sig-b", payload="newest")
    )

    assert superseded == ()
    assert len(coordinator.queued) == 1
    assert coordinator.counts()["coalesced"] == 1
    # One entry, but it carries the newest identity and payload: the caller's
    # correlation key has moved on, and an entry still holding the old one would
    # be rejected as stale when it compiled.
    assert again.publish_id > queued.publish_id
    assert coordinator.queued[0].publish_id == again.publish_id
    assert coordinator.queued[0].payload == "newest"


def test_a_result_for_replaced_work_cannot_settle_the_request_that_replaced_it() -> None:
    coordinator = _coordinator()
    first, _ = coordinator.enqueue(_request(coordinator, reason="first"))
    coordinator.begin_next(material_generation=1)
    canceled = coordinator.cancel_active(reason="model_replaced", detail="import B arrived")
    assert canceled is not None
    assert canceled.status is MaterialPublicationStatus.CANCELED

    second, _ = coordinator.enqueue(_request(coordinator, reason="second"))
    coordinator.begin_next(material_generation=2)
    assert coordinator.complete_active(first.publish_id) is None
    assert coordinator.active is not None and coordinator.active.publish_id == second.publish_id
    assert coordinator.counts()["stale_results"] == 1

    settled = coordinator.complete_active(second.publish_id)
    assert settled is not None and settled.succeeded


def test_is_current_rejects_a_foreign_session_process_or_package() -> None:
    coordinator = _coordinator()
    request, _ = coordinator.enqueue(_request(coordinator))
    coordinator.begin_next(material_generation=4)

    assert coordinator.is_current(
        request.publish_id,
        session_id="session-1",
        process_generation=3,
        package_generation=7,
    )
    assert not coordinator.is_current(request.publish_id, session_id="session-2")
    assert not coordinator.is_current(request.publish_id, process_generation=4)
    assert not coordinator.is_current(request.publish_id, package_generation=8)
    assert not coordinator.is_current(request.publish_id + 1)
    assert not coordinator.is_current("not-a-number")


def test_a_restarted_renderer_retires_work_from_the_old_process_generation() -> None:
    coordinator = _coordinator()
    old_active, _ = coordinator.enqueue(_request(coordinator, process_generation=3))
    coordinator.begin_next(material_generation=1)
    old_queued, _ = coordinator.enqueue(_request(coordinator, roles=ORIGINAL, process_generation=3))
    survivor, _ = coordinator.enqueue(_request(coordinator, reason="after", process_generation=4))

    retired = coordinator.invalidate_generations(process_generation=4)
    retired_ids = {result.publish_id for result in retired}
    assert retired_ids == {old_active.publish_id, old_queued.publish_id}
    assert all(result.status is MaterialPublicationStatus.STALE for result in retired)
    assert coordinator.active is None
    assert [request.publish_id for request in coordinator.queued] == [survivor.publish_id]


def test_a_failed_role_does_not_retire_a_ready_one() -> None:
    coordinator = _coordinator()
    imported, _ = coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    coordinator.begin_next(material_generation=1)
    coordinator.complete_active(imported.publish_id)

    original, _ = coordinator.enqueue(_request(coordinator, roles=ORIGINAL))
    coordinator.begin_next(material_generation=2)
    coordinator.complete_active(
        original.publish_id,
        status=MaterialPublicationStatus.FAILED,
        detail="missing base map",
    )

    imported_result = coordinator.last_result_for_role(IMPORTED)
    original_result = coordinator.last_result_for_role(ORIGINAL)
    assert imported_result is not None and imported_result.succeeded
    assert original_result is not None
    assert original_result.status is MaterialPublicationStatus.FAILED
    assert original_result.detail == "missing base map"
    assert not coordinator.has_work()


def test_pending_roles_reports_active_and_queued_work() -> None:
    coordinator = _coordinator()
    coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    coordinator.begin_next(material_generation=1)
    coordinator.enqueue(_request(coordinator, roles=ORIGINAL))

    assert coordinator.pending_roles() == (IMPORTED, ORIGINAL)
    assert coordinator.has_pending_role("replacement")
    assert coordinator.has_pending_role("original")
    assert coordinator.is_busy()


def test_cancel_all_drains_active_and_queued_work() -> None:
    coordinator = _coordinator()
    coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    coordinator.begin_next(material_generation=1)
    coordinator.enqueue(_request(coordinator, roles=ORIGINAL))
    coordinator.enqueue(_request(coordinator, roles=IMPORTED, reason="another"))

    results = coordinator.cancel_all(reason="session_closed")
    assert len(results) == 3
    assert all(result.status is MaterialPublicationStatus.CANCELED for result in results)
    assert all(result.reason == "session_closed" for result in results)
    assert not coordinator.has_work()
    assert coordinator.begin_next() is None


def test_priority_orders_the_queue_and_imported_can_be_put_first() -> None:
    coordinator = _coordinator()
    coordinator.enqueue(_request(coordinator, roles=IMPORTED, reason="occupier"))
    coordinator.begin_next(material_generation=1)
    coordinator.enqueue(_request(coordinator, roles=ORIGINAL, reason="reference", priority=10))
    imported, _ = coordinator.enqueue(
        _request(coordinator, roles=IMPORTED, reason="imported", priority=0)
    )

    # The Imported pane is the visible one, so its work leads even though the
    # reference publication was queued first.
    assert coordinator.queued[0].publish_id == imported.publish_id


def test_payloads_survive_the_queue_untouched() -> None:
    coordinator = _coordinator()
    payload = {"mesh_snapshot": object(), "submesh_index_offset": 4}
    coordinator.enqueue(_request(coordinator, payload=payload))
    started = coordinator.begin_next(material_generation=1)
    assert started is not None and started.payload is payload


def test_snapshot_reports_active_queued_and_history_for_diagnostics() -> None:
    coordinator = _coordinator()
    active, _ = coordinator.enqueue(_request(coordinator, roles=IMPORTED, reason="imported"))
    coordinator.begin_next(material_generation=5)
    coordinator.enqueue(_request(coordinator, roles=ORIGINAL, reason="reference"))

    snapshot = coordinator.snapshot()
    assert snapshot["active"]["publish_id"] == active.publish_id
    assert snapshot["active"]["material_generation"] == 5
    assert snapshot["active"]["roles"] == (IMPORTED,)
    assert len(snapshot["queued"]) == 1
    assert snapshot["queued"][0]["roles"] == (ORIGINAL,)
    assert snapshot["pending_roles"] == (IMPORTED, ORIGINAL)
    assert snapshot["counts"]["enqueued"] == 2
    assert snapshot["history"]

    coordinator.complete_active(active.publish_id)
    settled = coordinator.snapshot()
    assert settled["results_by_role"][IMPORTED]["status"] == "succeeded"
    assert settled["results_by_role"][IMPORTED]["publish_id"] == active.publish_id


def test_a_published_role_stays_outstanding_until_it_is_acknowledged() -> None:
    coordinator = _coordinator()
    request, _ = coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    coordinator.begin_next(material_generation=1)

    published = coordinator.publish_active(request.publish_id)
    assert published is not None
    assert published.status is MaterialPublicationStatus.PUBLISHED
    # The compiler slot is free, so the next role can compile while this one
    # waits for the renderer.
    assert not coordinator.is_busy()
    # ...but the pane is not ready, so the role is still outstanding.
    assert coordinator.has_pending_role(IMPORTED)
    assert coordinator.has_work()

    settled = coordinator.acknowledge(request.publish_id)
    assert settled is not None and settled.succeeded
    assert not coordinator.has_pending_role(IMPORTED)
    assert not coordinator.has_work()


def test_publishing_one_role_lets_the_other_compile_in_parallel() -> None:
    coordinator = _coordinator()
    imported, _ = coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    original, _ = coordinator.enqueue(_request(coordinator, roles=ORIGINAL))
    coordinator.begin_next(material_generation=1)
    coordinator.publish_active(imported.publish_id)

    assert coordinator.begin_next(material_generation=2).publish_id == original.publish_id
    assert coordinator.pending_roles() == (ORIGINAL, IMPORTED)

    coordinator.acknowledge(imported.publish_id)
    assert coordinator.has_pending_role(ORIGINAL)
    assert not coordinator.has_pending_role(IMPORTED)


def test_an_unmatched_acknowledgement_cannot_mark_a_role_ready() -> None:
    coordinator = _coordinator()
    request, _ = coordinator.enqueue(_request(coordinator, roles=IMPORTED))
    coordinator.begin_next(material_generation=1)
    coordinator.publish_active(request.publish_id)

    assert coordinator.acknowledge(request.publish_id + 5) is None
    assert coordinator.acknowledge("nonsense") is None
    assert coordinator.counts()["stale_results"] == 2
    assert coordinator.has_pending_role(IMPORTED)

    assert coordinator.acknowledge(request.publish_id) is not None
    # The same acknowledgement replayed is stale the second time.
    assert coordinator.acknowledge(request.publish_id) is None


def test_a_renderer_restart_retires_work_waiting_on_an_acknowledgement() -> None:
    coordinator = _coordinator()
    request, _ = coordinator.enqueue(_request(coordinator, process_generation=3))
    coordinator.begin_next(material_generation=1)
    coordinator.publish_active(request.publish_id)

    retired = coordinator.invalidate_generations(process_generation=4)
    assert [result.publish_id for result in retired] == [request.publish_id]
    assert retired[0].status is MaterialPublicationStatus.STALE
    assert not coordinator.has_work()
    # A late acknowledgement from the dead process settles nothing.
    assert coordinator.acknowledge(request.publish_id) is None


def test_an_explicit_publish_id_is_used_end_to_end() -> None:
    coordinator = _coordinator()
    request = coordinator.build_request(
        session_id="session-1",
        process_generation=3,
        package_generation=7,
        roles=IMPORTED,
        publish_id=42,
    )
    assert request.publish_id == 42
    assert request.material_generation == 42
    # Later auto-assigned ids must not collide with one that was handed in.
    assert coordinator.build_request(session_id="session-1", process_generation=3).publish_id == 43


def test_note_stale_result_is_recorded_without_touching_the_queue() -> None:
    coordinator = _coordinator()
    request, _ = coordinator.enqueue(_request(coordinator))
    coordinator.begin_next(material_generation=1)

    coordinator.note_stale_result(request.publish_id - 1, detail="late compile")
    assert coordinator.counts()["stale_results"] == 1
    assert coordinator.active is not None
    assert coordinator.active.publish_id == request.publish_id
    assert any(entry["detail"] == "late compile" for entry in coordinator.snapshot()["history"])
