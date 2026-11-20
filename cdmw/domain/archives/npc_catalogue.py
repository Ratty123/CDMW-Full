"""Typed, bounded resident-worker contracts for the NPC Finder.

An NPC row is keyed ``npc:<character id>`` or, for an appearance file that no
character links to, ``appearance:<normalized appearance path>``. Each outfit is
one appearance file with the pieces it lists: armour first (from the
``<Armor>`` prefabs), then body, head and hair.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalogue_wire import (
    ArchiveContractError,
    read_bool, read_int, read_string, read_string_tuple,
    require_mapping, require_sequence,
)

NPC_CATALOG_CAPABILITY = "npc_catalog_v1"
NPC_CATALOG_MAXIMUM_PAGE_SIZE = 200
NPC_KINDS = ("all", "npc", "creature", "mount", "player", "other")


def _int_tuple(payload, key: str) -> tuple[int, ...]:
    values = require_sequence(payload.get(key), key)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ArchiveContractError(f"{key} must contain integers")
    return tuple(values)


def npc_key(character_id: int) -> str:
    return f"npc:{int(character_id)}"


def appearance_key(path: str) -> str:
    return "appearance:" + path.replace("\\", "/").strip().strip("/").lower()


@dataclass(frozen=True, slots=True)
class BuildNpcCatalogRequest:
    session_id: str


@dataclass(frozen=True, slots=True)
class NpcCatalogStatistics:
    appearance_count: int
    unparsed_appearance_count: int
    armor_appearance_count: int
    armor_entry_count: int
    distinct_prefab_count: int
    resolved_prefab_count: int
    missing_prefab_count: int
    empty_prefab_count: int
    model_path_count: int
    unresolved_link_count: int

    @classmethod
    def from_wire(cls, value: object) -> "NpcCatalogStatistics":
        p = require_mapping(value, "NPC catalogue statistics")
        return cls(*(read_int(p, key) for key in (
            "appearance_count", "unparsed_appearance_count", "armor_appearance_count", "armor_entry_count",
            "distinct_prefab_count", "resolved_prefab_count", "missing_prefab_count", "empty_prefab_count",
            "model_path_count", "unresolved_link_count")))


@dataclass(frozen=True, slots=True)
class BuildNpcCatalogResult:
    session_id: str
    used_cache: bool
    npc_count: int
    appearance_row_count: int
    statistics: NpcCatalogStatistics
    warnings: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "BuildNpcCatalogResult":
        p = require_mapping(value, "NPC catalogue build")
        return cls(read_string(p, "session_id"), read_bool(p, "used_cache"), read_int(p, "npc_count"),
                   read_int(p, "appearance_row_count"), NpcCatalogStatistics.from_wire(p.get("statistics")),
                   read_string_tuple(p, "warnings"))


@dataclass(frozen=True, slots=True)
class NpcCatalogSearchRequest:
    session_id: str
    query: str = ""
    kind: str | None = None
    has_armor: bool = False
    page_start: int = 0
    page_size: int = 100

    def __post_init__(self) -> None:
        if self.kind not in (None, "", *NPC_KINDS):
            raise ValueError(f"kind must be one of {', '.join(NPC_KINDS)}.")
        if self.page_start < 0:
            raise ValueError("page_start must not be negative.")
        if not 1 <= self.page_size <= NPC_CATALOG_MAXIMUM_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {NPC_CATALOG_MAXIMUM_PAGE_SIZE}.")


@dataclass(frozen=True, slots=True)
class NpcCatalogRow:
    key: str
    character_id: int
    display_name: str
    internal_name: str
    kind: str
    source_group: str
    variant_count: int
    piece_count: int
    resolution: str
    appearance_path: str
    has_armor: bool

    @property
    def label(self) -> str:
        return self.display_name or self.internal_name or self.key

    @classmethod
    def from_wire(cls, value: object) -> "NpcCatalogRow":
        p = require_mapping(value, "NPC row")
        key = read_string(p, "key")
        if not key.startswith(("npc:", "appearance:")):
            raise ArchiveContractError("NPC row key must start with npc: or appearance:")
        return cls(key, read_int(p, "character_id"), read_string(p, "display_name"), read_string(p, "internal_name"),
                   read_string(p, "kind"), read_string(p, "source_group"), read_int(p, "variant_count"),
                   read_int(p, "piece_count"), read_string(p, "resolution"), read_string(p, "appearance_path"),
                   read_bool(p, "has_armor"))


@dataclass(frozen=True, slots=True)
class NpcCatalogSearchResult:
    session_id: str
    total_matches: int
    page_start: int
    page_size: int
    rows: tuple[NpcCatalogRow, ...]
    warnings: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "NpcCatalogSearchResult":
        p = require_mapping(value, "NPC search")
        return cls(read_string(p, "session_id"), read_int(p, "total_matches"), read_int(p, "page_start"),
                   read_int(p, "page_size"),
                   tuple(NpcCatalogRow.from_wire(row) for row in require_sequence(p.get("rows"), "rows")),
                   read_string_tuple(p, "warnings"))


@dataclass(frozen=True, slots=True)
class NpcPiece:
    section: str
    slot: str
    prefab_name: str
    prefab_entry_id: int
    prefab_path: str
    model_entry_id: int
    model_path: str
    preview: str
    resolution: str
    item_ids: tuple[int, ...]

    @property
    def has_model(self) -> bool:
        return self.model_entry_id >= 0

    @property
    def file_name(self) -> str:
        return self.model_path.replace("\\", "/").rsplit("/", 1)[-1] if self.model_path else ""

    @classmethod
    def from_wire(cls, value: object) -> "NpcPiece":
        p = require_mapping(value, "NPC piece")
        return cls(read_string(p, "section"), read_string(p, "slot"), read_string(p, "prefab_name"),
                   read_int(p, "prefab_entry_id"), read_string(p, "prefab_path"), read_int(p, "model_entry_id"),
                   read_string(p, "model_path"), read_string(p, "preview"), read_string(p, "resolution"),
                   _int_tuple(p, "item_ids"))


@dataclass(frozen=True, slots=True)
class NpcOutfit:
    variant: int
    appearance_path: str
    appearance_entry_id: int
    resolution: str
    pieces: tuple[NpcPiece, ...]
    evidence: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "NpcOutfit":
        p = require_mapping(value, "NPC outfit")
        return cls(read_int(p, "variant"), read_string(p, "appearance_path"), read_int(p, "appearance_entry_id"),
                   read_string(p, "resolution"),
                   tuple(NpcPiece.from_wire(piece) for piece in require_sequence(p.get("pieces"), "pieces")),
                   read_string_tuple(p, "evidence"))


@dataclass(frozen=True, slots=True)
class NpcOutfitRequest:
    session_id: str
    key: str
    appearance_path: str | None = None


@dataclass(frozen=True, slots=True)
class NpcOutfitResult:
    session_id: str
    row: NpcCatalogRow
    outfits: tuple[NpcOutfit, ...]
    other_display_names: tuple[str, ...]
    item_links_available: bool

    @classmethod
    def from_wire(cls, value: object) -> "NpcOutfitResult":
        p = require_mapping(value, "NPC outfit result")
        return cls(read_string(p, "session_id"), NpcCatalogRow.from_wire(p.get("row")),
                   tuple(NpcOutfit.from_wire(outfit) for outfit in require_sequence(p.get("outfits"), "outfits")),
                   read_string_tuple(p, "other_display_names"), read_bool(p, "item_links_available"))


@dataclass(frozen=True, slots=True)
class NpcWearersRequest:
    session_id: str
    piece: str
    maximum_results: int = 200

    def __post_init__(self) -> None:
        if not self.piece.strip():
            raise ValueError("piece must name a model path, a model file name or a prefab name.")
        if not 1 <= self.maximum_results <= 1000:
            raise ValueError("maximum_results must be between 1 and 1000.")


@dataclass(frozen=True, slots=True)
class NpcWearer:
    row: NpcCatalogRow
    appearance_path: str
    section: str
    slot: str
    prefab_name: str
    model_path: str

    @classmethod
    def from_wire(cls, value: object) -> "NpcWearer":
        p = require_mapping(value, "NPC wearer")
        return cls(NpcCatalogRow.from_wire(p.get("row")), *(read_string(p, key) for key in (
            "appearance_path", "section", "slot", "prefab_name", "model_path")))


@dataclass(frozen=True, slots=True)
class NpcWearersResult:
    session_id: str
    piece: str
    wearers: tuple[NpcWearer, ...]
    total_count: int
    truncated: bool

    @classmethod
    def from_wire(cls, value: object) -> "NpcWearersResult":
        p = require_mapping(value, "NPC wearers")
        return cls(read_string(p, "session_id"), read_string(p, "piece"),
                   tuple(NpcWearer.from_wire(row) for row in require_sequence(p.get("wearers"), "wearers")),
                   read_int(p, "total_count"), read_bool(p, "truncated"))
