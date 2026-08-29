"""Typed contracts for replacing one archive-owned mesh family with another."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cdmw.models import ArchiveEntry


class ReplaceFromArchiveCharacterMode(str, Enum):
    NOT_CHARACTER = "not_character"
    PRESERVE_TARGET = "preserve_target"
    BODY_HEAD_PATCH = "body_head_patch"
    FULL_SOURCE_IDENTITY = "full_source_identity"


class ReplaceFromArchiveActionKind(str, Enum):
    COPY = "copy"
    PATCH = "patch"
    REUSE = "reuse"


@dataclass(frozen=True, slots=True)
class ReplaceFromArchiveRequest:
    target_entry: ArchiveEntry
    source_entry: ArchiveEntry
    character_mode: ReplaceFromArchiveCharacterMode = (
        ReplaceFromArchiveCharacterMode.NOT_CHARACTER
    )


@dataclass(frozen=True, slots=True)
class ReplaceFromArchiveFileAction:
    role: str
    kind: ReplaceFromArchiveActionKind
    source_entry: ArchiveEntry | None
    target_entry: ArchiveEntry | None
    note: str = ""
    payload_data: bytes = b""

    @property
    def source_path(self) -> str:
        return str(getattr(self.source_entry, "path", "") or "")

    @property
    def target_path(self) -> str:
        return str(getattr(self.target_entry, "path", "") or "")


@dataclass(frozen=True, slots=True)
class ReplaceFromArchivePlan:
    request: ReplaceFromArchiveRequest
    actions: tuple[ReplaceFromArchiveFileAction, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def can_build(self) -> bool:
        return bool(self.actions) and not self.blockers

    @property
    def copied_actions(self) -> tuple[ReplaceFromArchiveFileAction, ...]:
        return tuple(
            action
            for action in self.actions
            if action.kind is not ReplaceFromArchiveActionKind.REUSE
        )


__all__ = [
    "ReplaceFromArchiveActionKind",
    "ReplaceFromArchiveCharacterMode",
    "ReplaceFromArchiveFileAction",
    "ReplaceFromArchivePlan",
    "ReplaceFromArchiveRequest",
]
