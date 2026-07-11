"""Immutable attachment-patch result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(slots=True, frozen=True)
class PrefabSocketNameField:
    field_name: str
    value: str
    length_offset: int
    value_offset: int
    byte_length: int


@dataclass(slots=True, frozen=True)
class PrefabSocketNamePatchResult:
    data: bytes
    fields: Tuple[PrefabSocketNameField, ...]
    proof_lines: Tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PrefabAttachmentProfilePatchResult:
    data: bytes
    fields: Tuple[PrefabSocketNameField, ...]
    changed_fields: Tuple[PrefabSocketNameField, ...]
    proof_lines: Tuple[str, ...]


__all__ = [
    "PrefabAttachmentProfilePatchResult",
    "PrefabSocketNameField",
    "PrefabSocketNamePatchResult",
]
