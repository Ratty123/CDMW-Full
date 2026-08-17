"""Queued, correlated material publication for the resident Mesh Editor panes.

Material work used to be coordinated by a handful of independent pending
booleans and model slots around a single latest-wins compiler. Whether a pane
became textured therefore depended on resolver order, pane configuration,
launch timing, and which compile happened to be running when the next request
arrived. The failure that motivated this module is the worst version of that:
no path published an external import's own materials at all, so the request for
Solid (Textured) waited on an acknowledgement for ``editable_imported`` that
nothing was ever going to send.

This module owns the ordering rules and nothing else. It is deliberately free
of Qt and of the tab's state so the queue can be tested directly:

* one publication may be active at a time,
* newer work for a role supersedes that role's *queued* work,
* newer work never displaces *active* work without recording a cancellation,
* every result carries back the ``publish_id`` and generation tuple it was
  issued with, so a late answer from a replaced compile or a restarted
  renderer is recognised as stale instead of being applied,
* and the whole queue is inspectable for diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Iterator, Mapping


class MaterialRole(str, Enum):
    """The resident roles a publication can target."""

    EDITABLE_IMPORTED = "editable_imported"
    ORIGINAL_REFERENCE = "original_reference"


_ORIGINAL_ROLE_ALIASES = frozenset({"original", "reference", "original_reference"})


def normalize_material_role(role: object) -> str:
    """Map any spelling of a role onto its resident key.

    ``replacement`` is the historical name for the editable pane and still
    arrives from the protocol and from call sites that predate the roles, so
    anything that is not explicitly the reference pane resolves to the editable
    one -- the same rule the tab has always applied.
    """

    # `str(SomeStrEnum.MEMBER)` renders as "MaterialRole.MEMBER" from Python
    # 3.11, so the member's value has to be taken before any text handling.
    raw = role.value if isinstance(role, Enum) else role
    normalized = str(raw or "replacement").strip().lower().replace("-", "_")
    if normalized in _ORIGINAL_ROLE_ALIASES:
        return MaterialRole.ORIGINAL_REFERENCE.value
    return MaterialRole.EDITABLE_IMPORTED.value


def normalize_material_roles(roles: object) -> tuple[str, ...]:
    """Normalize one role or a sequence of them, preserving order without repeats."""

    if roles is None:
        return ()
    if isinstance(roles, (str, MaterialRole)):
        return (normalize_material_role(roles),)
    if not isinstance(roles, Iterable):
        return (normalize_material_role(roles),)
    ordered: list[str] = []
    for value in roles:
        key = normalize_material_role(value)
        if key not in ordered:
            ordered.append(key)
    return tuple(ordered)


class MaterialPublicationStatus(str, Enum):
    """Where a publication is in its life, including every way it can end.

    ``PUBLISHED`` is the stage that the old model had no name for. A compiled
    payload that has been handed to the renderer is not yet applied, and the
    pane is not textured until the correlated acknowledgement comes back. Left
    unnamed, "compile finished" got read as "pane ready" and a role that was
    still waiting looked identical to one that had settled.
    """

    QUEUED = "queued"
    ACTIVE = "active"
    PUBLISHED = "published"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    SUPERSEDED = "superseded"
    STALE = "stale"


TERMINAL_PUBLICATION_STATUSES = frozenset(
    {
        MaterialPublicationStatus.SUCCEEDED,
        MaterialPublicationStatus.FAILED,
        MaterialPublicationStatus.CANCELED,
        MaterialPublicationStatus.SUPERSEDED,
        MaterialPublicationStatus.STALE,
    }
)


@dataclass(frozen=True, slots=True)
class MaterialPublicationRequest:
    """One unit of material work, correlated well enough to be answered late.

    ``payload`` is opaque here: the coordinator never inspects it. The caller
    stores whatever it needs to actually perform the publish (a mesh snapshot,
    a preview model, the keyword arguments for the send) and gets it back when
    the request becomes active.
    """

    publish_id: int
    session_id: str
    process_generation: int
    package_generation: int
    roles: tuple[str, ...]
    reason: str = "changed"
    priority: int = 0
    signature: str = ""
    geometry_generation: int = 0
    material_generation: int = 0
    payload: object = None

    @property
    def role(self) -> str:
        """The primary role, which is the one status and errors are reported against."""

        return self.roles[0] if self.roles else MaterialRole.EDITABLE_IMPORTED.value

    def generation_token(self) -> tuple[int, int]:
        """The process and package pair a result has to still match to be applied."""

        return (int(self.process_generation), int(self.package_generation))

    def covers_role(self, role: object) -> bool:
        return normalize_material_role(role) in self.roles


@dataclass(frozen=True, slots=True)
class MaterialPublicationResult:
    """The outcome of a request, carrying back everything needed to correlate it."""

    publish_id: int
    roles: tuple[str, ...]
    status: MaterialPublicationStatus
    reason: str = ""
    detail: str = ""
    material_generation: int = 0
    session_id: str = ""
    process_generation: int = 0
    package_generation: int = 0

    @property
    def role(self) -> str:
        return self.roles[0] if self.roles else MaterialRole.EDITABLE_IMPORTED.value

    @property
    def succeeded(self) -> bool:
        return self.status is MaterialPublicationStatus.SUCCEEDED

    def as_event_payload(self) -> dict[str, object]:
        return {
            "publish_id": int(self.publish_id),
            "roles": tuple(self.roles),
            "role": self.role,
            "status": self.status.value,
            "reason": str(self.reason or ""),
            "detail": str(self.detail or ""),
            "material_generation": int(self.material_generation),
            "session_id": str(self.session_id or ""),
            "process_generation": int(self.process_generation),
            "package_generation": int(self.package_generation),
        }


@dataclass(slots=True)
class _HistoryEntry:
    publish_id: int
    roles: tuple[str, ...]
    reason: str
    status: MaterialPublicationStatus
    detail: str = ""

    def as_payload(self) -> dict[str, object]:
        return {
            "publish_id": int(self.publish_id),
            "roles": tuple(self.roles),
            "reason": str(self.reason or ""),
            "status": self.status.value,
            "detail": str(self.detail or ""),
        }


# Diagnostics are read after a failure, not streamed, so the history only has to
# be long enough to show how the queue got into its current shape.
_HISTORY_LIMIT = 32


class MaterialPublicationCoordinator:
    """Order material publications explicitly instead of by callback accident.

    The coordinator never performs a publish. It decides which request is next,
    which results still matter, and what diagnostics should say; the caller owns
    the compiler, the protocol, and the Qt objects.
    """

    def __init__(self) -> None:
        self._next_publish_id = 0
        self._active: MaterialPublicationRequest | None = None
        self._queued: list[MaterialPublicationRequest] = []
        self._awaiting_ack: dict[int, MaterialPublicationRequest] = {}
        self._history: list[_HistoryEntry] = []
        self._results_by_role: dict[str, MaterialPublicationResult] = {}
        self._counts: dict[str, int] = {
            "enqueued": 0,
            "coalesced": 0,
            "superseded": 0,
            "canceled": 0,
            "started": 0,
            "published": 0,
            "succeeded": 0,
            "failed": 0,
            "stale_results": 0,
        }

    # -- construction ---------------------------------------------------

    def build_request(
        self,
        *,
        session_id: str,
        process_generation: int,
        package_generation: int = 0,
        roles: object = MaterialRole.EDITABLE_IMPORTED,
        reason: str = "changed",
        priority: int = 0,
        signature: str = "",
        geometry_generation: int = 0,
        material_generation: int = 0,
        publish_id: int | None = None,
        payload: object = None,
    ) -> MaterialPublicationRequest:
        """Mint a request. Enqueueing it is a separate step.

        ``publish_id`` can be supplied by a caller that already owns a
        monotonic correlation key -- the Mesh Editor tab passes its material
        generation, which is what the compile request and the resident
        acknowledgement already travel with, so one number identifies the
        publication end to end instead of two that have to be kept in step.
        """

        if publish_id is None:
            self._next_publish_id += 1
            identifier = self._next_publish_id
        else:
            identifier = int(publish_id)
            self._next_publish_id = max(self._next_publish_id, identifier)
        normalized_roles = normalize_material_roles(roles) or (
            MaterialRole.EDITABLE_IMPORTED.value,
        )
        return MaterialPublicationRequest(
            publish_id=identifier,
            session_id=str(session_id or ""),
            process_generation=int(process_generation),
            package_generation=int(package_generation),
            roles=normalized_roles,
            reason=str(reason or "changed"),
            priority=int(priority),
            signature=str(signature or ""),
            geometry_generation=int(geometry_generation),
            material_generation=int(material_generation or identifier),
            payload=payload,
        )

    # -- queue ----------------------------------------------------------

    def enqueue(
        self,
        request: MaterialPublicationRequest,
    ) -> tuple[MaterialPublicationRequest, tuple[MaterialPublicationResult, ...]]:
        """Queue work, returning it with the results of anything it displaced.

        Identical work for a role that is already queued is coalesced rather
        than queued twice, which is what stops a reader clicking Solid
        (Textured) repeatedly from starting a compile per click. Newer work for
        a role supersedes that role's older *queued* entries; the active request
        is never touched here.
        """

        self._counts["enqueued"] += 1
        existing_index = self._find_coalescable(request)
        if existing_index is not None:
            # The work is identical, so it stays one queue entry -- clicking
            # Solid (Textured) four times must not compile four times. The entry
            # takes the newcomer's identity rather than the newcomer being
            # dropped: the caller's correlation key has already moved on, and a
            # queued entry still carrying the older one would be rejected as
            # stale when it finally compiled.
            existing = self._queued[existing_index]
            self._queued[existing_index] = request
            self._counts["coalesced"] += 1
            self._remember(
                request.publish_id,
                request.roles,
                request.reason,
                MaterialPublicationStatus.QUEUED,
                f"coalesced with publish {existing.publish_id}",
            )
            return request, ()
        superseded: list[MaterialPublicationResult] = []
        remaining: list[MaterialPublicationRequest] = []
        for queued in self._queued:
            if queued.priority <= request.priority and set(queued.roles) <= set(request.roles):
                superseded.append(
                    self._finish(
                        queued,
                        MaterialPublicationStatus.SUPERSEDED,
                        reason=request.reason,
                        detail=f"superseded by publish {request.publish_id}",
                    )
                )
                continue
            remaining.append(queued)
        remaining.append(request)
        remaining.sort(key=lambda item: (item.priority, item.publish_id))
        self._queued = remaining
        self._remember(request.publish_id, request.roles, request.reason, MaterialPublicationStatus.QUEUED)
        return request, tuple(superseded)

    def _find_coalescable(self, request: MaterialPublicationRequest) -> int | None:
        if not request.signature:
            return None
        for index, queued in enumerate(self._queued):
            if (
                queued.roles == request.roles
                and queued.signature == request.signature
                and queued.generation_token() == request.generation_token()
                and queued.session_id == request.session_id
            ):
                return index
        return None

    def begin_next(self, *, material_generation: int = 0) -> MaterialPublicationRequest | None:
        """Promote the head of the queue, if nothing is running yet.

        The material generation is stamped on here rather than at enqueue time
        because it is the compiler's counter: a request that waited behind two
        others must not claim the number it would have had when it was queued.
        """

        if self._active is not None or not self._queued:
            return None
        request = self._queued.pop(0)
        if material_generation:
            request = replace(request, material_generation=int(material_generation))
        self._active = request
        self._counts["started"] += 1
        self._remember(request.publish_id, request.roles, request.reason, MaterialPublicationStatus.ACTIVE)
        return request

    def cancel_active(self, *, reason: str, detail: str = "") -> MaterialPublicationResult | None:
        """Stop the running publication and say so.

        Displacing active work is allowed only through here, because the point
        of the rule is that it leaves a record. A silently replaced compile is
        indistinguishable from one that never answered.
        """

        request = self._active
        if request is None:
            return None
        self._active = None
        self._counts["canceled"] += 1
        return self._finish(
            request,
            MaterialPublicationStatus.CANCELED,
            reason=reason,
            detail=detail,
        )

    def complete_active(
        self,
        publish_id: int,
        *,
        status: MaterialPublicationStatus = MaterialPublicationStatus.SUCCEEDED,
        reason: str = "",
        detail: str = "",
    ) -> MaterialPublicationResult | None:
        """Settle the active publication, ignoring an answer that is not its own."""

        request = self._active
        if request is None or int(publish_id) != int(request.publish_id):
            self._counts["stale_results"] += 1
            return None
        self._active = None
        if status is MaterialPublicationStatus.SUCCEEDED:
            self._counts["succeeded"] += 1
        elif status is MaterialPublicationStatus.FAILED:
            self._counts["failed"] += 1
        return self._finish(request, status, reason=reason, detail=detail)

    def publish_active(
        self,
        publish_id: int,
        *,
        detail: str = "",
    ) -> MaterialPublicationResult | None:
        """Hand the active publication's compiled payload to the renderer.

        This frees the compiler for the next request while keeping the role
        outstanding: the pane is not textured until the acknowledgement arrives,
        so ``pending_roles`` still reports it.
        """

        request = self._active
        if request is None or int(publish_id) != int(request.publish_id):
            self._counts["stale_results"] += 1
            return None
        self._active = None
        self._awaiting_ack[int(request.publish_id)] = request
        self._counts["published"] += 1
        return self._finish(
            request,
            MaterialPublicationStatus.PUBLISHED,
            detail=detail,
        )

    def acknowledge(
        self,
        publish_id: object,
        *,
        status: MaterialPublicationStatus = MaterialPublicationStatus.SUCCEEDED,
        reason: str = "",
        detail: str = "",
    ) -> MaterialPublicationResult | None:
        """Settle a published request from the resident acknowledgement.

        An acknowledgement for anything the coordinator is not waiting on is a
        late answer from a replaced compile or a retired renderer generation. It
        is recorded and discarded rather than allowed to mark a role ready.
        """

        try:
            identifier = int(publish_id)
        except (TypeError, ValueError, OverflowError):
            identifier = 0
        request = self._awaiting_ack.pop(identifier, None)
        if request is None:
            self.note_stale_result(identifier, detail=detail or "unmatched acknowledgement")
            return None
        if status is MaterialPublicationStatus.SUCCEEDED:
            self._counts["succeeded"] += 1
        elif status is MaterialPublicationStatus.FAILED:
            self._counts["failed"] += 1
        return self._finish(request, status, reason=reason, detail=detail)

    def is_awaiting_acknowledgement(self, publish_id: object) -> bool:
        try:
            return int(publish_id) in self._awaiting_ack
        except (TypeError, ValueError, OverflowError):
            return False

    def cancel_all(self, *, reason: str, detail: str = "") -> tuple[MaterialPublicationResult, ...]:
        """Drop everything, active first, for a session close or model replacement."""

        results: list[MaterialPublicationResult] = []
        active = self.cancel_active(reason=reason, detail=detail)
        if active is not None:
            results.append(active)
        queued, self._queued = self._queued, []
        awaiting, self._awaiting_ack = tuple(self._awaiting_ack.values()), {}
        for request in (*queued, *awaiting):
            self._counts["canceled"] += 1
            results.append(
                self._finish(
                    request,
                    MaterialPublicationStatus.CANCELED,
                    reason=reason,
                    detail=detail,
                )
            )
        return tuple(results)

    def invalidate_generations(
        self,
        *,
        session_id: str | None = None,
        process_generation: int | None = None,
        package_generation: int | None = None,
        reason: str = "generation_invalidated",
    ) -> tuple[MaterialPublicationResult, ...]:
        """Retire work that belongs to a generation the session has moved past.

        A renderer restart bumps the process generation and a new resident
        package bumps the package one. Anything still carrying the old token can
        never be acknowledged, so it is retired here rather than left to time
        out.
        """

        def outdated(request: MaterialPublicationRequest) -> bool:
            if session_id is not None and request.session_id != str(session_id or ""):
                return True
            if (
                process_generation is not None
                and int(request.process_generation) != int(process_generation)
            ):
                return True
            if (
                package_generation is not None
                and int(request.package_generation) > 0
                and int(request.package_generation) != int(package_generation)
            ):
                return True
            return False

        results: list[MaterialPublicationResult] = []
        if self._active is not None and outdated(self._active):
            request, self._active = self._active, None
            self._counts["canceled"] += 1
            results.append(
                self._finish(
                    request,
                    MaterialPublicationStatus.STALE,
                    reason=reason,
                    detail="active publication belonged to a retired generation",
                )
            )
        remaining: list[MaterialPublicationRequest] = []
        for request in self._queued:
            if outdated(request):
                self._counts["canceled"] += 1
                results.append(
                    self._finish(
                        request,
                        MaterialPublicationStatus.STALE,
                        reason=reason,
                        detail="queued publication belonged to a retired generation",
                    )
                )
                continue
            remaining.append(request)
        self._queued = remaining
        for identifier, request in tuple(self._awaiting_ack.items()):
            if not outdated(request):
                continue
            del self._awaiting_ack[identifier]
            self._counts["canceled"] += 1
            results.append(
                self._finish(
                    request,
                    MaterialPublicationStatus.STALE,
                    reason=reason,
                    detail="acknowledgement can no longer arrive for this generation",
                )
            )
        return tuple(results)

    # -- correlation ----------------------------------------------------

    def is_current(
        self,
        publish_id: object,
        *,
        session_id: str | None = None,
        process_generation: int | None = None,
        package_generation: int | None = None,
    ) -> bool:
        """Whether a returning answer still describes the running publication."""

        request = self._active
        if request is None:
            return False
        try:
            if int(publish_id) != int(request.publish_id):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
        if session_id is not None and str(session_id or "") != request.session_id:
            return False
        if (
            process_generation is not None
            and int(process_generation) != int(request.process_generation)
        ):
            return False
        if (
            package_generation is not None
            and int(package_generation) > 0
            and int(request.package_generation) > 0
            and int(package_generation) != int(request.package_generation)
        ):
            return False
        return True

    def note_stale_result(
        self,
        publish_id: object,
        *,
        detail: str = "",
    ) -> None:
        """Record that an answer arrived for work that is no longer current."""

        self._counts["stale_results"] += 1
        try:
            identifier = int(publish_id)
        except (TypeError, ValueError, OverflowError):
            identifier = 0
        self._remember(
            identifier,
            (),
            "stale_result",
            MaterialPublicationStatus.STALE,
            detail,
        )

    # -- inspection -----------------------------------------------------

    @property
    def active(self) -> MaterialPublicationRequest | None:
        return self._active

    @property
    def queued(self) -> tuple[MaterialPublicationRequest, ...]:
        return tuple(self._queued)

    @property
    def awaiting_acknowledgement(self) -> tuple[MaterialPublicationRequest, ...]:
        return tuple(self._awaiting_ack.values())

    def has_work(self) -> bool:
        return self._active is not None or bool(self._queued) or bool(self._awaiting_ack)

    def has_compile_work(self) -> bool:
        """Work that still needs the compiler, excluding anything awaiting an ack.

        Callers that drain before export want this one. An acknowledgement can
        be lost -- a retired package generation is rejected by the protocol
        guard before it reaches the coordinator -- so waiting on the ack stage
        would burn the whole timeout for something the compiler already finished.
        """

        return self._active is not None or bool(self._queued)

    def is_busy(self) -> bool:
        """Whether the single compiler slot is occupied. Awaiting an ack does not occupy it."""

        return self._active is not None

    def pending_roles(self) -> tuple[str, ...]:
        """Every role with work outstanding, active or queued, in role order."""

        roles: list[str] = []
        for request in self._iter_outstanding():
            for role in request.roles:
                if role not in roles:
                    roles.append(role)
        return tuple(roles)

    def has_pending_role(self, role: object) -> bool:
        key = normalize_material_role(role)
        return any(request.covers_role(key) for request in self._iter_outstanding())

    def last_result_for_role(self, role: object) -> MaterialPublicationResult | None:
        return self._results_by_role.get(normalize_material_role(role))

    def _iter_outstanding(self) -> Iterator[MaterialPublicationRequest]:
        if self._active is not None:
            yield self._active
        yield from self._queued
        yield from self._awaiting_ack.values()

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def snapshot(self) -> dict[str, object]:
        """One structure a diagnostics panel or an event payload can render."""

        return {
            "active": _describe(self._active),
            "queued": tuple(_describe(request) for request in self._queued),
            "awaiting_acknowledgement": tuple(
                _describe(request) for request in self._awaiting_ack.values()
            ),
            "pending_roles": self.pending_roles(),
            "results_by_role": {
                role: result.as_event_payload()
                for role, result in sorted(self._results_by_role.items())
            },
            "counts": self.counts(),
            "history": tuple(entry.as_payload() for entry in self._history),
        }

    # -- internals ------------------------------------------------------

    def _finish(
        self,
        request: MaterialPublicationRequest,
        status: MaterialPublicationStatus,
        *,
        reason: str = "",
        detail: str = "",
    ) -> MaterialPublicationResult:
        result = MaterialPublicationResult(
            publish_id=request.publish_id,
            roles=request.roles,
            status=status,
            reason=str(reason or request.reason or ""),
            detail=str(detail or ""),
            material_generation=int(request.material_generation),
            session_id=request.session_id,
            process_generation=int(request.process_generation),
            package_generation=int(request.package_generation),
        )
        for role in request.roles:
            self._results_by_role[role] = result
        self._remember(request.publish_id, request.roles, result.reason, status, detail)
        return result

    def _remember(
        self,
        publish_id: int,
        roles: tuple[str, ...],
        reason: str,
        status: MaterialPublicationStatus,
        detail: str = "",
    ) -> None:
        self._history.append(
            _HistoryEntry(
                publish_id=int(publish_id),
                roles=tuple(roles),
                reason=str(reason or ""),
                status=status,
                detail=str(detail or ""),
            )
        )
        if len(self._history) > _HISTORY_LIMIT:
            del self._history[: len(self._history) - _HISTORY_LIMIT]


def _describe(request: MaterialPublicationRequest | None) -> Mapping[str, object] | None:
    if request is None:
        return None
    return {
        "publish_id": int(request.publish_id),
        "roles": tuple(request.roles),
        "reason": str(request.reason or ""),
        "priority": int(request.priority),
        "signature": str(request.signature or ""),
        "session_id": str(request.session_id or ""),
        "process_generation": int(request.process_generation),
        "package_generation": int(request.package_generation),
        "geometry_generation": int(request.geometry_generation),
        "material_generation": int(request.material_generation),
    }


__all__ = [
    "MaterialPublicationCoordinator",
    "MaterialPublicationRequest",
    "MaterialPublicationResult",
    "MaterialPublicationStatus",
    "MaterialRole",
    "TERMINAL_PUBLICATION_STATUSES",
    "normalize_material_role",
    "normalize_material_roles",
]
