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
from cdmw.domain.new_item.authoring import SocketSlot, LevelBonuses, RecipeOverride, RewardAcquisition, VariantAppearance


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


class MaterialRoute(str, Enum):
    """How an imported model's materials are written for the game."""

    #: The Builder's own sidecar as it came: the template's layered material with the
    #: imported textures fitted into it (Material Authority).
    BUILDER = "builder"
    #: The wrappers the import owns rewritten to the game's texture-driven shaders
    #: (`SkinnedMeshStandard`, `SkinnedMeshEmissive`): albedo, normal, `_sp` roughness/
    #: metalness from the source. What the shipped texture-driven weapons use.
    PLAIN_PBR = "plain_pbr"


class SheathedModel(str, Enum):
    """What draws when an imported weapon is sheathed (the `_IN` part).

    A weapon's sheathed look is a part of its own (`CD_TwoHandWeapon_Sword_IN`, the
    `_in` stems), usually borrowed from another item: Reckleeman's greatsword borrows
    `cd_phm_02_sword_0001_in`, the shipped sword-in-scabbard model, so an imported
    model on that template shows the shipped scabbard beside it. Only read for an
    imported model.
    """

    #: Keep borrowing the template's sheathed part.
    TEMPLATE = "template"
    #: A sheathed part of the item's own that draws the imported mesh: the borrowed
    #: `_IN` records are cloned under the item's stem and their prefabs re-pathed to
    #: the new mesh (eight shipped two-hand swords have no sheathed part at all, so
    #: nothing depends on the scabbard being there).
    OWN_MODEL = "own_model"


class ItemGroupsChoice(str, Enum):
    ORDINARY = "ordinary"
    #: Join every item group the template is in.
    TEMPLATE = "template"
    #: Join exactly the listed group keys.
    EXPLICIT = "explicit"


class EnhancementRows(str, Enum):
    """Which `multichangeinfo` transition rows the item enhances through."""

    #: Inherit the template's recipe values. Current-format connections receive
    #: owned item/output references; the legacy format retains shared rows.
    TEMPLATE = "template"
    #: Request owned transitions explicitly, including on the legacy format.
    OWN = "own"


#: A shop line's stock count that never runs out (the bank's gold bars carry it).
UNLIMITED_STOCK = 0xFFFFFFFF


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
    #: Not written: a StoreInfo entry carries no price of its own (the shop prices the
    #: item from its buy-price list). Kept so an older spec still loads; the rules warn.
    price: Optional[int] = None
    #: A shop line may demand the knowledge of a collection prop before it sells (the
    #: shop shows "Knowledge" until then). False, the default, sells the new item freely
    #: by dropping that block from the line it takes; True keeps the line's own.
    keep_requirement: bool = False
    #: How many the shop has: None keeps the line's own count (1 on most equipment
    #: lines: sold once, then "0 in stock"), :data:`UNLIMITED_STOCK` never runs out.
    stock_count: Optional[int] = None
    stock_index: Optional[int] = None


from cdmw.domain.new_item.effect_authoring import EffectLook, EffectLayer


