"""Typed, bounded resident-worker contracts for the Body & Face Finder."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .catalogue import ArchiveEntryDto
from .catalogue_wire import (
    read_bool, read_int, read_string, read_string_tuple,
    require_mapping, require_sequence,
)


def _ids(payload: object, key: str) -> tuple[int, ...]:
    values = require_sequence(require_mapping(payload, "catalogue IDs").get(key), key)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError(f"{key} must contain nonnegative entry IDs")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class BuildCharacterCatalogRequest:
    session_id: str


@dataclass(frozen=True, slots=True)
class BuildCharacterCatalogResult:
    session_id: str
    used_cache: bool
    asset_count: int
    appearance_count: int
    candidate_count: int
    resolved_count: int
    unresolved_count: int
    excluded_count: int
    warnings: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "BuildCharacterCatalogResult":
        p = require_mapping(value, "character catalogue build")
        return cls(read_string(p, "session_id"), read_bool(p, "used_cache"),
                   *(read_int(p, key) for key in ("asset_count", "appearance_count", "candidate_count",
                     "resolved_count", "unresolved_count", "excluded_count")), read_string_tuple(p, "warnings"))


@dataclass(frozen=True, slots=True)
class CharacterCatalogSearchRequest:
    session_id: str
    query: str = ""
    view: str = "assets"
    tab: str = "bodies"
    role: str | None = None
    source_group: str | None = None
    body_family: str | None = None
    resolution: str | None = None
    related_key: str | None = None
    page_start: int = 0
    page_size: int = 72


@dataclass(frozen=True, slots=True)
class CharacterCatalogRow:
    key: str
    view: str
    role: str
    label: str
    internal_name: str
    path: str
    source_group: str
    body_family: str
    resolution: str
    preview_status: str
    model_count: int
    usage_count: int
    evidence: str
    embedded_face: bool = False

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogRow":
        p = require_mapping(value, "character catalogue row")
        return cls(*(read_string(p, key) for key in ("key", "view", "role", "label", "internal_name",
                    "path", "source_group", "body_family", "resolution", "preview_status")),
                   read_int(p, "model_count"), read_int(p, "usage_count"), read_string(p, "evidence"),
                   read_bool(p, "embedded_face", default=False))


@dataclass(frozen=True, slots=True)
class CharacterCatalogFacet:
    field: str
    value: str
    count: int

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogFacet":
        p = require_mapping(value, "character catalogue facet")
        return cls(read_string(p, "field"), read_string(p, "value"), read_int(p, "count"))


@dataclass(frozen=True, slots=True)
class CharacterCatalogSearchResult:
    session_id: str
    total_matches: int
    page_start: int
    page_size: int
    rows: tuple[CharacterCatalogRow, ...]
    facets: tuple[CharacterCatalogFacet, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogSearchResult":
        p = require_mapping(value, "character catalogue search")
        return cls(read_string(p, "session_id"), read_int(p, "total_matches"), read_int(p, "page_start"),
                   read_int(p, "page_size"),
                   tuple(CharacterCatalogRow.from_wire(r) for r in require_sequence(p.get("rows"), "rows")),
                   tuple(CharacterCatalogFacet.from_wire(r) for r in require_sequence(p.get("facets"), "facets")),
                   read_string_tuple(p, "warnings"))


@dataclass(frozen=True, slots=True)
class CharacterCatalogDetailRequest:
    session_id: str
    key: str


@dataclass(frozen=True, slots=True)
class CharacterCatalogFile:
    entry_id: int
    path: str
    extension: str
    relation: str
    source_pamt: str

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogFile":
        p = require_mapping(value, "character file")
        return cls(read_int(p, "entry_id"), *(read_string(p, key) for key in ("path", "extension", "relation", "source_pamt")))


@dataclass(frozen=True, slots=True)
class CharacterCatalogComponent:
    role: str
    name: str
    model_entry_ids: tuple[int, ...]
    context_entry_ids: tuple[int, ...]
    scale: float
    attributes: dict[str, str]
    resolution: str

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogComponent":
        p = require_mapping(value, "character component")
        scale = p.get("scale")
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise ValueError("Character scale must be finite and positive")
        attributes = require_mapping(p.get("attributes"), "character attributes")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in attributes.items()):
            raise ValueError("Character attributes must contain strings")
        return cls(read_string(p, "role"), read_string(p, "name"), _ids(p, "model_entry_ids"),
                   _ids(p, "context_entry_ids"), float(scale), dict(attributes), read_string(p, "resolution"))


@dataclass(frozen=True, slots=True)
class CharacterCatalogOwner:
    character_id: int
    internal_name: str
    display_name: str
    evidence: str

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogOwner":
        p = require_mapping(value, "character owner")
        return cls(read_int(p, "character_id"), *(read_string(p, key) for key in ("internal_name", "display_name", "evidence")))


@dataclass(frozen=True, slots=True)
class CharacterCatalogDetailResult:
    session_id: str
    row: CharacterCatalogRow
    models: tuple[ArchiveEntryDto, ...]
    components: tuple[CharacterCatalogComponent, ...]
    files: tuple[CharacterCatalogFile, ...]
    characters: tuple[CharacterCatalogOwner, ...]
    related: tuple[CharacterCatalogRow, ...]
    evidence: tuple[str, ...]
    total_file_count: int
    total_related_count: int
    total_character_count: int
    truncated: bool
    appearance_path: str
    context_key: str

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogDetailResult":
        p = require_mapping(value, "character catalogue details")
        return cls(read_string(p, "session_id"), CharacterCatalogRow.from_wire(p.get("row")),
                   *(tuple(kind.from_wire(r) for r in require_sequence(p.get(key), key)) for key, kind in (
                       ("models", ArchiveEntryDto), ("components", CharacterCatalogComponent), ("files", CharacterCatalogFile),
                       ("characters", CharacterCatalogOwner), ("related", CharacterCatalogRow))),
                   read_string_tuple(p, "evidence"), read_int(p, "total_file_count"), read_int(p, "total_related_count"),
                   read_int(p, "total_character_count"), read_bool(p, "truncated"), read_string(p, "appearance_path"),
                   read_string(p, "context_key"))


@dataclass(frozen=True, slots=True)
class CharacterCatalogScopeRequest:
    session_id: str
    key: str
    include_related: bool = False
    maximum_results: int = 4096


@dataclass(frozen=True, slots=True)
class CharacterCatalogScopeResult:
    session_id: str
    entry_ids: tuple[int, ...]
    direct_count: int
    total_count: int
    truncated: bool

    @classmethod
    def from_wire(cls, value: object) -> "CharacterCatalogScopeResult":
        p = require_mapping(value, "character catalogue scope")
        return cls(read_string(p, "session_id"), _ids(p, "entry_ids"), read_int(p, "direct_count"),
                   read_int(p, "total_count"), read_bool(p, "truncated"))
