"""Typed protocol-v3 resident mutation values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def _mapping_tuple(values: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    return tuple(dict(value) for value in values)


@dataclass(frozen=True, slots=True)
class ResidentMutationBatch:
    """One service revision and every renderer change it authorizes."""

    session_id: str
    process_generation: int
    request_id: int
    base_revision: int
    target_revision: int
    action: str
    vertex_updates: tuple[dict[str, object], ...] = ()
    topology_update: dict[str, object] | None = None
    material_updates: tuple[dict[str, object], ...] = ()
    selection_update: dict[str, object] | None = None
    final_submesh_count: int | None = None
    affected_submesh_indices: tuple[int, ...] = ()
    temporary_payloads: tuple[dict[str, object], ...] = ()
    recovery_snapshot: bool = False

    def __post_init__(self) -> None:
        session_id = str(self.session_id or "").strip()
        if not session_id:
            raise ValueError("resident mutation batch requires session_id")
        if int(self.process_generation) <= 0:
            raise ValueError("resident mutation batch requires positive process_generation")
        if int(self.request_id) <= 0:
            raise ValueError("resident mutation batch requires positive request_id")
        if int(self.base_revision) < 0:
            raise ValueError("resident mutation batch base_revision cannot be negative")
        if int(self.target_revision) <= int(self.base_revision):
            raise ValueError("resident mutation batch target_revision must be newer than base_revision")
        if not str(self.action or "").strip():
            raise ValueError("resident mutation batch requires an action identity")
        if self.final_submesh_count is not None and int(self.final_submesh_count) < 0:
            raise ValueError("resident mutation batch final_submesh_count cannot be negative")
        affected = tuple(sorted({int(value) for value in self.affected_submesh_indices}))
        if any(value < 0 for value in affected):
            raise ValueError("resident mutation batch affected submeshes cannot be negative")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "process_generation", int(self.process_generation))
        object.__setattr__(self, "request_id", int(self.request_id))
        object.__setattr__(self, "base_revision", int(self.base_revision))
        object.__setattr__(self, "target_revision", int(self.target_revision))
        object.__setattr__(self, "action", str(self.action).strip())
        object.__setattr__(self, "vertex_updates", _mapping_tuple(self.vertex_updates))
        object.__setattr__(
            self,
            "topology_update",
            dict(self.topology_update) if self.topology_update is not None else None,
        )
        object.__setattr__(self, "material_updates", _mapping_tuple(self.material_updates))
        object.__setattr__(
            self,
            "selection_update",
            dict(self.selection_update) if self.selection_update is not None else None,
        )
        object.__setattr__(
            self,
            "final_submesh_count",
            int(self.final_submesh_count) if self.final_submesh_count is not None else None,
        )
        object.__setattr__(self, "affected_submesh_indices", affected)
        object.__setattr__(self, "temporary_payloads", _mapping_tuple(self.temporary_payloads))

    def as_protocol_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": "resident_mutation_batch",
            "session_id": self.session_id,
            "process_generation": self.process_generation,
            "request_id": self.request_id,
            "base_revision": self.base_revision,
            "target_revision": self.target_revision,
            "revision": self.target_revision,
            "edit_revision": self.target_revision,
            "protocol_version": 3,
            "action": self.action,
            "command": self.action,
            "vertex_updates": [dict(value) for value in self.vertex_updates],
            "material_updates": [dict(value) for value in self.material_updates],
            "affected_submesh_indices": list(self.affected_submesh_indices),
            "temporary_payloads": [dict(value) for value in self.temporary_payloads],
            "mutation_kind": "recovery_snapshot" if self.recovery_snapshot else "mutation",
            "recovery_snapshot": bool(self.recovery_snapshot),
        }
        if self.topology_update is not None:
            payload["topology_update"] = dict(self.topology_update)
        if self.selection_update is not None:
            payload["selection_update"] = dict(self.selection_update)
        if self.final_submesh_count is not None:
            payload["final_submesh_count"] = self.final_submesh_count
        return payload


__all__ = ["ResidentMutationBatch"]
