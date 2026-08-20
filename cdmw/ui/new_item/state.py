"""The New Item Studio's editable state, and the pure helpers around it.

No Qt here. The panels write into a :class:`NewItemDraft`, and :func:`spec_from_draft`
turns it into the domain's :class:`NewItemSpec` by diffing the stat grid against the
template's own ladder, so only what the reader changed becomes an edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.domain.new_item.spec import (
    BuyPriceEdit,
    EffectLook,
    EnhancementRows,
    GlowChoice,
    IconSource,
    ItemGroupsChoice,
    MaterialRoute,
    ModelSource,
    NewItemSpec,
    SheathedModel,
    Placement,
    PlacementKind,
    PriceEdit,
    StatEdit,
    UNLIMITED_STOCK,
)

MANAGERS: Tuple[str, ...] = ("CDUMM", "DMM", "JMM")
STAT_KIND = "stat"
BUY_PRICE_KIND = "buy_price"


@dataclass(frozen=True, slots=True)
class StatColumn:
    """One column of the stats grid: a StatusInfo stat or a buy-price money item."""

    kind: str  # "stat" | "buy_price"
    key: int
    label: str


@dataclass(frozen=True, slots=True)
class StatGrid:
    """The template's enchant ladder as a grid the panel can show and edit."""

    columns: Tuple[StatColumn, ...]
    #: level -> column index -> value (None where the template has no entry)
    template_values: Tuple[Tuple[Optional[int], ...], ...]
    price_items: Tuple[Tuple[int, str, int], ...]  # (item key, label, template price)

    @property
    def level_count(self) -> int:
        return len(self.template_values)


#: The game's status entries as a reader knows them; the key stays in brackets so the
#: table still names the row's own member. A reading of the names, not the exe's words.
STATUS_LABELS = {
    "DDD": "Attack",
    "DPV": "Defence",
    "DDV": "Evasion",
    "GuardPVRate": "Guard rate",
    "AttackSpeedRate": "Attack speed",
    "AttackedDamageRate": "Damage taken",
    "AttackedDamageReduction": "Damage reduction",
    "CriticalRate": "Critical rate",
    "CriticalDamage": "Critical damage",
    "HitRate": "Accuracy",
    "RangeHitRate": "Ranged accuracy",
    "MaxDamageRate": "Max damage",
    "MoveSpeedRate": "Move speed",
    "ClimbSpeedRate": "Climb speed",
    "SwimSpeedRate": "Swim speed",
    "Hp": "HP",
    "Mp": "MP",
    "Stamina": "Stamina",
    "Stamina_UseResourceDecreaseRate": "Stamina cost reduction",
    "Mp_UseResourceDecreaseRate": "MP cost reduction",
    "FireResistance": "Fire resistance",
    "IceResistance": "Ice resistance",
    "ElectricityResistance": "Lightning resistance",
    "MoraleResistance": "Morale resistance",
    "Strength": "Strength",
    "Agility": "Agility",
    "Pressure": "Pressure",
    "Fatal": "Fatal",
    "KnockOut": "Knock-out",
    "KnockOutPVRate": "Knock-out defence",
    "DPVRate": "Defence rate",
    "DHIT": "Hit",
}


def status_label(name: str) -> str:
    """`Attack (DDD)` for a status the reader has a word for, the bare name otherwise."""

    friendly = STATUS_LABELS.get(str(name))
    return f"{friendly} ({name})" if friendly else str(name)


def stat_grid_for(
    row: object,
    status_names: Mapping[int, str],
    item_names: Mapping[int, str],
    extra_status_keys: Sequence[int] = (),
) -> StatGrid:
    """Columns in first-seen order across the ladder; a value where the level has one.
    `extra_status_keys` are stats the reader added that the template's ladder lacks:
    they follow the template's stat columns (before the prices) with no template value,
    so every value typed into them is an addition the plan writes.

    `row` is a parsed ItemInfo row (the service's snapshot hands one over); only its
    `enchant_levels` and `price_list` are read, so the UI layer needs no core import.
    """

    columns: List[StatColumn] = []
    seen_stats: List[int] = []
    seen_prices: List[int] = []
    for level in row.enchant_levels:
        for stat in level.stats:
            if stat.status_key not in seen_stats:
                seen_stats.append(stat.status_key)
                columns.append(StatColumn(STAT_KIND, stat.status_key, status_label(status_names.get(stat.status_key, str(stat.status_key)))))
    for key in extra_status_keys:
        key = int(key)
        if key not in seen_stats:
            seen_stats.append(key)
            columns.append(StatColumn(STAT_KIND, key, status_label(status_names.get(key, str(key)))))
    for level in row.enchant_levels:
        for price in level.buy_prices:
            if price.item_key not in seen_prices:
                seen_prices.append(price.item_key)
                columns.append(StatColumn(BUY_PRICE_KIND, price.item_key, f"Price ({item_names.get(price.item_key, str(price.item_key))})"))
    values = []
    for level in row.enchant_levels:
        stats = {stat.status_key: stat.value for stat in level.stats}
        prices = {price.item_key: price.price for price in level.buy_prices}
        values.append(tuple(
            (stats.get(column.key) if column.kind == STAT_KIND else prices.get(column.key)) for column in columns
        ))
    price_items = tuple((price.item_key, item_names.get(price.item_key, str(price.item_key)), price.price) for price in row.price_list)
    return StatGrid(columns=tuple(columns), template_values=tuple(values), price_items=price_items)


