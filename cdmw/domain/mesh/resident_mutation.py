"""Typed protocol-v3 resident mutation values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import string

RESIDENT_INTERACTION_FORMAT_VERSION = 2
RESIDENT_INTERACTION_LEGACY_FORMAT_VERSION = 1
RESIDENT_INTERACTION_MAPPING_PREFIX = "Local\\CDMW.MeshInteraction."
RESIDENT_INTERACTION_MAX_BYTES = 128 * 1024 * 1024


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
    history_state: dict[str, object] | None = None
    final_submesh_count: int | None = None
    affected_submesh_indices: tuple[int, ...] = ()
    temporary_payloads: tuple[dict[str, object], ...] = ()
    recovery_snapshot: bool = False
    selection_revision: int = 0
    topology_generation: int = 0

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
            "history_state",
            dict(self.history_state) if self.history_state is not None else None,
        )
        object.__setattr__(
            self,
            "final_submesh_count",
            int(self.final_submesh_count) if self.final_submesh_count is not None else None,
        )
        object.__setattr__(self, "affected_submesh_indices", affected)
        object.__setattr__(self, "temporary_payloads", _mapping_tuple(self.temporary_payloads))
        object.__setattr__(self, "selection_revision", max(0, int(self.selection_revision)))
        object.__setattr__(self, "topology_generation", max(0, int(self.topology_generation)))

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
            "selection_revision": self.selection_revision,
            "topology_generation": self.topology_generation,
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
        if self.history_state is not None:
            payload["history_state"] = dict(self.history_state)
        if self.final_submesh_count is not None:
            payload["final_submesh_count"] = self.final_submesh_count
        return payload


__all__ = ["ResidentMutationBatch"]


_RESIDENT_INTERACTION_DESCRIPTOR_FIELDS = (
    "mapping_name",
    "length",
    "sha256",
    "session_id",
    "gesture_id",
    "transaction_sequence",
    "tool",
    "base_revision",
    "target_revision",
    "base_selection_revision",
    "target_selection_revision",
    "topology_generation",
    "request_id",
    "process_generation",
    "helper_process_id",
    "format_version",
)

def _resident_interaction_descriptor(payload: Mapping[str, object]) -> dict[str, object]:
    descriptor = {name: payload.get(name) for name in _RESIDENT_INTERACTION_DESCRIPTOR_FIELDS}
    mapping_name = str(descriptor["mapping_name"] or "")
    suffix = mapping_name.removeprefix(RESIDENT_INTERACTION_MAPPING_PREFIX)
    sha256 = str(descriptor["sha256"] or "")
    format_version = descriptor["format_version"]
    if type(format_version) is not int:
        raise ValueError("Invalid resident interaction transaction descriptor.")
    required_names = {
        "gesture_id",
        "base_revision",
        "base_selection_revision",
        "topology_generation",
        "format_version",
    }
    if int(format_version) == RESIDENT_INTERACTION_FORMAT_VERSION:
        required_names.update(
            {
                "transaction_sequence",
                "tool",
                "target_revision",
                "target_selection_revision",
                "request_id",
                "process_generation",
                "helper_process_id",
            }
        )
    if (
        not mapping_name.startswith(RESIDENT_INTERACTION_MAPPING_PREFIX)
        or len(suffix) != 32
        or any(character not in string.hexdigits for character in suffix)
        or len(sha256) != 64
        or any(character not in string.hexdigits for character in sha256)
        or not str(descriptor["session_id"] or "")
        or any(type(descriptor[name]) is not int for name in required_names)
        or type(descriptor["length"]) is not int
        or int(descriptor["length"] or 0) <= 0
        or int(descriptor["gesture_id"] or 0) <= 0
        or int(descriptor["format_version"] or 0) not in {
            RESIDENT_INTERACTION_LEGACY_FORMAT_VERSION,
            RESIDENT_INTERACTION_FORMAT_VERSION,
        }
        or (
            int(descriptor["format_version"] or 0) == RESIDENT_INTERACTION_FORMAT_VERSION
            and (
                int(descriptor["transaction_sequence"] or 0) <= 0
                or int(descriptor["request_id"] or 0) <= 0
                or int(descriptor["process_generation"] or 0) <= 0
                or int(descriptor["helper_process_id"] or 0) <= 0
            )
        )
    ):
        raise ValueError("Invalid resident interaction transaction descriptor.")
    descriptor["mapping_name"] = mapping_name
    descriptor["sha256"] = sha256.lower()
    descriptor["session_id"] = str(descriptor["session_id"])
    if int(format_version) == RESIDENT_INTERACTION_LEGACY_FORMAT_VERSION:
        descriptor = {
            name: descriptor[name]
            for name in (
                "mapping_name",
                "length",
                "sha256",
                "session_id",
                "gesture_id",
                "base_revision",
                "base_selection_revision",
                "topology_generation",
                "format_version",
            )
        }
    return descriptor
