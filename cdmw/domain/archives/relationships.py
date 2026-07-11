"""Immutable archive relationship contracts and policy names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from cdmw.models import ArchiveEntry


ARCHIVE_REL_INCLUDE_REQUIRED = "required"
ARCHIVE_REL_INCLUDE_RECOMMENDED = "recommended"
ARCHIVE_REL_INCLUDE_MANUAL = "manual"
ARCHIVE_REL_INCLUDE_RISKY = "risky"
ARCHIVE_REL_INCLUDE_UNRESOLVED = "unresolved"

SWAP_SCOPE_BODY_ONLY = "body_only"
SWAP_SCOPE_BODY_HEAD = "body_head"
SWAP_SCOPE_FULL_APPEARANCE_REDIRECT = "full_appearance_redirect"


@dataclass(frozen=True, slots=True)
class ArchiveRelationEdge:
    source_path: str
    related_path: str = ""
    related_entry: Optional[ArchiveEntry] = None
    relation_kind: str = ""
    role: str = ""
    confidence: str = "heuristic"
    reason: str = ""
    include_policy: str = ARCHIVE_REL_INCLUDE_MANUAL
    risk: bool = False
    suggested_target_path: str = ""
    unresolved: bool = False
    source_table: str = ""
    source_field: str = ""


@dataclass(frozen=True, slots=True)
class ArchiveRelationshipPlan:
    source_path: str
    mode: str = "inspect"
    edges: Tuple[ArchiveRelationEdge, ...] = ()
    warnings: Tuple[str, ...] = ()
    swap_scope: str = ""
    patched_target_app_xml: bytes = b""
    patched_target_app_path: str = ""


@dataclass(frozen=True, slots=True)
class CharacterDependencyPlan:
    body_path: str
    selected_appearance_path: str = ""
    appearance_paths: Tuple[str, ...] = ()
    entries: Tuple[ArchiveEntry, ...] = ()
    edges: Tuple[ArchiveRelationEdge, ...] = ()
    warnings: Tuple[str, ...] = ()
    blocking_errors: Tuple[str, ...] = ()


__all__ = [
    "ARCHIVE_REL_INCLUDE_MANUAL",
    "ARCHIVE_REL_INCLUDE_RECOMMENDED",
    "ARCHIVE_REL_INCLUDE_REQUIRED",
    "ARCHIVE_REL_INCLUDE_RISKY",
    "ARCHIVE_REL_INCLUDE_UNRESOLVED",
    "SWAP_SCOPE_BODY_HEAD",
    "SWAP_SCOPE_BODY_ONLY",
    "SWAP_SCOPE_FULL_APPEARANCE_REDIRECT",
    "ArchiveRelationEdge",
    "ArchiveRelationshipPlan",
    "CharacterDependencyPlan",
]
