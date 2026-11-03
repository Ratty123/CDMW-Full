"""Add player selectors to one unambiguous worn prefab, using item.behavior@1.

CharacterInfo in 1.0.0.3479 identifies Kliff/1, Damian/4 and Oongka/6 with
player_1, player_2 and player_3 respectively. These are player identities, not
body shapes. Selector presence does not prove model/rig or in-game support.
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
    if not entry['tribe_genders']:
        raise WearerSupportError('no_selectors')
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
    if not set(source[index]['tribe_genders']).issubset(current[index]['tribe_genders']):
        # A manually restricted override must not be silently broadened/reset.
        raise WearerSupportError('unsupported')
    return source, current, index


def wearer_support(row, settings, strings):
    source, current, index = _prefab_lists(row, settings)
    keys = {name: stringinfo_key(selector) for name, selector in PLAYER_SELECTORS.items()}
    return WearerSupport(
        frozenset(name for name, key in keys.items() if key in source[index]['tribe_genders']),
        frozenset(name for name, key in keys.items() if key in current[index]['tribe_genders']),
        frozenset(name for name, key in keys.items() if strings.get(key) == PLAYER_SELECTORS[name]),
    )


def set_wearer_support(row, settings, strings, character, enabled):
    support = wearer_support(row, settings, strings)
    if character not in support.available or type(enabled) is not bool:
        raise WearerSupportError('unsupported')
    if character in support.inherited and not enabled:
        raise WearerSupportError('inherited')
    source, current, index = _prefab_lists(row, settings)
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