@dataclass(slots=True)
class NewItemDraft:
    """What the panels hold. Everything is optional until the plan is built."""

    template_key: Optional[int] = None
    internal_name: str = ""
    display_names: Dict[str, str] = field(default_factory=dict)
    descriptions: Dict[str, str] = field(default_factory=dict)
    stem: str = ""
    item_key: Optional[int] = None
    model_source: ModelSource = ModelSource.TEMPLATE
    #: how an imported model's materials are written; the plain-PBR shaders unless the
    #: Builder's own sidecar is asked for
    material_route: MaterialRoute = MaterialRoute.PLAIN_PBR
    #: what an imported weapon draws when sheathed: a part of its own, or the template's borrowed one
    sheathed_model: SheathedModel = SheathedModel.OWN_MODEL
    #: whether an imported model inherits the template's cloth and collision
    keep_template_physics: bool = False
    #: the material parts that glow, and how. Empty is no glow, which is what an imported
    #: model does unless it brought an emissive map of its own.
    glow_parts: Tuple[str, ...] = ()
    glow_color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    glow_intensity: float = 4.0
    icon: IconSource = IconSource.TEMPLATE
    icon_source_path: str = ""
    #: level -> column index -> value; None means "as the template".
    grid_values: Dict[Tuple[int, int], Optional[int]] = field(default_factory=dict)
    extra_levels: int = 0
    #: StatusInfo keys added as stat columns the template's ladder lacks, in the order added
    extra_stat_keys: List[int] = field(default_factory=list)
    price_values: Dict[int, int] = field(default_factory=dict)
    max_stack_count: Optional[int] = None
    placement_kind: PlacementKind = PlacementKind.NONE
    store_name: str = ""
    old_item_name: str = ""
    #: Keep the shop line's unlock-knowledge requirement (default: sell freely).
    keep_requirement: bool = False
    #: The shop line never runs out (default); off keeps the line's own count, which is
    #: 1 on most equipment lines: sold once, then "0 in stock".
    unlimited_stock: bool = True
    item_groups: ItemGroupsChoice = ItemGroupsChoice.TEMPLATE
    explicit_item_groups: Tuple[int, ...] = ()
    manager: str = "CDUMM"
    export_root: str = ""
    own_enhancement_rows: bool = False
    #: The perks (Abyss Gear socket items) the item carries; None keeps the template's.
    socket_items: Optional[List[int]] = None
    #: A weapon effect stem (`fx_cc_firesweapon_a__fire1`); empty for none.
    effect_stem: str = ""
    #: the grafted effect's uniform scale and offset (x, y, z, metres in the weapon's axes)
    effect_scale: float = 1.0
    effect_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: The effect's look: colour (RGB 0..1) or None, and factors on brightness, particle
    #: size, spawn rate and lifetime; all as shipped by default.
    effect_color: Optional[Tuple[float, float, float]] = None
    effect_intensity: float = 1.0
    effect_size: float = 1.0
    effect_rate: float = 1.0
    effect_lifetime: float = 1.0

    def reset_for_template(self, template_key: Optional[int]) -> None:
        self.template_key = template_key
        self.grid_values = {}
        self.extra_levels = 0
        self.price_values = {}
        self.max_stack_count = None
        self.stem = ""
        self.item_key = None
        self.socket_items = None


def stat_edits_from_grid(draft: NewItemDraft, grid: StatGrid) -> Tuple[Tuple[StatEdit, ...], Tuple[BuyPriceEdit, ...]]:
    """Every grid cell that differs from the template, as edits; new levels are copied then edited."""

    stats: List[StatEdit] = []
    prices: List[BuyPriceEdit] = []
    for (level, column_index), value in sorted(draft.grid_values.items()):
        if value is None or column_index >= len(grid.columns):
            continue
        column = grid.columns[column_index]
        template_value = grid.template_values[level][column_index] if level < grid.level_count else None
        if template_value == value:
            continue
        if column.kind == STAT_KIND:
            stats.append(StatEdit(level=level, status_key=column.key, value=int(value)))
        else:
            prices.append(BuyPriceEdit(level=level, item_key=column.key, price=int(value)))
    return tuple(stats), tuple(prices)


