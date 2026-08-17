"""What makes a :class:`NewItemSpec` valid.

Two layers, kept apart because they need different inputs and fail at different
times in the UI:

* :func:`validate_spec` needs nothing but the spec: shapes, ranges, required
  fields, internal consistency. It runs on every keystroke.
* :func:`validate_against_context` also needs a read-only snapshot of the
  archives (:class:`NewItemContext`): what keys, names, stems, stores and
  localisation keys already exist, and what the chosen template looks like. The
  service builds that snapshot once per archive scan, off the UI thread, and this
  module never reads a file itself.

Every refusal is a :class:`ValidationIssue` with a stable `code`, the `field` it
belongs to and a message, because the tab shows them next to the field and tests
assert on the code, not the wording. `severity` is `error` (cannot build),
`warning` (can build, worth knowing) or `info`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping, Optional, Tuple

from cdmw.domain.new_item.allocation import is_conventional_localization_key
from cdmw.domain.new_item.spec import (
    EnhancementRows,
    IconSource,
    ItemGroupsChoice,
    ModelSource,
    NewItemSpec,
    PlacementKind,
)

#: The 14 shipped `.paloc` tables, by the language code in their file names.
LOCALIZATION_LANGUAGES: Tuple[str, ...] = (
    "eng", "kor", "jpn", "rus", "tur", "spa-es", "spa-mx", "fre", "ger", "ita", "pol", "por-br", "zho-tw", "zho-cn",
)
REQUIRED_LANGUAGE = "eng"

#: The socket list the row reader accepts, and the most any shipped item carries (Regglin's boss sword, four).
MAX_SOCKET_ITEMS = 8
MAX_SHIPPED_SOCKET_ITEMS = 4

_INTERNAL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_STEM_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_LOC_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_EFFECT_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}\.(level|action)\.effect$")
_U32_MAX = 0xFFFFFFFF
_I32_MIN, _I32_MAX = -0x80000000, 0x7FFFFFFF


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: str = "error"

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True, slots=True)
class TemplateLevelFacts:
    """One enchant level of the template: which stats and buy-price items it carries."""

    level: int
    status_keys: Tuple[int, ...] = ()
    buy_price_items: Tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateFacts:
    """What the validator needs to know about the chosen template item."""

    key: int
    internal_name: str
    #: EquipTypeInfo name (`OneHandSword`, `Helm`, ...); empty for non-equipment.
    equip_type_name: str = ""
    item_type: Optional[int] = None
    has_description: bool = True
    has_stat_block: bool = True
    #: The template's model family stem, e.g. `cd_phm_01_sword_0109`.
    model_stem: str = ""
    #: The prefab stems that belong to that family (`..._r`, `..._l`, ...), not borrowed ones.
    owned_stems: Tuple[str, ...] = ()
    levels: Tuple[TemplateLevelFacts, ...] = ()
    price_items: Tuple[int, ...] = ()
    max_stack_count: int = 1
    item_group_keys: Tuple[int, ...] = ()
    #: The Abyss Gear items the template embeds by default (its tooltip's perk lines).
    socket_items: Tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class NewItemContext:
    """A read-only snapshot of the archives, as far as a new item can collide with them."""

    template: TemplateFacts
    item_keys: FrozenSet[int] = frozenset()
    internal_names: FrozenSet[str] = frozenset()
    stringinfo_texts: FrozenSet[str] = frozenset()
    pappt_stems: FrozenSet[str] = frozenset()
    #: Model family stems that already have files under `character/model`.
    model_stems: FrozenSet[str] = frozenset()
    store_names: FrozenSet[str] = frozenset()
    #: store name -> internal names of the items currently in its stock.
    store_stock_names: Mapping[str, FrozenSet[str]] = field(default_factory=dict)
    localization_keys: FrozenSet[str] = frozenset()
    status_keys: FrozenSet[int] = frozenset()
    item_group_keys: FrozenSet[int] = frozenset()
    #: Item keys some shipped item embeds as a socket item (the Abyss Gear "perks").
    socket_item_keys: FrozenSet[int] = frozenset()
    #: Stems of the shipped effect binaries (`effect/binary__/releasebin/<stem>.pae`).
    effect_stems: FrozenSet[str] = frozenset()
    #: Capabilities of the current build; the rules refuse what the writers cannot do yet.
    store_insert_supported: bool = False
    stat_shape_edits_supported: bool = False


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.is_error for issue in issues)


def _issue(code: str, field_name: str, message: str, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(code=code, field=field_name, message=message, severity=severity)


# --------------------------------------------------------------------------- offline


def validate_spec(spec: NewItemSpec) -> Tuple[ValidationIssue, ...]:
    """Shapes, ranges and internal consistency; needs no archive access."""

    issues: list[ValidationIssue] = []
    name = str(spec.internal_name or "")
    if not name:
        issues.append(_issue("internal_name.empty", "internal_name", "Give the item an internal name."))
    elif not _INTERNAL_NAME_RE.match(name):
        issues.append(
            _issue("internal_name.shape", "internal_name", "Internal names are ASCII letters, digits and underscores, starting with a letter, at most 64 characters.")
        )

    if spec.template_key is None or int(spec.template_key) <= 0:
        issues.append(_issue("template.missing", "template_key", "Choose a template item."))

    if spec.item_key is not None and not (0 < int(spec.item_key) <= _U32_MAX):
        issues.append(_issue("item_key.range", "item_key", "Item keys are positive 32-bit integers."))

    if spec.stem is not None and not _STEM_RE.match(str(spec.stem)):
        issues.append(_issue("stem.shape", "stem", "Model stems are lowercase letters, digits and underscores, at most 64 characters, no path separators."))

    for field_name, value in (("name_key", spec.name_key), ("desc_key", spec.desc_key)):
        if value is not None and not _LOC_KEY_RE.match(str(value)):
            issues.append(_issue(f"{field_name}.shape", field_name, "Localisation keys are short ASCII identifiers."))
    if spec.name_key is not None and spec.desc_key is not None and spec.name_key == spec.desc_key:
        issues.append(_issue("desc_key.same_as_name", "desc_key", "The description key must differ from the name key."))
    if spec.item_key is not None and 0 < int(spec.item_key) <= _U32_MAX:
        for field_name, value, is_desc in (("name_key", spec.name_key, False), ("desc_key", spec.desc_key, True)):
            if value is not None and not is_conventional_localization_key(int(spec.item_key), str(value), description=is_desc):
                issues.append(_issue(f"{field_name}.unconventional", field_name, "The game derives this key from the item key; a different key is carried in the row but the name stays blank in game. Leave it unset to allocate the derived one.", "warning"))

    english = str(spec.display_names.get(REQUIRED_LANGUAGE, "") or "").strip()
    if not english:
        issues.append(_issue("names.english_missing", "display_names", "An English display name is required; other languages default to it."))
    for mapping_name, mapping in (("display_names", spec.display_names), ("descriptions", spec.descriptions)):
        for code, text in mapping.items():
            if code not in LOCALIZATION_LANGUAGES:
                issues.append(_issue("names.language_unknown", mapping_name, f"{code!r} is not one of the shipped language tables."))
            elif mapping_name == "display_names" and not str(text or "").strip():
                issues.append(_issue("names.empty", mapping_name, f"The {code} display name is empty; leave the language out to fall back to English.", "warning"))

    seen_stats: set[tuple[int, int]] = set()
    for edit in spec.stat_edits:
        if edit.level < 0:
            issues.append(_issue("stat.level", "stat_edits", f"Enchant level {edit.level} is negative."))
        if not _I32_MIN <= int(edit.value) <= _I32_MAX:
            issues.append(_issue("stat.range", "stat_edits", f"Stat values are signed 32-bit; {edit.value} is not."))
        if (edit.level, edit.status_key) in seen_stats:
            issues.append(_issue("stat.duplicate", "stat_edits", f"Level {edit.level} sets stat {edit.status_key} twice."))
        seen_stats.add((edit.level, edit.status_key))

    seen_buy: set[tuple[int, int]] = set()
    for edit in spec.buy_price_edits:
        if edit.level < 0:
            issues.append(_issue("buy_price.level", "buy_price_edits", f"Enchant level {edit.level} is negative."))
        if not 0 <= int(edit.price) <= _U32_MAX:
            issues.append(_issue("buy_price.range", "buy_price_edits", f"Prices are unsigned 32-bit; {edit.price} is not."))
        if (edit.level, edit.item_key) in seen_buy:
            issues.append(_issue("buy_price.duplicate", "buy_price_edits", f"Level {edit.level} prices item {edit.item_key} twice."))
        seen_buy.add((edit.level, edit.item_key))

    seen_price: set[int] = set()
    for edit in spec.price_edits:
        if not 0 <= int(edit.price) <= _U32_MAX:
            issues.append(_issue("price.range", "price_edits", f"Prices are unsigned 32-bit; {edit.price} is not."))
        if edit.item_key in seen_price:
            issues.append(_issue("price.duplicate", "price_edits", f"Item {edit.item_key} is priced twice."))
        seen_price.add(edit.item_key)

    if spec.max_stack_count is not None and not (1 <= int(spec.max_stack_count) <= _U32_MAX):
        issues.append(_issue("max_stack.range", "max_stack_count", "Max stack count is a positive 32-bit integer."))

    if spec.effect is not None and not _EFFECT_RE.match(str(spec.effect)):
        issues.append(_issue("effect.shape", "effect", "An effect is named `<stem>.level.effect` (or `.action.effect`), the stem being a shipped `effect/binary__/releasebin/<stem>.pae`."))

    if spec.socket_items is not None:
        if any(not 0 < int(item) <= _U32_MAX for item in spec.socket_items):
            issues.append(_issue("sockets.range", "socket_items", "Socket items are positive 32-bit item keys."))
        if len(spec.socket_items) > MAX_SOCKET_ITEMS:
            issues.append(_issue("sockets.too_many", "socket_items", f"At most {MAX_SOCKET_ITEMS} socket items fit the row."))
        elif len(spec.socket_items) > MAX_SHIPPED_SOCKET_ITEMS:
            issues.append(_issue("sockets.unproven", "socket_items", f"No shipped item carries more than {MAX_SHIPPED_SOCKET_ITEMS} socket items; more is unproven in game.", "warning"))

    placement = spec.placement
    if placement.kind is PlacementKind.NONE:
        issues.append(_issue("placement.none", "placement", "No shop placement: the item will exist but nothing in the game hands it out.", "warning"))
    else:
        if not str(placement.store_name or "").strip():
            issues.append(_issue("placement.store_missing", "placement", "Choose a store."))
        if placement.kind is PlacementKind.SWAP and not str(placement.old_item_name or "").strip():
            issues.append(_issue("placement.old_item_missing", "placement", "Choose which stock entry the new item replaces."))
        if placement.price is not None and not 0 <= int(placement.price) <= _U32_MAX:
            issues.append(_issue("placement.price", "placement", "A placement price is a non-negative 32-bit integer."))
        if placement.kind is PlacementKind.INSERT and placement.price is not None:
            issues.append(_issue("placement.price_ignored", "placement", "StoreInfo entries carry no price of their own; the shop prices the item from its buy-price list, so this price is not written.", "warning"))

    if spec.item_groups is ItemGroupsChoice.EXPLICIT and not spec.explicit_item_groups:
        issues.append(_issue("item_groups.empty", "item_groups", "Explicit item groups were chosen but none were listed."))
    if spec.item_groups is ItemGroupsChoice.TEMPLATE and spec.explicit_item_groups:
        issues.append(_issue("item_groups.ignored", "item_groups", "The listed item groups are ignored while the template's groups are selected.", "warning"))

    return tuple(issues)


# --------------------------------------------------------------------------- against the archives


def _stem_family_taken(stem: str, context: NewItemContext) -> Optional[str]:
    if stem in context.model_stems:
        return "a model family with that stem already exists"
    if stem in context.pappt_stems or any(existing.startswith(stem + "_") for existing in context.pappt_stems):
        return "the part-prefab table already knows that stem"
    lower = stem.lower()
    if stem in context.stringinfo_texts or any(text.startswith(stem + "_") or text.lower().endswith("_" + lower) for text in context.stringinfo_texts):
        return "StringInfo already carries that stem"
    return None


def validate_against_context(spec: NewItemSpec, context: NewItemContext) -> Tuple[ValidationIssue, ...]:
    """Collisions and template fit; needs the archive snapshot. Runs after :func:`validate_spec`."""

    issues: list[ValidationIssue] = []
    template = context.template

    if int(spec.template_key) != int(template.key):
        issues.append(_issue("template.mismatch", "template_key", "The snapshot describes a different template than the spec names."))
        return tuple(issues)
    if context.item_keys and template.key not in context.item_keys:
        issues.append(_issue("template.unknown", "template_key", f"Item {template.key} is not in the table."))
    if not template.equip_type_name:
        issues.append(_issue("template.not_equipment", "template_key", f"{template.internal_name} has no equip type; only equipment can be cloned into a new item."))
    if not template.has_stat_block:
        issues.append(_issue("template.no_stat_block", "template_key", f"{template.internal_name}'s stat block did not decode; stats and prices cannot be edited on this template.", "warning"))

    name = str(spec.internal_name or "")
    if name and (name in context.internal_names or name.casefold() in {n.casefold() for n in context.internal_names}):
        issues.append(_issue("internal_name.taken", "internal_name", f"An item named {name} already exists."))
    if name and name == template.internal_name:
        issues.append(_issue("internal_name.same_as_template", "internal_name", "The clone needs its own internal name."))

    if spec.item_key is not None and int(spec.item_key) in context.item_keys:
        issues.append(_issue("item_key.taken", "item_key", f"Item key {spec.item_key} is already used."))

    if spec.stem is not None:
        stem = str(spec.stem)
        if template.model_stem and stem == template.model_stem:
            issues.append(_issue("stem.same_as_template", "stem", "The new model family needs its own stem."))
        else:
            reason = _stem_family_taken(stem, context)
            if reason:
                issues.append(_issue("stem.taken", "stem", f"Stem {stem} cannot be used: {reason}."))
        if not spec.needs_new_stem:
            issues.append(_issue("stem.unused", "stem", "A stem was given but the item keeps the template's model and icon, so it is not used.", "warning"))
    if spec.needs_own_family and not template.owned_stems:
        issues.append(_issue("template.no_owned_stems", "template_key", f"{template.internal_name} owns no prefab stems to clone (all of its parts are borrowed)."))
    if spec.effect is not None:
        stem = str(spec.effect).split(".", 1)[0]
        if context.effect_stems and stem not in context.effect_stems:
            issues.append(_issue("effect.unknown", "effect", f"No shipped effect is named {stem}."))
        issues.append(_issue("effect.unproven", "effect", "A weapon effect is grafted into the item's prefabs as an EffectComponent, the way the shipped thrown lightning spear carries one; unproven in game.", "warning"))

    for field_name, value in (("name_key", spec.name_key), ("desc_key", spec.desc_key)):
        if value is not None and str(value) in context.localization_keys:
            issues.append(_issue(f"{field_name}.taken", field_name, f"Localisation key {value} already exists."))
    if spec.desc_key is None and spec.name_key is not None and template.has_description:
        issues.append(_issue("desc_key.needed", "desc_key", "The template has a description; the clone needs a description key too (leave both keys unset to allocate them together).", "warning"))

    by_level = {facts.level: facts for facts in template.levels}
    for edit in spec.stat_edits:
        facts = by_level.get(edit.level)
        if context.status_keys and edit.status_key not in context.status_keys:
            issues.append(_issue("stat.unknown_status", "stat_edits", f"{edit.status_key} is not a StatusInfo key."))
        if facts is None or edit.status_key not in facts.status_keys:
            if not context.stat_shape_edits_supported:
                issues.append(_issue("stat.not_in_template", "stat_edits", f"Level {edit.level} of {template.internal_name} has no {edit.status_key} entry; adding stats needs the stat-block rebuild, which this build does not have."))
    for edit in spec.buy_price_edits:
        facts = by_level.get(edit.level)
        if (facts is None or edit.item_key not in facts.buy_price_items) and not context.stat_shape_edits_supported:
            issues.append(_issue("buy_price.not_in_template", "buy_price_edits", f"Level {edit.level} of {template.internal_name} has no buy price in item {edit.item_key}."))
    for edit in spec.price_edits:
        if edit.item_key not in template.price_items and not context.stat_shape_edits_supported:
            issues.append(_issue("price.not_in_template", "price_edits", f"{template.internal_name} has no price in item {edit.item_key}."))
    if spec.socket_items is not None:
        if not template.has_stat_block:
            issues.append(_issue("sockets.no_stat_block", "socket_items", f"{template.internal_name}'s stat block did not decode, so its socket items cannot be replaced."))
        if context.item_keys:
            unknown = [item for item in spec.socket_items if int(item) not in context.item_keys]
            if unknown:
                issues.append(_issue("sockets.unknown_item", "socket_items", f"Not item keys: {', '.join(str(k) for k in unknown)}."))
        if context.socket_item_keys:
            odd = [item for item in spec.socket_items if int(item) in context.item_keys and int(item) not in context.socket_item_keys]
            if odd:
                issues.append(_issue("sockets.not_gear", "socket_items", f"Not Abyss Gear socket items (nothing shipped embeds them): {', '.join(str(k) for k in odd)}.", "warning"))

    placement = spec.placement
    if placement.kind is not PlacementKind.NONE:
        store = str(placement.store_name or "")
        if context.store_names and store not in context.store_names:
            issues.append(_issue("placement.store_unknown", "placement", f"There is no store named {store}."))
        elif placement.kind is PlacementKind.SWAP:
            stock = context.store_stock_names.get(store)
            if stock is not None and str(placement.old_item_name or "") not in stock:
                issues.append(_issue("placement.old_item_not_in_store", "placement", f"{store} does not stock {placement.old_item_name}."))
        elif placement.kind is PlacementKind.INSERT and not context.store_insert_supported:
            issues.append(_issue("placement.insert_unsupported", "placement", "Adding a stock entry is not available in this build; swap an existing entry instead."))

    if spec.item_groups is ItemGroupsChoice.EXPLICIT and context.item_group_keys:
        unknown = [key for key in spec.explicit_item_groups if key not in context.item_group_keys]
        if unknown:
            issues.append(_issue("item_groups.unknown", "item_groups", f"Unknown item group key(s): {', '.join(str(k) for k in unknown)}."))
    if spec.enhancement is EnhancementRows.OWN:
        issues.append(_issue("enhancement.own_unproven", "enhancement", "Cloned enhancement rows are unproven in game; sharing the template's rows is the verified form.", "warning"))
    else:
        issues.append(_issue("enhancement.shared", "enhancement", "The item enhances through the template's own transition rows, which name the template.", "info"))
    if spec.icon is IconSource.GENERATED and spec.model_source is ModelSource.TEMPLATE:
        issues.append(_issue("icon.generated_for_template_model", "icon", "A generated icon on the template's model will look like the template's icon; that is allowed, but check it is what you want.", "info"))

    return tuple(issues)


__all__ = [
    "LOCALIZATION_LANGUAGES",
    "MAX_SHIPPED_SOCKET_ITEMS",
    "MAX_SOCKET_ITEMS",
    "REQUIRED_LANGUAGE",
    "NewItemContext",
    "TemplateFacts",
    "TemplateLevelFacts",
    "ValidationIssue",
    "has_errors",
    "validate_against_context",
    "validate_spec",
]
