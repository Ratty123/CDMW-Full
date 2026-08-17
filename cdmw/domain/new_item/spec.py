"""The specification of a new item, as data.

A :class:`NewItemSpec` says everything the New Item Studio needs to build one
item from a template: identity, model source, stat and price edits, where it is
sold, which item groups it joins, and where its icon comes from. It carries no
bytes and no archive knowledge; :mod:`cdmw.domain.new_item.rules` says whether a
spec is valid, and the service turns a valid spec into archive changes.

Optional identity fields (`item_key`, `stem`, `name_key`, `desc_key`) may be left
`None` and allocated later through :mod:`cdmw.domain.new_item.allocation`; the
validator treats `None` as "to be allocated", not as an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Optional, Tuple


class ModelSource(str, Enum):
    """Where the new item's model comes from."""

    #: Keep the template's model family: no new archive files, only table rows.
    TEMPLATE = "template"
    #: An imported build (Import Mesh / Builder output) re-pathed to the new stem.
    IMPORTED = "imported"


class IconSource(str, Enum):
    #: Point the clone at the template's icon (no new icon file).
    TEMPLATE = "template"
    #: A generated icon at the new item's own path (NI-013).
    GENERATED = "generated"


class ItemGroupsChoice(str, Enum):
    #: Join every item group the template is in.
    TEMPLATE = "template"
    #: Join exactly the listed group keys.
    EXPLICIT = "explicit"


class PlacementKind(str, Enum):
    NONE = "none"
    #: Replace one existing stock entry of a store with the new item.
    SWAP = "swap"
    #: Add a stock entry to a store (needs the StoreInfo insert, NI-005).
    INSERT = "insert"


@dataclass(frozen=True, slots=True)
class StatEdit:
    """A `_statList_DataDefinedStatic` value at one enchant level."""

    level: int
    status_key: int
    value: int


@dataclass(frozen=True, slots=True)
class BuyPriceEdit:
    """A `_buyPriceList` price at one enchant level, in one money item."""

    level: int
    item_key: int
    price: int


@dataclass(frozen=True, slots=True)
class PriceEdit:
    """A `_priceList` price in one money item."""

    item_key: int
    price: int


@dataclass(frozen=True, slots=True)
class Placement:
    kind: PlacementKind = PlacementKind.NONE
    store_name: str = ""
    #: For SWAP: the internal name of the stock entry's current item.
    old_item_name: str = ""
    #: For INSERT: the stock price in the store's money item.
    price: Optional[int] = None


@dataclass(frozen=True, slots=True)
class NewItemSpec:
    template_key: int
    internal_name: str
    #: Per language code (`eng`, `kor`, ...); `eng` is required, the rest default to it.
    display_names: Mapping[str, str] = field(default_factory=dict)
    descriptions: Mapping[str, str] = field(default_factory=dict)
    item_key: Optional[int] = None
    stem: Optional[str] = None
    name_key: Optional[str] = None
    desc_key: Optional[str] = None
    model_source: ModelSource = ModelSource.TEMPLATE
    icon: IconSource = IconSource.TEMPLATE
    stat_edits: Tuple[StatEdit, ...] = ()
    buy_price_edits: Tuple[BuyPriceEdit, ...] = ()
    price_edits: Tuple[PriceEdit, ...] = ()
    max_stack_count: Optional[int] = None
    placement: Placement = field(default_factory=Placement)
    item_groups: ItemGroupsChoice = ItemGroupsChoice.TEMPLATE
    explicit_item_groups: Tuple[int, ...] = ()

    @property
    def needs_new_model_files(self) -> bool:
        return self.model_source is ModelSource.IMPORTED

    @property
    def needs_new_stem(self) -> bool:
        return self.model_source is ModelSource.IMPORTED or self.icon is IconSource.GENERATED

    def with_allocations(
        self,
        *,
        item_key: Optional[int] = None,
        stem: Optional[str] = None,
        name_key: Optional[str] = None,
        desc_key: Optional[str] = None,
    ) -> "NewItemSpec":
        """The same spec with allocated identity fields filled in (given ones win)."""

        return replace(
            self,
            item_key=self.item_key if self.item_key is not None else item_key,
            stem=self.stem if self.stem is not None else stem,
            name_key=self.name_key if self.name_key is not None else name_key,
            desc_key=self.desc_key if self.desc_key is not None else desc_key,
        )


__all__ = [
    "BuyPriceEdit",
    "IconSource",
    "ItemGroupsChoice",
    "ModelSource",
    "NewItemSpec",
    "Placement",
    "PlacementKind",
    "PriceEdit",
    "StatEdit",
]