@dataclass(frozen=True, slots=True)
class GlowChoice:
    """The parts of an item that glow, and how.

    `parts` are material submesh names as the `.pac_xml` writes them
    (`cd_phm_02_sword_handle_0040`), because that is what a material wrapper is keyed by.
    The game's emissive is one intensity map times one colour times one number, so a part
    that glows takes a solid map and these two values.
    """

    parts: Tuple[str, ...] = ()
    #: linear 0..1 per channel, as the colour buttons elsewhere in the studio carry it
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    #: the shipped materials run 1 to 10 and the game's own authority caps at 20
    intensity: float = 4.0

    @property
    def wanted(self) -> bool:
        return bool(self.parts)

    def hex_color(self) -> str:
        """`#RRGGBBAA`, the way a `.pac_xml` writes a colour."""

        red, green, blue = (max(0, min(255, int(round(float(channel) * 255)))) for channel in self.color)
        return f"#{red:02X}{green:02X}{blue:02X}FF"


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
    #: Only read for an imported model.
    material_route: MaterialRoute = MaterialRoute.PLAIN_PBR
    #: Only read for an imported model.
    sheathed_model: SheathedModel = SheathedModel.OWN_MODEL
    #: Copy the template's mesh physics (`character/bin__/meshphysics/<stem>.hkx`) onto the
    #: item. That file binds cloth and collision to the *template's* own vertices, so on a
    #: model of your own it drives whichever vertices those indices land on: a handle that
    #: swings like cloth, a blade that sags. The game finds the file by the stem, so an item
    #: written without one simply has no physics. Only read for an imported model.
    keep_template_physics: bool = False
    #: Which parts of the item glow, in what colour, and how strongly. Empty parts means
    #: nothing glows, which is what an imported model does unless it brought an emissive
    #: map of its own: a template's own glow rides on a mask cut for the template's mesh,
    #: and the map the importer generates in its place says "glow everywhere".
    glow: "GlowChoice" = None  # type: ignore[assignment]
    icon: IconSource = IconSource.TEMPLATE
    stat_edits: Tuple[StatEdit, ...] = ()
    buy_price_edits: Tuple[BuyPriceEdit, ...] = ()
    price_edits: Tuple[PriceEdit, ...] = ()
    max_stack_count: Optional[int] = None
    placement: Placement = field(default_factory=Placement)
    shop_placements: Optional[Tuple[Placement, ...]] = None
    item_groups: ItemGroupsChoice = ItemGroupsChoice.TEMPLATE
    explicit_item_groups: Tuple[int, ...] = ()
    enhancement: EnhancementRows = EnhancementRows.TEMPLATE
    #: The Abyss Gear items embedded by default (the tooltip's perk lines), as item keys;
    #: None keeps the template's. The shipped rows carry up to four.
    socket_items: Optional[Tuple[int, ...]] = None
    socket_slots: Optional[Tuple["SocketSlot", ...]] = None
    equipment_bonuses: Optional[Tuple["LevelBonuses", ...]] = None
    recipes: Optional[Tuple[RecipeOverride, ...]] = None
    reward_acquisitions: Optional[Tuple[RewardAcquisition, ...]] = None
    variants: Optional[Tuple[VariantAppearance, ...]] = None
    #: A persistent visual on the item: an effect reference such as
    #: `fx_cc_firesweapon_a__fire1.level.effect` (`effect/binary__/releasebin/<stem>.pae`),
    #: grafted into the item's own prefabs as an `EffectComponent`. None for none. Any
    #: effect gives the item its own model family (prefabs of its own), copying the
    #: template's mesh when no model is imported.
    effect: Optional[str] = None
    #: The grafted effect's `_offsetTransform`: a uniform scale, an offset in the item's
    #: own axes in metres, and a turn about those axes as Euler
    #: degrees applied x, then y, then z -- the order the placement viewport composes.
    #: The transform's quaternion field is proven in shipped data (the spear carries a
    #: quarter turn about z); the studio's own written turn awaits an in-game fit check.
    #: Only read with an effect.
    effect_scale: float = 1.0
    effect_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    effect_rotation_degrees: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: How the effect should look, when not as shipped: the effect and the emitters it
    #: instances are cloned under stems of the item's own and their named values edited in
    #: place (see :mod:`cdmw.core.effect_edit`). Only read with an effect.
    effect_look: "EffectLook" = field(default_factory=lambda: EffectLook())
    effect_layers: Optional[Tuple[EffectLayer, ...]] = None

    @property
    def active_effect_layers(self) -> Tuple[EffectLayer, ...]:
        if self.effect_layers is not None:
            return tuple(layer for layer in self.effect_layers if layer.enabled and layer.stem)
        if self.effect is None:
            return ()
        parts = str(self.effect).split('.')
        return (EffectLayer(parts[0], scale=self.effect_scale, offset=self.effect_offset, rotation=self.effect_rotation_degrees, look=self.effect_look, kind=parts[1] if len(parts) > 1 else 'level'),)

    @property
    def needs_new_model_files(self) -> bool:
        return self.model_source is ModelSource.IMPORTED

    @property
    def needs_own_family(self) -> bool:
        """The item gets prefabs, mesh and side files of its own under its stem."""

        return self.model_source is ModelSource.IMPORTED or bool(self.active_effect_layers) or bool(self.variants)

    @property
    def needs_new_stem(self) -> bool:
        return self.needs_own_family or self.icon is IconSource.GENERATED

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
    "EnhancementRows",
    "IconSource",
    "MaterialRoute",
    "ItemGroupsChoice",
    "ModelSource",
    "EffectLook",
    "NewItemSpec",
    "Placement",
    "UNLIMITED_STOCK",
    "PlacementKind",
    "PriceEdit",
    "SheathedModel",
    "StatEdit",
]
