"""Frozen public catalogue contracts shared by the shell, services, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .catalogue_wire import (
    ArchiveContractError,
    read_bool,
    read_enum,
    read_int,
    read_optional_int,
    read_string,
    read_string_tuple,
    require_mapping,
    require_sequence,
)


class ArchiveEntryRole(str, Enum):
    OTHER = "other"
    MODEL = "model"
    ANIMATION = "animation"
    PHYSICS = "physics"
    METADATA = "metadata"
    VIDEO = "video"
    AUDIO = "audio"
    USER_INTERFACE = "user_interface"
    IMPOSTOR = "impostor"
    NORMAL = "normal"
    MATERIAL = "material"
    IMAGE = "image"
    TEXT = "text"


class ArchiveViewMode(str, Enum):
    FOLDERS = "folders"
    CATEGORIES = "categories"
    CATEGORIES_AND_FOLDERS = "categories_and_folders"
    FLAT = "flat"


class ArchiveSortField(str, Enum):
    PATH = "path"
    NAME = "name"
    KNOWN_NAME = "known_name"
    NAME_EVIDENCE = "name_evidence"
    EXTENSION = "extension"
    PACKAGE = "package"
    ORIGINAL_SIZE = "original_size"
    STORED_SIZE = "stored_size"
    COMPRESSION = "compression"
    ROLE = "role"
    CATEGORY = "category"
    ACTIVE_OVERRIDE = "active_override"


class ArchiveLookupKind(str, Enum):
    ENTRY_IDS = "entry_ids"
    IDENTITIES = "identities"
    EXACT_PATHS = "exact_paths"
    BASENAMES = "basenames"
    EXTENSIONS = "extensions"
    ROLES = "roles"


@dataclass(frozen=True, slots=True)
class ArchiveDurableIdentity:
    normalized_path: str
    source_pamt: str
    paz_index: int
    archive_offset: int

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveDurableIdentity":
        payload = require_mapping(value, "archive identity")
        return cls(
            normalized_path=read_string(payload, "normalized_path"),
            source_pamt=read_string(payload, "source_pamt"),
            paz_index=read_int(payload, "paz_index"),
            archive_offset=read_int(payload, "archive_offset"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveSessionHandle:
    session_id: str
    package_root: str
    fingerprint: str
    entry_count: int
    index_version: int
    cache_hit: bool

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveSessionHandle":
        payload = require_mapping(value, "archive session handle")
        return cls(
            session_id=read_string(payload, "session_id"),
            package_root=read_string(payload, "package_root"),
            fingerprint=read_string(payload, "fingerprint"),
            entry_count=read_int(payload, "entry_count"),
            index_version=read_int(payload, "index_version"),
            cache_hit=read_bool(payload, "cache_hit"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveEntryRef:
    session_id: str
    entry_id: int
    identity: ArchiveDurableIdentity
    display_path: str

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveEntryRef":
        payload = require_mapping(value, "archive entry reference")
        return cls(
            session_id=read_string(payload, "session_id"),
            entry_id=read_int(payload, "entry_id"),
            identity=ArchiveDurableIdentity.from_wire(payload.get("identity")),
            display_path=read_string(payload, "display_path"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveEntryDto:
    session_id: str
    entry_id: int
    identity: ArchiveDurableIdentity
    path: str
    source_pamt: str
    paz_file: str
    paz_index: int
    offset: int
    stored_size: int
    original_size: int
    flags: int
    extension: str
    package: str
    role: ArchiveEntryRole
    category: str
    is_previewable: bool
    known_name: str = ""
    exact_name: str = ""
    name_evidence: str = ""
    is_active_override: bool = False

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveEntryDto":
        payload = require_mapping(value, "archive entry")
        return cls(
            session_id=read_string(payload, "session_id"),
            entry_id=read_int(payload, "entry_id"),
            identity=ArchiveDurableIdentity.from_wire(payload.get("identity")),
            path=read_string(payload, "path"),
            source_pamt=read_string(payload, "source_pamt"),
            paz_file=read_string(payload, "paz_file"),
            paz_index=read_int(payload, "paz_index"),
            offset=read_int(payload, "offset"),
            stored_size=read_int(payload, "stored_size"),
            original_size=read_int(payload, "original_size"),
            flags=read_int(payload, "flags"),
            extension=read_string(payload, "extension"),
            package=read_string(payload, "package"),
            role=read_enum(payload, "role", ArchiveEntryRole),
            category=read_string(payload, "category"),
            is_previewable=read_bool(payload, "is_previewable"),
            known_name=read_string(payload, "known_name", default=""),
            exact_name=read_string(payload, "exact_name", default=""),
            name_evidence=read_string(payload, "name_evidence", default=""),
            is_active_override=read_bool(payload, "is_active_override", default=False),
        )


@dataclass(frozen=True, slots=True)
class ArchiveQuery:
    session_id: str
    include_text: str | None = None
    exclude_text: str | None = None
    extensions: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    folder: str | None = None
    roles: tuple[ArchiveEntryRole, ...] = ()
    technical_suffixes: tuple[str, ...] = ()
    minimum_size: int | None = None
    previewable_only: bool = False
    active_overrides_only: bool = False
    view_mode: ArchiveViewMode = ArchiveViewMode.FLAT
    sort_field: ArchiveSortField = ArchiveSortField.PATH
    sort_descending: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveQueryHandle:
    session_id: str
    query_id: str
    generation: int
    total_matches: int

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveQueryHandle":
        payload = require_mapping(value, "archive query handle")
        return cls(
            session_id=read_string(payload, "session_id"),
            query_id=read_string(payload, "query_id"),
            generation=read_int(payload, "generation"),
            total_matches=read_int(payload, "total_matches"),
        )


@dataclass(frozen=True, slots=True)
class ArchivePage:
    session_id: str
    query_id: str
    generation: int
    total_matches: int
    page_start: int
    rows: tuple[ArchiveEntryDto, ...]

    @classmethod
    def from_wire(cls, value: object) -> "ArchivePage":
        payload = require_mapping(value, "archive page")
        rows = require_sequence(payload.get("rows"), "rows")
        return cls(
            session_id=read_string(payload, "session_id"),
            query_id=read_string(payload, "query_id"),
            generation=read_int(payload, "generation"),
            total_matches=read_int(payload, "total_matches"),
            page_start=read_int(payload, "page_start"),
            rows=tuple(ArchiveEntryDto.from_wire(row) for row in rows),
        )


@dataclass(frozen=True, slots=True)
class ArchiveChildrenRequest:
    query_id: str
    parent_path: str | None = None
    category: str | None = None
    limit: int = 512
    offset: int = 0

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("offset must not be negative.")
        if not 1 <= self.limit <= 512:
            raise ValueError("limit must be between 1 and 512.")


@dataclass(frozen=True, slots=True)
class ArchiveChildNode:
    key: str
    label: str
    is_folder: bool
    match_count: int
    entry: ArchiveEntryDto | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveChildNode":
        payload = require_mapping(value, "archive child")
        raw_entry = payload.get("entry")
        return cls(
            key=read_string(payload, "key"),
            label=read_string(payload, "label"),
            is_folder=read_bool(payload, "is_folder"),
            match_count=read_int(payload, "match_count"),
            entry=None if raw_entry is None else ArchiveEntryDto.from_wire(raw_entry),
        )


@dataclass(frozen=True, slots=True)
class ArchiveChildrenResult:
    session_id: str
    query_id: str
    children: tuple[ArchiveChildNode, ...]
    truncated: bool
    offset: int = 0
    total_children: int = 0
    next_offset: int | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveChildrenResult":
        payload = require_mapping(value, "archive children result")
        children = require_sequence(payload.get("children"), "children")
        offset = read_int(payload, "offset", default=0)
        truncated = read_bool(payload, "truncated")
        next_offset = read_optional_int(payload, "next_offset")
        if truncated and next_offset is None:
            next_offset = offset + len(children)
        return cls(
            session_id=read_string(payload, "session_id"),
            query_id=read_string(payload, "query_id"),
            children=tuple(ArchiveChildNode.from_wire(child) for child in children),
            truncated=truncated,
            offset=offset,
            total_children=read_int(payload, "total_children", default=len(children)),
            next_offset=next_offset,
        )


@dataclass(frozen=True, slots=True)
class ArchiveFacet:
    key: str
    label: str
    count: int

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveFacet":
        payload = require_mapping(value, "archive facet")
        return cls(read_string(payload, "key"), read_string(payload, "label"), read_int(payload, "count"))


@dataclass(frozen=True, slots=True)
class ArchiveFacetsResult:
    session_id: str
    extensions: tuple[ArchiveFacet, ...]
    packages: tuple[ArchiveFacet, ...]
    roles: tuple[ArchiveFacet, ...]
    categories: tuple[ArchiveFacet, ...]

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveFacetsResult":
        payload = require_mapping(value, "archive facets result")

        def facets(key: str) -> tuple[ArchiveFacet, ...]:
            return tuple(ArchiveFacet.from_wire(item) for item in require_sequence(payload.get(key), key))

        return cls(
            session_id=read_string(payload, "session_id"),
            extensions=facets("extensions"),
            packages=facets("packages"),
            roles=facets("roles"),
            categories=facets("categories"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveLookupRequest:
    session_id: str
    kind: ArchiveLookupKind
    entry_ids: tuple[int, ...] = ()
    identities: tuple[ArchiveDurableIdentity, ...] = ()
    values: tuple[str, ...] = ()
    roles: tuple[ArchiveEntryRole, ...] = ()
    limit: int = 512
    query_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveLookupResult:
    session_id: str
    entries: tuple[ArchiveEntryDto, ...]
    total_matches: int
    truncated: bool
    query_rows: tuple[int, ...] = ()

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveLookupResult":
        payload = require_mapping(value, "archive lookup result")
        entries = require_sequence(payload.get("entries"), "entries")
        raw_query_rows = require_sequence(payload.get("query_rows", ()), "query_rows")
        if any(isinstance(row, bool) or not isinstance(row, int) for row in raw_query_rows):
            raise ArchiveContractError("query_rows must contain only integers.")
        return cls(
            session_id=read_string(payload, "session_id"),
            entries=tuple(ArchiveEntryDto.from_wire(entry) for entry in entries),
            total_matches=read_int(payload, "total_matches"),
            truncated=read_bool(payload, "truncated"),
            query_rows=tuple(raw_query_rows),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ArchiveAssociationRequest:
    session_id: str
    entry_id: int
    limit: int = 256


@dataclass(frozen=True, slots=True)
class ArchiveAssociationResult:
    session_id: str
    entry_id: int
    candidates: tuple[ArchiveEntryDto, ...]
    total_candidates: int
    truncated: bool

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveAssociationResult":
        payload = require_mapping(value, "archive association result")
        candidates = require_sequence(payload.get("candidates"), "candidates")
        return cls(
            session_id=read_string(payload, "session_id"),
            entry_id=read_int(payload, "entry_id"),
            candidates=tuple(ArchiveEntryDto.from_wire(entry) for entry in candidates),
            total_candidates=read_int(payload, "total_candidates"),
            truncated=read_bool(payload, "truncated"),
        )


def archive_query_from_wire(value: object) -> ArchiveQuery:
    payload = require_mapping(value, "archive query")
    raw_roles = require_sequence(payload.get("roles", ()), "roles")
    return ArchiveQuery(
        session_id=read_string(payload, "session_id"),
        include_text=payload.get("include_text") if isinstance(payload.get("include_text"), str) else None,
        exclude_text=payload.get("exclude_text") if isinstance(payload.get("exclude_text"), str) else None,
        extensions=read_string_tuple(payload, "extensions"),
        packages=read_string_tuple(payload, "packages"),
        folder=payload.get("folder") if isinstance(payload.get("folder"), str) else None,
        roles=tuple(ArchiveEntryRole(str(role)) for role in raw_roles),
        technical_suffixes=read_string_tuple(payload, "technical_suffixes"),
        minimum_size=payload.get("minimum_size") if isinstance(payload.get("minimum_size"), int) else None,
        previewable_only=read_bool(payload, "previewable_only", default=False),
        active_overrides_only=read_bool(payload, "active_overrides_only", default=False),
        view_mode=read_enum(payload, "view_mode", ArchiveViewMode, default=ArchiveViewMode.FLAT),
        sort_field=read_enum(payload, "sort_field", ArchiveSortField, default=ArchiveSortField.PATH),
        sort_descending=read_bool(payload, "sort_descending", default=False),
    )


__all__ = [
    "ArchiveAssociationRequest",
    "ArchiveAssociationResult",
    "ArchiveChildNode",
    "ArchiveChildrenRequest",
    "ArchiveChildrenResult",
    "ArchiveDurableIdentity",
    "ArchiveEntryDto",
    "ArchiveEntryRef",
    "ArchiveEntryRole",
    "ArchiveFacet",
    "ArchiveFacetsResult",
    "ArchiveLookupKind",
    "ArchiveLookupRequest",
    "ArchiveLookupResult",
    "ArchivePage",
    "ArchiveQuery",
    "ArchiveQueryHandle",
    "ArchiveSessionHandle",
    "ArchiveSortField",
    "ArchiveViewMode",
    "archive_query_from_wire",
]
