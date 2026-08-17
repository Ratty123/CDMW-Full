"""Explicit Edit Mesh session transitions.

Whether Edit Mesh was open, closing, or already closed used to be inferred from
whichever combination of worker timing, pending dictionaries, and status text
happened to be readable at the call site. That is why Modify Original could race
its own worker and stop after preparation with nothing but a status message, and
why a renderer that died mid-finish could leave the tab unable to say whether
the edits had been committed.

This module owns the state and the legal moves between them, and nothing else.
It has no Qt, no protocol, and no knowledge of the tab, so every transition --
including the ones that only happen after a crash -- is reachable in a test.

A refused transition is a returned refusal, not an exception. Every caller here
is a protocol handler or a UI slot where raising would abandon a half-applied
session; they need to record the refusal and carry on holding the state they
already had.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MeshEditSessionState(str, Enum):
    """Where an Edit Mesh session is."""

    BUILDER_IDLE = "builder_idle"
    PREPARING_EDIT = "preparing_edit"
    EDIT_ACTIVE = "edit_active"
    APPLYING_COMMAND = "applying_command"
    FINISHING_EDIT = "finishing_edit"
    EDIT_COMMITTED = "edit_committed"
    EDIT_CANCELED = "edit_canceled"
    EDIT_RECOVERY_REQUIRED = "edit_recovery_required"


_S = MeshEditSessionState

# Every legal move. Anything absent is refused, which is the point: the old
# model had no illegal moves because it had no moves at all.
ALLOWED_TRANSITIONS: dict[MeshEditSessionState, frozenset[MeshEditSessionState]] = {
    _S.BUILDER_IDLE: frozenset({_S.PREPARING_EDIT}),
    # Preparation can fail before the helper ever enters mesh edit, and that is
    # a return to idle rather than a cancelled edit: nothing was opened.
    _S.PREPARING_EDIT: frozenset(
        {_S.EDIT_ACTIVE, _S.BUILDER_IDLE, _S.EDIT_RECOVERY_REQUIRED}
    ),
    _S.EDIT_ACTIVE: frozenset(
        {
            _S.APPLYING_COMMAND,
            _S.FINISHING_EDIT,
            _S.EDIT_CANCELED,
            _S.EDIT_RECOVERY_REQUIRED,
        }
    ),
    # A command result returns to EDIT_ACTIVE whether it succeeded or not. The
    # session is still open either way; the failure is the command's business.
    _S.APPLYING_COMMAND: frozenset({_S.EDIT_ACTIVE, _S.EDIT_RECOVERY_REQUIRED}),
    # Finishing goes back to EDIT_ACTIVE when a gate refuses it, which is what
    # "Finish Edit Mesh cannot complete while commands are pending" means: the
    # session stays open and usable rather than ending in an unknown state.
    _S.FINISHING_EDIT: frozenset(
        {_S.EDIT_COMMITTED, _S.EDIT_ACTIVE, _S.EDIT_RECOVERY_REQUIRED}
    ),
    _S.EDIT_COMMITTED: frozenset({_S.BUILDER_IDLE, _S.PREPARING_EDIT}),
    _S.EDIT_CANCELED: frozenset({_S.BUILDER_IDLE, _S.PREPARING_EDIT}),
    # Recovery is deliberately a dead end except for an explicit return to the
    # pre-edit candidate. There is no path from here to EDIT_COMMITTED: a
    # session whose renderer died mid-edit must never silently commit.
    _S.EDIT_RECOVERY_REQUIRED: frozenset({_S.BUILDER_IDLE}),
}

# States in which the session holds edits the user has not committed.
UNCOMMITTED_STATES = frozenset(
    {
        _S.PREPARING_EDIT,
        _S.EDIT_ACTIVE,
        _S.APPLYING_COMMAND,
        _S.FINISHING_EDIT,
        _S.EDIT_RECOVERY_REQUIRED,
    }
)

# States in which a mutation command may be sent.
COMMAND_ACCEPTING_STATES = frozenset({_S.EDIT_ACTIVE, _S.APPLYING_COMMAND})


@dataclass(frozen=True, slots=True)
class MeshEditTransition:
    """The outcome of asking for a move, accepted or refused."""

    accepted: bool
    previous: MeshEditSessionState
    current: MeshEditSessionState
    requested: MeshEditSessionState
    reason: str = ""
    refusal: str = ""

    def as_event_payload(self) -> dict[str, object]:
        return {
            "accepted": bool(self.accepted),
            "previous_state": self.previous.value,
            "current_state": self.current.value,
            "requested_state": self.requested.value,
            "reason": str(self.reason or ""),
            "refusal": str(self.refusal or ""),
        }


_HISTORY_LIMIT = 24


class MeshEditSessionMachine:
    """The authoritative Edit Mesh session state.

    One writer, one reader, and a recorded refusal for anything else. Callers
    ask for a move and act on the answer; they never set the state directly.
    """

    def __init__(self, state: MeshEditSessionState = MeshEditSessionState.BUILDER_IDLE) -> None:
        self._state = state
        self._generation = 0
        self._history: list[MeshEditTransition] = []

    @property
    def state(self) -> MeshEditSessionState:
        return self._state

    @property
    def generation(self) -> int:
        """How many accepted transitions this session has made.

        A command correlated against an older generation belongs to a session
        that has since been finished, cancelled, or recovered.
        """

        return self._generation

    def is_in(self, *states: MeshEditSessionState) -> bool:
        return self._state in states

    @property
    def has_uncommitted_edits(self) -> bool:
        return self._state in UNCOMMITTED_STATES

    @property
    def accepts_commands(self) -> bool:
        return self._state in COMMAND_ACCEPTING_STATES

    def can(self, target: MeshEditSessionState) -> bool:
        return target in ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def transition(
        self,
        target: MeshEditSessionState,
        *,
        reason: str = "",
    ) -> MeshEditTransition:
        """Move to ``target`` if the move is legal, and record either way."""

        previous = self._state
        if target is previous:
            # Re-asserting the current state is not a move and must not bump the
            # generation, or a repeated protocol event would retire correlated
            # commands that are still valid.
            outcome = MeshEditTransition(
                accepted=True,
                previous=previous,
                current=previous,
                requested=target,
                reason=str(reason or ""),
            )
            self._remember(outcome)
            return outcome
        if not self.can(target):
            outcome = MeshEditTransition(
                accepted=False,
                previous=previous,
                current=previous,
                requested=target,
                reason=str(reason or ""),
                refusal=f"{previous.value} cannot move to {target.value}",
            )
            self._remember(outcome)
            return outcome
        self._state = target
        self._generation += 1
        outcome = MeshEditTransition(
            accepted=True,
            previous=previous,
            current=target,
            requested=target,
            reason=str(reason or ""),
        )
        self._remember(outcome)
        return outcome

    def require_recovery(self, *, reason: str) -> MeshEditTransition:
        """Force the session into recovery from anywhere it can still hold edits.

        A renderer that dies mid-edit is not a transition the session chose, so
        it does not go through the normal legality check from every state -- but
        it must not manufacture an edit session out of an idle builder either.
        """

        if not self.has_uncommitted_edits:
            return MeshEditTransition(
                accepted=False,
                previous=self._state,
                current=self._state,
                requested=MeshEditSessionState.EDIT_RECOVERY_REQUIRED,
                reason=str(reason or ""),
                refusal="no uncommitted edits to recover",
            )
        return self.transition(
            MeshEditSessionState.EDIT_RECOVERY_REQUIRED,
            reason=reason,
        )

    def reset_to_idle(self, *, reason: str = "session_closed") -> MeshEditTransition:
        """Return to idle from any state, for a session that is being torn down."""

        previous = self._state
        if previous is MeshEditSessionState.BUILDER_IDLE:
            return self.transition(MeshEditSessionState.BUILDER_IDLE, reason=reason)
        self._state = MeshEditSessionState.BUILDER_IDLE
        self._generation += 1
        outcome = MeshEditTransition(
            accepted=True,
            previous=previous,
            current=MeshEditSessionState.BUILDER_IDLE,
            requested=MeshEditSessionState.BUILDER_IDLE,
            reason=str(reason or ""),
        )
        self._remember(outcome)
        return outcome

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self._state.value,
            "generation": int(self._generation),
            "has_uncommitted_edits": bool(self.has_uncommitted_edits),
            "accepts_commands": bool(self.accepts_commands),
            "allowed_transitions": tuple(
                sorted(target.value for target in ALLOWED_TRANSITIONS.get(self._state, ()))
            ),
            "history": tuple(entry.as_event_payload() for entry in self._history),
        }

    def _remember(self, outcome: MeshEditTransition) -> None:
        self._history.append(outcome)
        if len(self._history) > _HISTORY_LIMIT:
            del self._history[: len(self._history) - _HISTORY_LIMIT]


__all__ = [
    "ALLOWED_TRANSITIONS",
    "COMMAND_ACCEPTING_STATES",
    "UNCOMMITTED_STATES",
    "MeshEditSessionMachine",
    "MeshEditSessionState",
    "MeshEditTransition",
]
