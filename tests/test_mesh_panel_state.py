from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshPanelSnapshot, MeshPanelStatus, MeshPanelUnavailableError


def test_pending_new_revision_retains_last_good_value_without_making_it_current() -> None:
    pending = MeshPanelSnapshot.unavailable().begin_refresh(session_id="mesh-a", revision=4)
    ready = pending.publish_ready({"parts": 3})

    refreshing = ready.begin_refresh(session_id="mesh-a", revision=5)

    assert refreshing.status is MeshPanelStatus.PENDING
    assert refreshing.revision == 5
    assert refreshing.value == {"parts": 3}
    assert refreshing.value_revision == 4
    assert not refreshing.is_current(session_id="mesh-a", revision=5)


def test_new_session_never_inherits_an_old_sessions_value() -> None:
    ready = (
        MeshPanelSnapshot.unavailable()
        .begin_refresh(session_id="mesh-a", revision=2)
        .publish_ready("summary-a")
    )

    refreshing = ready.begin_refresh(session_id="mesh-b", revision=1)

    assert refreshing.value is None
    assert refreshing.value_session_id == ""
    assert refreshing.value_revision is None


def test_request_identity_includes_session_revision_and_generation() -> None:
    first = MeshPanelSnapshot.unavailable().begin_refresh(session_id="mesh-a", revision=7)
    second = first.begin_refresh(session_id="mesh-a", revision=7)

    assert not second.matches_request(session_id="mesh-a", revision=7, generation=first.generation)
    assert not second.matches_request(session_id="mesh-a", revision=6, generation=second.generation)
    assert not second.matches_request(session_id="mesh-b", revision=7, generation=second.generation)
    assert second.matches_request(session_id="mesh-a", revision=7, generation=second.generation)


def test_expected_unavailability_retains_last_good_value_and_stable_code() -> None:
    ready = (
        MeshPanelSnapshot.unavailable()
        .begin_refresh(session_id="mesh-a", revision=8)
        .publish_ready("last-good")
    )
    pending = ready.begin_refresh(session_id="mesh-a", revision=9)

    unavailable = pending.publish_error(
        error_code="native_snapshot_pending",
        message="Native snapshot is pending.",
        unavailable=True,
    )

    assert unavailable.status is MeshPanelStatus.UNAVAILABLE
    assert unavailable.error_code == "native_snapshot_pending"
    assert unavailable.value == "last-good"
    assert unavailable.value_revision == 8


def test_unexpected_error_retains_last_good_but_cannot_be_current() -> None:
    ready = (
        MeshPanelSnapshot.unavailable()
        .begin_refresh(session_id="mesh-a", revision=10)
        .publish_ready("last-good")
    )

    failed = ready.begin_refresh(session_id="mesh-a", revision=11).publish_error(
        error_code="unexpected_summary_failure",
        message="decoder exploded",
    )

    assert failed.status is MeshPanelStatus.ERROR
    assert failed.value == "last-good"
    assert failed.value_revision == 10
    assert not failed.is_current(session_id="mesh-a", revision=11)


def test_ready_publication_requires_a_pending_request() -> None:
    with pytest.raises(RuntimeError, match="pending panel request"):
        MeshPanelSnapshot.unavailable().publish_ready("impossible")


def test_typed_unavailability_requires_stable_diagnostics() -> None:
    error = MeshPanelUnavailableError("native_snapshot_stale", "Native snapshot is stale.")

    assert error.code == "native_snapshot_stale"
    assert str(error) == "Native snapshot is stale."