def scaled_grid_values(grid: StatGrid, factor: float, *, kinds: Sequence[str] = (STAT_KIND,)) -> Dict[Tuple[int, int], Optional[int]]:
    """Every template value of the given column kinds multiplied by `factor` (rounded)."""

    out: Dict[Tuple[int, int], Optional[int]] = {}
    for level, values in enumerate(grid.template_values):
        for column_index, value in enumerate(values):
            if value is None or grid.columns[column_index].kind not in kinds:
                continue
            out[(level, column_index)] = int(round(value * factor))
    return out


def flat_grid_values(grid: StatGrid, value: int, *, kinds: Sequence[str] = (STAT_KIND,)) -> Dict[Tuple[int, int], Optional[int]]:
    out: Dict[Tuple[int, int], Optional[int]] = {}
    for level, values in enumerate(grid.template_values):
        for column_index, template_value in enumerate(values):
            if template_value is None or grid.columns[column_index].kind not in kinds:
                continue
            out[(level, column_index)] = int(value)
    return out


def spec_from_draft(draft: NewItemDraft, grid: Optional[StatGrid]) -> NewItemSpec:
    """The domain spec for the draft; unset identity fields stay None for allocation."""

    if draft.template_key is None:
        raise ValueError("Choose a template item first.")
    stats, buy_prices = stat_edits_from_grid(draft, grid) if grid is not None else ((), ())
    price_edits = tuple(
        PriceEdit(item_key=int(key), price=int(value))
        for key, value in sorted(draft.price_values.items())
        if grid is None or all(not (item == key and template == value) for item, _label, template in grid.price_items)
    )
    placement = Placement(
        kind=draft.placement_kind,
        store_name=draft.store_name if draft.placement_kind is not PlacementKind.NONE else "",
        old_item_name=draft.old_item_name if draft.placement_kind is PlacementKind.SWAP else "",
        keep_requirement=bool(draft.keep_requirement),
        stock_count=UNLIMITED_STOCK if draft.unlimited_stock else None,
    )
    return NewItemSpec(
        template_key=int(draft.template_key),
        internal_name=draft.internal_name.strip(),
        display_names={code: text for code, text in draft.display_names.items() if str(text).strip()},
        descriptions={code: text for code, text in draft.descriptions.items() if str(text).strip()},
        item_key=draft.item_key,
        stem=draft.stem.strip() or None,
        model_source=draft.model_source,
        material_route=draft.material_route,
        sheathed_model=draft.sheathed_model,
        keep_template_physics=draft.keep_template_physics,
        glow=GlowChoice(
            parts=tuple(draft.glow_parts), color=tuple(draft.glow_color), intensity=float(draft.glow_intensity),
        ) if draft.glow_parts else None,
        icon=draft.icon,
        stat_edits=stats,
        buy_price_edits=buy_prices,
        price_edits=price_edits,
        max_stack_count=draft.max_stack_count,
        placement=placement,
        item_groups=draft.item_groups,
        explicit_item_groups=tuple(draft.explicit_item_groups),
        enhancement=EnhancementRows.OWN if draft.own_enhancement_rows else EnhancementRows.TEMPLATE,
        socket_items=None if draft.socket_items is None else tuple(int(item) for item in draft.socket_items),
        effect=effect_reference(draft.effect_stem),
        effect_scale=float(draft.effect_scale),
        effect_offset=tuple(float(v) for v in draft.effect_offset),
        effect_look=EffectLook(
            color=tuple(float(v) for v in draft.effect_color) if draft.effect_color is not None else None,
            intensity=float(draft.effect_intensity), size=float(draft.effect_size),
            rate=float(draft.effect_rate), lifetime=float(draft.effect_lifetime),
        ),
    )


EFFECT_KIND = "level"


def effect_reference(stem: str) -> Optional[str]:
    """`<stem>.level.effect`, the persistent form a weapon carries; None for no stem."""

    clean = str(stem or "").strip()
    return f"{clean}.{EFFECT_KIND}.effect" if clean else None


def with_template(draft: NewItemDraft, template_key: Optional[int]) -> NewItemDraft:
    """A copy of the draft re-pointed at a template, with the per-template fields cleared."""

    copy = replace(draft, grid_values=dict(draft.grid_values), price_values=dict(draft.price_values))
    copy.reset_for_template(template_key)
    return copy


__all__ = [
    "EFFECT_KIND",
    "MANAGERS",
    "NewItemDraft",
    "effect_reference",
    "StatColumn",
    "StatGrid",
    "flat_grid_values",
    "scaled_grid_values",
    "spec_from_draft",
    "stat_edits_from_grid",
    "stat_grid_for",
    "with_template",
]
