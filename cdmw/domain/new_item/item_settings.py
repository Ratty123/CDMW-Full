"""Closed v2 item settings, separate from both frozen v1 recipe grammars."""
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class RepairEntry:
    resource_item: int
    repair_value: int
    repair_style: int
    resource_count: int


@dataclass(frozen=True, slots=True)
class QuantityEdit:
    kind: str
    key: int
    value: int
    level: int | None = None


@dataclass(frozen=True, slots=True)
class ItemSettings:
    repairs: tuple[RepairEntry, ...] | None = None
    blocked_store_sell: bool | None = None
    discardable: bool | None = None
    important_item: bool | None = None
    destroy_when_broken: bool | None = None
    preserved_on_extract: bool | None = None
    can_disassemble: bool | None = None
    extractable: bool | None = None
    extraction_reward: int | None = None
    minimum_extract_level: int | None = None
    use_actions: tuple[int, ...] | None = None
    cooldowns: tuple[int, int, int] | None = None
    charge_type: int | None = None
    maximum_charges: tuple[int, int, int] | None = None
    shared_cooldown_group: int | None = None
    quantities: tuple[QuantityEdit, ...] = ()


SETTINGS_FIELDS = ('repairs', 'blocked_store_sell', 'discardable', 'important_item', 'destroy_when_broken',
    'preserved_on_extract', 'can_disassemble', 'extractable', 'extraction_reward', 'minimum_extract_level',
    'use_actions', 'cooldowns', 'charge_type', 'maximum_charges', 'shared_cooldown_group', 'quantities')
BOOLEAN_FIELDS = SETTINGS_FIELDS[1:8]
SCALAR_FIELDS = {
    'extraction_reward': ('_extractAdditionalDropSetInfo', 4),
    'minimum_extract_level': ('_minimumExtractEnchantLevel', 2),
    'charge_type': ('_itemChargeType', 1),
    'shared_cooldown_group': ('_sharedCoolTimeGroupNameHash', 4),
}
POLICY_FIELDS = dict(zip(BOOLEAN_FIELDS, ('_isBlockedStoreSell', '_discardable', '_isImportantItem',
    '_isDestoryWhenBroken', '_isPreservedOnExtract', '_canDisassemble', '_isExtractAbleItem')))
REPAIR_FIELDS = ('resource_item', 'repair_value', 'repair_style', 'resource_count')
QUANTITY_FIELDS = ('kind', 'key', 'value', 'level')


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in {minimum}..{maximum}.')


def decode_settings(data):
    if not isinstance(data, dict) or set(data) != set(SETTINGS_FIELDS):
        raise ValueError('Unsupported item settings fields.')
    values = dict(data)
    for name in BOOLEAN_FIELDS:
        if values[name] is not None and type(values[name]) is not bool:
            raise ValueError(f'{name} must be a boolean or inherit.')
    for name, (_field, width) in SCALAR_FIELDS.items():
        if values[name] is not None:
            _integer(values[name], 0, (1 << (8 * width)) - 1, name)
    for name, maximum in (('cooldowns', (1 << 64) - 1), ('maximum_charges', 0xffffffff)):
        if values[name] is not None:
            if not isinstance(values[name], list) or len(values[name]) != 3:
                raise ValueError(f'{name} requires exactly three values.')
            for value in values[name]:
                _integer(value, 0, maximum, name)
            values[name] = tuple(values[name])
    if values['use_actions'] is not None:
        actions = values['use_actions']
        if not isinstance(actions, list) or len(actions) > 128:
            raise ValueError('Unsupported item-use action list.')
        for key in actions:
            _integer(key, 1, 0xffffffff, 'use action')
        if len(set(actions)) != len(actions):
            raise ValueError('Duplicate item-use action.')
        values['use_actions'] = tuple(actions)
    if values['repairs'] is not None:
        repairs = values['repairs']
        if not isinstance(repairs, list) or len(repairs) > 128:
            raise ValueError('Unsupported repair list.')
        parsed = []
        for row in repairs:
            if not isinstance(row, dict) or set(row) != set(REPAIR_FIELDS):
                raise ValueError('Unsupported repair entry.')
            for name, minimum, maximum in (('resource_item', 1, 0xffffffff), ('repair_value', 0, 65535),
                    ('repair_style', 0, 255), ('resource_count', 1, (1 << 64) - 1)):
                _integer(row[name], minimum, maximum, name)
            parsed.append(RepairEntry(**row))
        values['repairs'] = tuple(parsed)
    quantities = values['quantities']
    if not isinstance(quantities, list) or len(quantities) > 256:
        raise ValueError('Unsupported quantity edit list.')
    parsed, seen = [], set()
    for row in quantities:
        if not isinstance(row, dict) or set(row) != set(QUANTITY_FIELDS):
            raise ValueError('Unsupported item quantity fields.')
        kind, level = row['kind'], row['level']
        if kind not in ('price', 'buy_price', 'stat') or (kind == 'price') != (level is None):
            raise ValueError('Unsupported item quantity selector.')
        if level is not None:
            _integer(level, 0, 65535, 'quantity level')
        _integer(row['key'], 1, 0xffffffff, 'quantity key')
        minimum, maximum = (-(1 << 63), (1 << 63) - 1) if kind == 'stat' else (0, (1 << 64) - 1)
        _integer(row['value'], minimum, maximum, kind)
        identity = (kind, level, row['key'])
        if identity in seen:
            raise ValueError('Duplicate item quantity edit.')
        seen.add(identity)
        parsed.append(QuantityEdit(**row))
    values['quantities'] = tuple(parsed)
    if all(value is None or name == 'quantities' and not value for name, value in values.items()):
        raise ValueError('Item settings require an explicit override.')
    return ItemSettings(**values)


def encode_settings(settings):
    if type(settings) is not ItemSettings or tuple(field.name for field in fields(settings)) != SETTINGS_FIELDS:
        raise ValueError('Unsupported item settings type or version.')
    result = {name: getattr(settings, name) for name in SETTINGS_FIELDS}
    for name in ('cooldowns', 'maximum_charges', 'use_actions'):
        if result[name] is not None:
            result[name] = list(result[name])
    if settings.repairs is not None:
        result['repairs'] = [{name: getattr(row, name) for name in REPAIR_FIELDS} for row in settings.repairs
                             if type(row) is RepairEntry]
        if len(result['repairs']) != len(settings.repairs):
            raise ValueError('Unsupported repair entry type.')
    result['quantities'] = [{name: getattr(row, name) for name in QUANTITY_FIELDS} for row in settings.quantities
                            if type(row) is QuantityEdit]
    if len(result['quantities']) != len(settings.quantities):
        raise ValueError('Unsupported quantity edit type.')
    decode_settings(result)
    return result
