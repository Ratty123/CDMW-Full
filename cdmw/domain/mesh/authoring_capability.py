"""What the Mesh Editor can author, keyed by format, LOD, and operation.

The limits themselves already exist and are enforced: the exact serializer
refuses what it cannot write byte for byte, and `export_validation` reports a
stable blocker code when a contract stops describing its own geometry. What did
not exist was a way to ask *before* editing. A reader discovered an unsupported
combination by doing the work and then being refused, and eleven topology
actions were simply hidden, which reads as "unfinished" rather than "blocked,
and here is why".

This module answers the question ahead of time. It is a description, not an
enforcement point: it neither writes nor validates anything, and it deliberately
carries no opinion the writer does not already hold. When the two could
disagree, the writer wins and this is stale -- so the reasons here name the
measured limit rather than restating a rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cdmw.domain.mesh.topology import (
    TOPOLOGY_OPERATION_DELETE_FACES,
    TOPOLOGY_OPERATION_LOOP_CUT,
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
)


class AuthoringSupport(str, Enum):
    """How well a combination is supported."""

    #: Proven: the exact writer produces the target bytes and round-trips.
    EXACT = "exact"
    #: Authorable, but through a generic rebuild rather than the exact writer.
    REBUILD = "rebuild"
    #: Possible in principle, unproven in practice; refused rather than guessed.
    UNPROVEN = "unproven"
    #: Cannot be authored at all for this combination.
    BLOCKED = "blocked"
    #: The format is readable but this build never writes it.
    READ_ONLY = "read_only"


AUTHORABLE_SUPPORT = frozenset({AuthoringSupport.EXACT, AuthoringSupport.REBUILD})


@dataclass(frozen=True, slots=True)
class AuthoringCapability:
    """One answer, with the reason a refusal has to carry."""

    support: AuthoringSupport
    reason: str = ""
    detail: str = ""

    @property
    def authorable(self) -> bool:
        return self.support in AUTHORABLE_SUPPORT

    def as_payload(self) -> dict[str, object]:
        return {
            "support": self.support.value,
            "authorable": bool(self.authorable),
            "reason": str(self.reason or ""),
            "detail": str(self.detail or ""),
        }


#: Formats this build can author geometry into, and the one it cannot.
AUTHORABLE_MESH_FORMATS = frozenset({"pac", "pam", "pamlod"})
READ_ONLY_MESH_FORMATS = frozenset({"meshinfo"})

#: The LOD the exact topology path is proven on.
PROVEN_AUTHORING_LOD = 0


def normalize_mesh_format(value: object) -> str:
    text = str(value or "").strip().lower().lstrip(".")
    return text


_UNSUPPORTED_FORMAT = AuthoringCapability(
    AuthoringSupport.BLOCKED,
    "Unsupported mesh format",
    "This build authors pac, pam, and pamlod geometry.",
)

_READ_ONLY_FORMAT = AuthoringCapability(
    AuthoringSupport.READ_ONLY,
    "This format is read-only",
    "The .meshinfo tables are not proven writable, so the editor opens them without an authoring path.",
)

_UNPROVEN_LOD = AuthoringCapability(
    AuthoringSupport.UNPROVEN,
    "LOD1 and above are not proven for authoring",
    "The exact topology path is proven on LOD0. Lower LODs are copied through unchanged.",
)

#: Topology operations, and what the exact PAC LOD0 writer can do with each.
#:
#: Face deletion derives no new vertices, so every surviving record is carried
#: through byte for byte and it is exact wherever the contract holds. Loop Cut
#: and midpoint Subdivide derive new vertices, and a derived record is only
#: admissible when every parent agrees on every protected byte -- measured at
#: 0.0072% of 151,927 unique LOD0 edges across twelve shipped PACs, so in
#: practice they are blocked on stock geometry rather than merely uncommon.
_TOPOLOGY_CAPABILITY: dict[str, AuthoringCapability] = {
    TOPOLOGY_OPERATION_DELETE_FACES: AuthoringCapability(AuthoringSupport.EXACT),
    TOPOLOGY_OPERATION_LOOP_CUT: AuthoringCapability(
        AuthoringSupport.UNPROVEN,
        "Loop Cut derives vertices whose protected bytes cannot be derived",
        "A derived vertex is admitted only where every parent agrees on every protected byte, "
        "which holds for 0.0072% of measured LOD0 edges.",
    ),
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT: AuthoringCapability(
        AuthoringSupport.UNPROVEN,
        "Midpoint Subdivide derives vertices whose protected bytes cannot be derived",
        "A derived vertex is admitted only where every parent agrees on every protected byte, "
        "which holds for 0.0072% of measured LOD0 edges.",
    ),
}

#: Native editor actions that change topology but have no exact-writer route at
#: all, with the reason each is unavailable. The UI hides these rather than
#: showing them disabled, which is a settled product decision rather than a
#: pending one -- see `_UNAUTHORABLE_TOPOLOGY_ACTION_KEYS` in
#: `cdmw/ui/mesh_editor/actions.py`. The reasons are kept current anyway: they
#: are what a capability panel or a diagnostics snapshot reads, and what a
#: future decision to surface them would use.
_UNIMPLEMENTED_TOPOLOGY_ACTIONS: dict[str, str] = {
    "edge_split": "Edge Split has no exact writeback route",
    "bridge": "Bridge has no exact writeback route",
    "extrude": "Extrude has no exact writeback route",
    "inset": "Inset has no exact writeback route",
    "merge": "Merge has no exact writeback route",
    "weld": "Weld has no exact writeback route",
    "fill": "Fill has no exact writeback route",
    "copy": "Copy has no exact writeback route",
    "paste": "Paste has no exact writeback route",
    "layer_delete": "Layer Delete has no exact writeback route",
}

_NO_EXACT_ROUTE_DETAIL = (
    "The operation changes topology in ways the exact PAC LOD0 serializer cannot express, "
    "and the generic rebuild would lose protected bytes."
)


def geometry_authoring_capability(
    mesh_format: object,
    *,
    lod_index: int = PROVEN_AUTHORING_LOD,
) -> AuthoringCapability:
    """Whether geometry can be authored into this format and LOD at all.

    Answers before the operation is chosen, because a format or LOD that cannot
    be written makes every operation moot.
    """

    normalized = normalize_mesh_format(mesh_format)
    if normalized in READ_ONLY_MESH_FORMATS:
        return _READ_ONLY_FORMAT
    if normalized not in AUTHORABLE_MESH_FORMATS:
        return _UNSUPPORTED_FORMAT
    if int(lod_index) != PROVEN_AUTHORING_LOD:
        return _UNPROVEN_LOD
    return AuthoringCapability(AuthoringSupport.EXACT)


def topology_authoring_capability(
    mesh_format: object,
    *,
    lod_index: int = PROVEN_AUTHORING_LOD,
    topology_operation: object = None,
) -> AuthoringCapability:
    """Whether a topology-changing operation can be authored exactly.

    ``topology_operation`` is the stable contract name, not the UI action key.
    Passing ``None`` asks about a geometry-only edit, which changes no topology
    and is answered by the format and LOD alone.
    """

    geometry = geometry_authoring_capability(mesh_format, lod_index=lod_index)
    if not geometry.authorable:
        return geometry
    if topology_operation is None:
        return geometry
    name = str(topology_operation or "").strip()
    capability = _TOPOLOGY_CAPABILITY.get(name)
    if capability is not None:
        return capability
    return AuthoringCapability(
        AuthoringSupport.BLOCKED,
        f"{name or 'This operation'} has no exact writeback route",
        _NO_EXACT_ROUTE_DETAIL,
    )


def action_authoring_capability(action_key: object) -> AuthoringCapability | None:
    """The capability for a native editor action, or ``None`` when unrestricted.

    ``None`` means the action carries no authoring limit of its own, not that it
    is always available: selection state and session state still gate it.
    """

    key = str(action_key or "").strip().lower()
    reason = _UNIMPLEMENTED_TOPOLOGY_ACTIONS.get(key)
    if reason is not None:
        return AuthoringCapability(AuthoringSupport.BLOCKED, reason, _NO_EXACT_ROUTE_DETAIL)
    from cdmw.domain.mesh.topology import TOPOLOGY_OPERATION_BY_NATIVE_ACTION

    operation = TOPOLOGY_OPERATION_BY_NATIVE_ACTION.get(key)
    if operation is None:
        return None
    capability = _TOPOLOGY_CAPABILITY.get(operation)
    return capability if capability is not None and not capability.authorable else None


def capability_matrix(mesh_format: object, *, lod_index: int = PROVEN_AUTHORING_LOD) -> dict[str, object]:
    """One structure a capability panel can render at session start."""

    geometry = geometry_authoring_capability(mesh_format, lod_index=lod_index)
    return {
        "format": normalize_mesh_format(mesh_format),
        "lod_index": int(lod_index),
        "geometry": geometry.as_payload(),
        "topology_operations": {
            operation: topology_authoring_capability(
                mesh_format,
                lod_index=lod_index,
                topology_operation=operation,
            ).as_payload()
            for operation in sorted(_TOPOLOGY_CAPABILITY)
        },
        "blocked_actions": {
            key: AuthoringCapability(
                AuthoringSupport.BLOCKED, reason, _NO_EXACT_ROUTE_DETAIL
            ).as_payload()
            for key, reason in sorted(_UNIMPLEMENTED_TOPOLOGY_ACTIONS.items())
        },
    }


__all__ = [
    "AUTHORABLE_MESH_FORMATS",
    "AUTHORABLE_SUPPORT",
    "PROVEN_AUTHORING_LOD",
    "READ_ONLY_MESH_FORMATS",
    "AuthoringCapability",
    "AuthoringSupport",
    "action_authoring_capability",
    "capability_matrix",
    "geometry_authoring_capability",
    "normalize_mesh_format",
    "topology_authoring_capability",
]
