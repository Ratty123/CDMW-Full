"""Revision-bound state for Mesh Editor derived panels.

Derived reports can finish after the active mesh or geometry revision changes.
This snapshot keeps the requested target separate from the revision that
produced the retained value, so a panel can show last-known-good data without
mistaking it for current authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Generic, TypeVar


PanelValueT = TypeVar("PanelValueT")


class MeshPanelKind(str, Enum):
    WORKSPACE = "workspace"
    UV = "uv"
    SKELETON = "skeleton"
    COMPARE = "compare"
    VALIDATION = "validation"
    REBUILD = "rebuild"


class MeshPanelStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class MeshPanelUnavailableError(RuntimeError):
    """Expected condition where authoritative panel data cannot be produced."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = str(code or "").strip()
        normalized_message = str(message or "").strip()
        if not normalized_code:
            raise ValueError("panel unavailability code must not be empty")
        if not normalized_message:
            raise ValueError("panel unavailability message must not be empty")
        super().__init__(normalized_message)
        self.code = normalized_code


@dataclass(frozen=True, slots=True)
class MeshPanelSnapshot(Generic[PanelValueT]):
    """State and retained value for one session/revision-bound panel."""

    session_id: str
    revision: int | None
    generation: int
    status: MeshPanelStatus
    value: PanelValueT | None = None
    value_session_id: str = ""
    value_revision: int | None = None
    error_code: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("panel generation must not be negative")
        if self.revision is not None and self.revision < 0:
            raise ValueError("panel revision must not be negative")
        if self.value_revision is not None and self.value_revision < 0:
            raise ValueError("panel value revision must not be negative")
        if self.status in {MeshPanelStatus.READY, MeshPanelStatus.PENDING, MeshPanelStatus.ERROR}:
            if not self.session_id or self.revision is None:
                raise ValueError(f"{self.status.value} panel state requires a session and revision")
        if self.status is MeshPanelStatus.READY:
            if self.value is None:
                raise ValueError("ready panel state requires a value")
            if self.value_session_id != self.session_id or self.value_revision != self.revision:
                raise ValueError("ready panel value must match its target session and revision")
        if self.value is None:
            if self.value_session_id or self.value_revision is not None:
                raise ValueError("empty panel value must not carry value authority")
        elif not self.value_session_id or self.value_revision is None:
            raise ValueError("retained panel value requires its source session and revision")
        if self.status is MeshPanelStatus.ERROR and not self.error_code:
            raise ValueError("error panel state requires a stable error code")

    @classmethod
    def unavailable(cls, *, message: str = "") -> "MeshPanelSnapshot[PanelValueT]":
        return cls(
            session_id="",
            revision=None,
            generation=0,
            status=MeshPanelStatus.UNAVAILABLE,
            message=str(message or "").strip(),
        )

    def begin_refresh(
        self,
        *,
        session_id: str,
        revision: int,
        message: str = "",
    ) -> "MeshPanelSnapshot[PanelValueT]":
        target_session = _session_id(session_id)
        target_revision = _revision(revision)
        value, value_session_id, value_revision = self._retained_value(target_session)
        return MeshPanelSnapshot(
            session_id=target_session,
            revision=target_revision,
            generation=self.generation + 1,
            status=MeshPanelStatus.PENDING,
            value=value,
            value_session_id=value_session_id,
            value_revision=value_revision,
            message=str(message or "").strip(),
        )

    def mark_unavailable(
        self,
        *,
        session_id: str = "",
        revision: int | None = None,
        message: str = "",
    ) -> "MeshPanelSnapshot[PanelValueT]":
        target_session = str(session_id or "").strip()
        target_revision = None if revision is None else _revision(revision)
        if bool(target_session) != (target_revision is not None):
            raise ValueError("panel target must provide both session and revision, or neither")
        value, value_session_id, value_revision = self._retained_value(target_session)
        return MeshPanelSnapshot(
            session_id=target_session,
            revision=target_revision,
            generation=self.generation + 1,
            status=MeshPanelStatus.UNAVAILABLE,
            value=value,
            value_session_id=value_session_id,
            value_revision=value_revision,
            message=str(message or "").strip(),
        )

    def publish_ready(self, value: PanelValueT) -> "MeshPanelSnapshot[PanelValueT]":
        if self.status is not MeshPanelStatus.PENDING:
            raise RuntimeError("only a pending panel request can publish a ready value")
        if value is None:
            raise ValueError("ready panel value must not be None")
        return MeshPanelSnapshot(
            session_id=self.session_id,
            revision=self.revision,
            generation=self.generation,
            status=MeshPanelStatus.READY,
            value=value,
            value_session_id=self.session_id,
            value_revision=self.revision,
        )

    def publish_error(
        self,
        *,
        error_code: str,
        message: str,
        unavailable: bool = False,
    ) -> "MeshPanelSnapshot[PanelValueT]":
        if self.status is not MeshPanelStatus.PENDING:
            raise RuntimeError("only a pending panel request can publish an error")
        normalized_code = str(error_code or "").strip()
        normalized_message = str(message or "").strip()
        if not normalized_code:
            raise ValueError("panel error code must not be empty")
        if not normalized_message:
            raise ValueError("panel error message must not be empty")
        return replace(
            self,
            status=MeshPanelStatus.UNAVAILABLE if unavailable else MeshPanelStatus.ERROR,
            error_code=normalized_code,
            message=normalized_message,
        )

    def replace_value(self, value: PanelValueT) -> "MeshPanelSnapshot[PanelValueT]":
        """Replace a selection overlay without changing geometry authority."""

        if self.value is None or value is None:
            raise RuntimeError("panel selection refresh requires a retained value")
        return replace(self, value=value)

    def matches_request(self, *, session_id: str, revision: int, generation: int) -> bool:
        return (
            self.session_id == str(session_id or "").strip()
            and self.revision == int(revision)
            and self.generation == int(generation)
        )

    def is_current(self, *, session_id: str, revision: int) -> bool:
        return (
            self.status is MeshPanelStatus.READY
            and self.session_id == str(session_id or "").strip()
            and self.revision == int(revision)
            and self.value_session_id == self.session_id
            and self.value_revision == self.revision
        )

    def _retained_value(
        self,
        target_session: str,
    ) -> tuple[PanelValueT | None, str, int | None]:
        if self.value is None or not target_session or self.value_session_id != target_session:
            return None, "", None
        return self.value, self.value_session_id, self.value_revision


def _session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("panel session id must not be empty")
    return normalized


def _revision(value: int) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError("panel revision must not be negative")
    return normalized
