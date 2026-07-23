"""Typed contracts for the lazy Full archive item catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from .catalogue_wire import (
    read_bool,
    read_int,
    read_optional_string,
    read_string,
    read_string_tuple,
    require_mapping,
    require_sequence,
)

_LEGACY_CATEGORY_FILTERS: dict[tuple[str, str], tuple[str | None, str | None]] = {
    ("equipment", "subweapon / shield"): ("Weapon", "Shield"),
    ("equipment", "upper armor"): ("Armor", "Body"),
    ("equipment", "lower armor"): ("Armor", "Legs"),
    ("equipment", "hands"): ("Armor", "Hands"),
    ("equipment", "feet"): ("Armor", "Feet"),
    ("equipment", "head"): ("Armor", "Head"),
    ("equipment", "weapon"): (None, None),
    ("equipment", "accessory"): (None, None),
    ("consumable", "consumable"): (None, None),
    ("material", "crafting material"): (None, None),
    ("quest", "quest item"): ("Quest / Document", "Quest"),
    ("other", "other"): ("Item", "Unclassified"),
}


def migrate_legacy_item_catalogue_filter(
    category: str | None,
    group: str | None,
) -> tuple[str | None, str | None]:
    """Map or clear filters persisted by Full's retired coarse taxonomy."""

    normalized_category = str(category or "").strip()
    normalized_group = str(group or "").strip()
    legacy_key = (normalized_category.casefold(), normalized_group.casefold())
    if legacy_key in _LEGACY_CATEGORY_FILTERS:
        return _LEGACY_CATEGORY_FILTERS[legacy_key]
    return normalized_category or None, normalized_group or None


@dataclass(frozen=True, slots=True)
class BuildNameIndexRequest:
    session_id: str


@dataclass(frozen=True, slots=True)
class BuildNameIndexResult:
    session_id: str
    available: bool
    used_cache: bool
    exact_name_count: int
    related_name_count: int
    warning: str | None = None
    item_count: int = 0

    @classmethod
    def from_wire(cls, value: object) -> "BuildNameIndexResult":
        payload = require_mapping(value, "name index result")
        return cls(
            session_id=read_string(payload, "session_id"),
            available=read_bool(payload, "available"),
            used_cache=read_bool(payload, "used_cache"),
            exact_name_count=read_int(payload, "exact_name_count"),
            related_name_count=read_int(payload, "related_name_count"),
            warning=read_optional_string(payload, "warning"),
            item_count=read_int(payload, "item_count", default=0),
        )


@dataclass(frozen=True, slots=True)
class ItemCatalogSearchRequest:
    session_id: str
    query: str = ""
    category: str | None = None
    group: str | None = None
    material_tag: str | None = None
    page_start: int = 0
    page_size: int = 72


@dataclass(frozen=True, slots=True)
class ItemCatalogCategoryFacet:
    category: str
    group: str
    count: int

    @classmethod
    def from_wire(cls, value: object) -> "ItemCatalogCategoryFacet":
        payload = require_mapping(value, "item category facet")
        return cls(
            category=read_string(payload, "category"),
            group=read_string(payload, "group"),
            count=read_int(payload, "count"),
        )


@dataclass(frozen=True, slots=True)
class ItemCatalogValueFacet:
    value: str
    count: int

    @classmethod
    def from_wire(cls, value: object) -> "ItemCatalogValueFacet":
        payload = require_mapping(value, "item value facet")
        return cls(read_string(payload, "value"), read_int(payload, "count"))


@dataclass(frozen=True, slots=True)
class ItemCatalogRow:
    item_id: int
    internal_name: str
    display_name: str
    category: str
    group: str
    category_evidence: str
    pac_files: tuple[str, ...]
    model_stems: tuple[str, ...]
    icon_paths: tuple[str, ...]
    localized_names: tuple[str, ...]
    material_tags: tuple[str, ...]
    variant_count: int
    evidence: str

    @classmethod
    def from_wire(cls, value: object) -> "ItemCatalogRow":
        payload = require_mapping(value, "item catalogue row")
        return cls(
            item_id=read_int(payload, "item_id"),
            internal_name=read_string(payload, "internal_name"),
            display_name=read_string(payload, "display_name"),
            category=read_string(payload, "category"),
            group=read_string(payload, "group"),
            category_evidence=read_string(payload, "category_evidence"),
            pac_files=read_string_tuple(payload, "pac_files"),
            model_stems=read_string_tuple(payload, "model_stems"),
            icon_paths=read_string_tuple(payload, "icon_paths"),
            localized_names=read_string_tuple(payload, "localized_names"),
            material_tags=read_string_tuple(payload, "material_tags"),
            variant_count=read_int(payload, "variant_count"),
            evidence=read_string(payload, "evidence"),
        )


