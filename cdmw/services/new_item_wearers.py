"""Add player selectors to one unambiguous worn prefab, using item.behavior@1.

CharacterInfo in 1.0.0.3479 identifies Kliff/1, Damian/4 and Oongka/6 with
player_1, player_2 and player_3 respectively. These are player identities, not
body shapes. Selector presence does not prove model/rig or in-game support.

The player controls apply to humanoid equipment only. Gear for horses, pets,
ridable creatures, the dragon, ships, wagons and the war machine lists
creature or hull selectors; `template_wearers` describes those read-only, and
the player controls refuse them with `not_player_equipment`.
"""
from copy import deepcopy
from dataclasses import dataclass

from cdmw.core.iteminfo_behavior import read_behavior_fields
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings, encode_behavior_settings


PLAYER_SELECTORS = {'kliff': 'player_1', 'damiane': 'player_2', 'oongka': 'player_3'}


class WearerSupportError(ValueError):
    """A closed reason code for the guided control's localized explanation."""


@dataclass(frozen=True)
class WearerSupport:
    inherited: frozenset[str]
    selected: frozenset[str]
    available: frozenset[str]
    unrestricted: bool = False


def _worn_entry(prefabs):
    # Do not choose among gender/body variants or interpret other prefab roles.
    if any(p['data_type'] not in (0, 3) for p in prefabs):
        raise WearerSupportError('unsupported')
    worn = [i for i, p in enumerate(prefabs) if p['data_type'] == 0]
    if len(worn) != 1:
        raise WearerSupportError('ambiguous')
    index = worn[0]
    entry = prefabs[index]
    if not entry['prefabs'] or entry['use_gimmick_prefab'] or entry['craft_material']:
        raise WearerSupportError('unsupported')
    return index


def _prefab_lists(row, settings):
    if settings is not None:
        encode_behavior_settings(settings)
    equipment = settings.fields.get('equipment_type', row.equip_type_key) if settings is not None else row.equip_type_key
    if not row.equip_type_key or not equipment:
        raise WearerSupportError('not_equipment')
    source = read_behavior_fields(row.raw)['prefabs']
    current = settings.fields.get('prefabs', source) if settings is not None else source
    index = _worn_entry(source)
    if len(current) != len(source) or _worn_entry(current) != index:
        raise WearerSupportError('unsupported')
    original_selectors, selected = source[index]['tribe_genders'], current[index]['tribe_genders']
    if selected and (not original_selectors or not set(original_selectors).issubset(selected)):
        # A manually restricted override must not be silently broadened/reset.
        raise WearerSupportError('unsupported')
    return source, current, index


def template_wearer_kind(row, strings, *, equip_type=''):
    """The wearer kind of a template: from its slot name, else from its worn selectors.

    The selector fallback recognizes only ship hulls, wagons and horse breeds,
    which no humanoid template uses; pets and ridable creatures need the slot.
    """
    from cdmw.domain.new_item.wearer_kinds import KIND_PLAYER, non_humanoid_selector_kind, wearer_kind_for_slot

    if equip_type:
        kind = wearer_kind_for_slot(equip_type)
        if kind != KIND_PLAYER:
            return kind
    try:
        prefabs = read_behavior_fields(row.raw)['prefabs']
    except (ValueError, KeyError, TypeError):
        return KIND_PLAYER
    texts = [strings.get(selector, '') for entry in prefabs if entry['data_type'] == 0
             for selector in entry['tribe_genders']]
    return non_humanoid_selector_kind(texts) or KIND_PLAYER


@dataclass(frozen=True)
class TemplateWearers:
    """Read-only: who wears a template, for templates the player controls do not apply to."""

    kind: str
    families: tuple[str, ...]
    worn_entries: int
    unrestricted: bool


def template_wearers(row, settings, strings, *, equip_type=''):
    """Describe a template's wearers without changing anything.

    Every worn entry is read, so a horse armour with one model per breed lists
    all five breeds. Families are the selector names without their gender part
    (`verybigboat_large_none` is the `large` hull).
    """
    from cdmw.domain.new_item.wearer_kinds import selector_family

    if not row.equip_type_key:
        raise WearerSupportError('not_equipment')
    prefabs = read_behavior_fields(row.raw)['prefabs']
    if settings is not None and 'prefabs' in settings.fields:
        prefabs = settings.fields['prefabs']
    worn = [entry for entry in prefabs if entry['data_type'] == 0]
    families = []
    for entry in worn:
        for selector in entry['tribe_genders']:
            family = selector_family(strings.get(selector, '')).family or f'#{selector}'
            if family not in families:
                families.append(family)
    return TemplateWearers(template_wearer_kind(row, strings, equip_type=equip_type), tuple(families),
                           len(worn), bool(worn) and all(not entry['tribe_genders'] for entry in worn))


def _require_player_equipment(row, strings, equip_type):
    from cdmw.domain.new_item.wearer_kinds import KIND_PLAYER

    if template_wearer_kind(row, strings, equip_type=equip_type) != KIND_PLAYER:
        # Horse, pet, ship, wagon, dragon and war machine gear: adding a playable
        # character to it would be a model the character cannot wear.
        raise WearerSupportError('not_player_equipment')


def wearer_support(row, settings, strings, *, equip_type=''):
    if not row.equip_type_key:
        raise WearerSupportError('not_equipment')
    # Who wears it comes first: a horse armour with one model per breed is horse gear,
    # not an ambiguous humanoid template.
    _require_player_equipment(row, strings, equip_type)
    source, current, index = _prefab_lists(row, settings)
    keys = {name: stringinfo_key(selector) for name, selector in PLAYER_SELECTORS.items()}
    # An empty selector list is unrestricted, as used by CC's Equip All Armor.
    # Do not turn it into a restriction merely by clicking a character checkbox.
    if not current[index]['tribe_genders']:
        return WearerSupport(frozenset(keys), frozenset(keys), frozenset(keys), unrestricted=True)
    return WearerSupport(
        frozenset(name for name, key in keys.items() if key in source[index]['tribe_genders']),
        frozenset(name for name, key in keys.items() if key in current[index]['tribe_genders']),
        frozenset(name for name, key in keys.items() if strings.get(key) == PLAYER_SELECTORS[name]),
    )


def set_wearer_support(row, settings, strings, character, enabled, *, equip_type=''):
    support = wearer_support(row, settings, strings, equip_type=equip_type)
    if character not in support.available or type(enabled) is not bool:
        raise WearerSupportError('unsupported')
    if character in support.inherited and not enabled:
        raise WearerSupportError('inherited')
    source, current, index = _prefab_lists(row, settings)
    if not current[index]['tribe_genders']:
        return settings
    changed = deepcopy(current)
    selectors = changed[index]['tribe_genders']
    key = stringinfo_key(PLAYER_SELECTORS[character])
    if enabled and key not in selectors:
        selectors.append(key)
    elif not enabled:
        selectors[:] = [value for value in selectors if value != key]
    fields = deepcopy(dict(settings.fields)) if settings is not None else {}
    if changed == source:
        fields.pop('prefabs', None)
    else:
        fields['prefabs'] = changed
    result = ItemBehaviorSettings(fields) if fields else None
    if result is not None:
        encode_behavior_settings(result)
    return result
