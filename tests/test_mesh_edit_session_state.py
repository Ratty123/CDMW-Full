"""Edit Mesh session transitions, including the ones that only follow a crash.

The point of the machine is that the illegal moves are named. The two that
matter most are that a session whose renderer died mid-edit can never reach
EDIT_COMMITTED, and that a refused Finish leaves the session open rather than in
an unknown state.
"""

from __future__ import annotations

import pytest

from cdmw.services.mesh_edit_session_state import (
    ALLOWED_TRANSITIONS,
    MeshEditSessionMachine,
    MeshEditSessionState as S,
)


def _machine(state: S = S.BUILDER_IDLE) -> MeshEditSessionMachine:
    return MeshEditSessionMachine(state)


def _drive(machine: MeshEditSessionMachine, *states: S) -> None:
    for state in states:
        assert machine.transition(state, reason="test").accepted, state


def test_a_new_session_starts_idle_and_holds_nothing() -> None:
    machine = _machine()
    assert machine.state is S.BUILDER_IDLE
    assert machine.generation == 0
    assert not machine.has_uncommitted_edits
    assert not machine.accepts_commands


def test_the_ordinary_edit_round_trip() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE)
    assert machine.accepts_commands
    assert machine.has_uncommitted_edits

    _drive(machine, S.APPLYING_COMMAND)
    assert machine.accepts_commands
    _drive(machine, S.EDIT_ACTIVE, S.FINISHING_EDIT)
    assert not machine.accepts_commands

    _drive(machine, S.EDIT_COMMITTED)
    assert not machine.has_uncommitted_edits
    _drive(machine, S.BUILDER_IDLE)


def test_every_state_declares_its_legal_moves() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_an_illegal_move_is_refused_without_changing_state() -> None:
    machine = _machine()
    outcome = machine.transition(S.EDIT_ACTIVE, reason="skip_preparation")

    assert not outcome.accepted
    assert outcome.refusal == "builder_idle cannot move to edit_active"
    assert outcome.reason == "skip_preparation"
    assert machine.state is S.BUILDER_IDLE
    assert machine.generation == 0


def test_re_asserting_the_current_state_is_accepted_but_not_a_move() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE)
    generation = machine.generation

    outcome = machine.transition(S.EDIT_ACTIVE, reason="duplicate_protocol_event")
    assert outcome.accepted
    # A repeated protocol event must not retire commands correlated against the
    # generation it is repeating.
    assert machine.generation == generation


def test_a_refused_finish_leaves_the_session_open() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE, S.FINISHING_EDIT)

    _drive(machine, S.EDIT_ACTIVE)
    assert machine.accepts_commands
    assert machine.has_uncommitted_edits


def test_a_session_in_recovery_can_never_commit() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE, S.FINISHING_EDIT)

    recovered = machine.require_recovery(reason="renderer_process_restarted")
    assert recovered.accepted
    assert machine.state is S.EDIT_RECOVERY_REQUIRED

    for target in (S.EDIT_COMMITTED, S.EDIT_ACTIVE, S.FINISHING_EDIT, S.APPLYING_COMMAND):
        assert not machine.transition(target, reason="after_recovery").accepted
        assert machine.state is S.EDIT_RECOVERY_REQUIRED
    # The only way out is back to the pre-edit candidate.
    assert machine.transition(S.BUILDER_IDLE, reason="return_to_candidate").accepted


@pytest.mark.parametrize(
    "state",
    [S.PREPARING_EDIT, S.EDIT_ACTIVE, S.APPLYING_COMMAND, S.FINISHING_EDIT],
)
def test_recovery_is_reachable_from_every_state_that_holds_edits(state: S) -> None:
    machine = _machine(state)
    assert machine.has_uncommitted_edits
    assert machine.require_recovery(reason="renderer_died").accepted
    assert machine.state is S.EDIT_RECOVERY_REQUIRED


@pytest.mark.parametrize("state", [S.BUILDER_IDLE, S.EDIT_COMMITTED, S.EDIT_CANCELED])
def test_recovery_cannot_invent_an_edit_session(state: S) -> None:
    machine = _machine(state)
    outcome = machine.require_recovery(reason="renderer_died")

    assert not outcome.accepted
    assert outcome.refusal == "no uncommitted edits to recover"
    assert machine.state is state


def test_preparation_that_fails_returns_to_idle_not_to_cancelled() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT)
    # Nothing was opened, so there is no edit to cancel.
    assert not machine.transition(S.EDIT_CANCELED, reason="prepare_failed").accepted
    assert machine.transition(S.BUILDER_IDLE, reason="prepare_failed").accepted


def test_cancel_from_an_active_edit_reaches_idle() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE, S.EDIT_CANCELED)
    assert not machine.has_uncommitted_edits
    _drive(machine, S.BUILDER_IDLE)


def test_a_committed_or_cancelled_session_can_open_a_new_edit_directly() -> None:
    for terminal in (S.EDIT_COMMITTED, S.EDIT_CANCELED):
        machine = _machine(terminal)
        assert machine.transition(S.PREPARING_EDIT, reason="reopen").accepted


def test_reset_to_idle_works_from_anywhere_and_counts_as_a_move() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE, S.APPLYING_COMMAND)
    generation = machine.generation

    outcome = machine.reset_to_idle(reason="session_closed")
    assert outcome.accepted
    assert outcome.previous is S.APPLYING_COMMAND
    assert machine.state is S.BUILDER_IDLE
    # The bump is what invalidates commands still correlated to the old session.
    assert machine.generation > generation


def test_reset_from_idle_does_not_bump_the_generation() -> None:
    machine = _machine()
    assert machine.reset_to_idle(reason="already_idle").accepted
    assert machine.generation == 0


def test_the_snapshot_names_the_state_and_what_it_can_do_next() -> None:
    machine = _machine()
    _drive(machine, S.PREPARING_EDIT, S.EDIT_ACTIVE)

    snapshot = machine.snapshot()
    assert snapshot["state"] == "edit_active"
    assert snapshot["generation"] == 2
    assert snapshot["has_uncommitted_edits"] is True
    assert snapshot["accepts_commands"] is True
    assert snapshot["allowed_transitions"] == (
        "applying_command",
        "edit_canceled",
        "edit_recovery_required",
        "finishing_edit",
    )
    assert [entry["current_state"] for entry in snapshot["history"]] == [
        "preparing_edit",
        "edit_active",
    ]


def test_refusals_are_recorded_in_history() -> None:
    machine = _machine()
    machine.transition(S.EDIT_COMMITTED, reason="commit_without_editing")

    history = machine.snapshot()["history"]
    assert len(history) == 1
    assert history[0]["accepted"] is False
    assert history[0]["requested_state"] == "edit_committed"
    assert history[0]["current_state"] == "builder_idle"