@dataclass(frozen=True, slots=True)
class ItemCatalogSearchResult:
    session_id: str
    total_matches: int
    page_start: int
    page_size: int
    items: tuple[ItemCatalogRow, ...]
    categories: tuple[ItemCatalogCategoryFacet, ...]
    material_tags: tuple[ItemCatalogValueFacet, ...]
    has_material_evidence: bool
    warning: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ItemCatalogSearchResult":
        payload = require_mapping(value, "item catalogue search result")
        return cls(
            session_id=read_string(payload, "session_id"),
            total_matches=read_int(payload, "total_matches"),
            page_start=read_int(payload, "page_start"),
            page_size=read_int(payload, "page_size"),
            items=tuple(ItemCatalogRow.from_wire(row) for row in require_sequence(payload.get("items"), "items")),
            categories=tuple(
                ItemCatalogCategoryFacet.from_wire(row)
                for row in require_sequence(payload.get("categories"), "categories")
            ),
            material_tags=tuple(
                ItemCatalogValueFacet.from_wire(row)
                for row in require_sequence(payload.get("material_tags"), "material_tags")
            ),
            has_material_evidence=read_bool(payload, "has_material_evidence", default=False),
            warning=read_optional_string(payload, "warning"),
        )


@dataclass(frozen=True, slots=True)
class ItemIconBatchRequest:
    session_id: str
    item_ids: tuple[int, ...]
    thumbnail_size: int = 120


@dataclass(frozen=True, slots=True)
class ItemIconResult:
    item_id: int
    png_path: str | None
    source_path: str | None
    warning: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ItemIconResult":
        payload = require_mapping(value, "item icon result")
        return cls(
            item_id=read_int(payload, "item_id"),
            png_path=read_optional_string(payload, "png_path"),
            source_path=read_optional_string(payload, "source_path"),
            warning=read_optional_string(payload, "warning"),
        )


@dataclass(frozen=True, slots=True)
class ItemIconBatchResult:
    session_id: str
    items: tuple[ItemIconResult, ...]

    @classmethod
    def from_wire(cls, value: object) -> "ItemIconBatchResult":
        payload = require_mapping(value, "item icon batch result")
        return cls(
            session_id=read_string(payload, "session_id"),
            items=tuple(ItemIconResult.from_wire(row) for row in require_sequence(payload.get("items"), "items")),
        )


@dataclass(frozen=True, slots=True)
class ItemCatalogScopeRequest:
    session_id: str
    item_ids: tuple[int, ...] = ()
    query: str = ""
    category: str | None = None
    group: str | None = None
    material_tag: str | None = None
    include_related: bool = False
    maximum_results: int = 4096


@dataclass(frozen=True, slots=True)
class ItemCatalogScopeResult:
    session_id: str
    entry_ids: tuple[int, ...]
    direct_count: int
    item_count: int
    truncated: bool

    @classmethod
    def from_wire(cls, value: object) -> "ItemCatalogScopeResult":
        payload = require_mapping(value, "item catalogue scope result")
        raw_ids = require_sequence(payload.get("entry_ids"), "entry_ids")
        if any(isinstance(entry_id, bool) or not isinstance(entry_id, int) for entry_id in raw_ids):
            raise ValueError("entry_ids must contain only integers")
        return cls(
            session_id=read_string(payload, "session_id"),
            entry_ids=tuple(raw_ids),  # type: ignore[arg-type]
            direct_count=read_int(payload, "direct_count"),
            item_count=read_int(payload, "item_count"),
            truncated=read_bool(payload, "truncated"),
        )


__all__ = [
    "BuildNameIndexRequest",
    "BuildNameIndexResult",
    "ItemCatalogCategoryFacet",
    "ItemCatalogRow",
    "ItemCatalogScopeRequest",
    "ItemCatalogScopeResult",
    "ItemCatalogSearchRequest",
    "ItemCatalogSearchResult",
    "ItemCatalogValueFacet",
    "ItemIconBatchRequest",
    "ItemIconBatchResult",
    "ItemIconResult",
    "migrate_legacy_item_catalogue_filter",
]
