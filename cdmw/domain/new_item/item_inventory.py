"""Closed item.inventory@1 overrides, independent of frozen recipe schemas."""
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class MaterialGroup:
    group_key: int
    value: int


@dataclass(frozen=True, slots=True)
class ReserveSlotTarget:
    slot_key: int
    condition_key: int


@dataclass(frozen=True, slots=True)
class ItemInventorySettings:
    max_stack_count: int | None = None
    apply_max_stack_cap: bool | None = None
    tags: tuple[int, ...] | None = None
    consumable_types: tuple[int, ...] | None = None
    use_immediately: bool | None = None
    quick_slot_index: int | None = None
    reserve_slots: tuple[ReserveSlotTarget, ...] | None = None
    usable_alert_type: int | None = None
    hide_on_pop: bool | None = None
    enable_alert_ui: bool | None = None
    inventory_buff: bool | None = None
    material_gimmicks: tuple[int, ...] | None = None
    material_items: tuple[int, ...] | None = None
    material_groups: tuple[MaterialGroup, ...] | None = None


BOOLEAN_FIELDS = {
    'apply_max_stack_cap': '_applyMaxStackCap', 'use_immediately': '_useImmediately',
    'hide_on_pop': '_hideFromInventoryOnPopItem', 'enable_alert_ui': '_enableAlertSystemToUI',
    'inventory_buff': '_isHasItemUseDataInventoryBuff',
}
INTEGER_FIELDS = {
    'max_stack_count': ('_maxStackCount', 8, 1, (1 << 64) - 1),
    'quick_slot_index': ('_quickSlotIndex', 1, 0, 255),
    'usable_alert_type': ('_usableAlertType', 1, 0, 255),
}
LIST_FIELDS = {
    'tags': '_itemTagList', 'consumable_types': '_consumableTypeList',
    'material_gimmicks': '_transmutationMaterialGimmickList',
    'material_items': '_transmutationMaterialItemList',
}
PAIR_FIELDS = {'reserve_slots': '_reserveSlotTargetDataList',
               'material_groups': '_transmutationMaterialItemGroupList'}
INVENTORY_FIELDS = ('max_stack_count', 'apply_max_stack_cap', 'tags', 'consumable_types',
    'use_immediately', 'quick_slot_index', 'reserve_slots', 'usable_alert_type', 'hide_on_pop',
    'enable_alert_ui', 'inventory_buff', 'material_gimmicks', 'material_items', 'material_groups')


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Item inventory value is outside its integer range.')


def decode_inventory_settings(data):
    if not isinstance(data, dict) or set(data) != set(INVENTORY_FIELDS):
        raise ValueError('Unsupported item.inventory fields.')
    values = dict(data)
    for name in BOOLEAN_FIELDS:
        if data[name] is not None and type(data[name]) is not bool:
            raise ValueError('Item inventory flags require booleans.')
    for name, (_field, _width, minimum, maximum) in INTEGER_FIELDS.items():
        if data[name] is not None:
            _integer(data[name], minimum, maximum)
    for name in (*LIST_FIELDS, *PAIR_FIELDS):
        rows = data[name]
        if rows is None:
            continue
        if not isinstance(rows, list) or len(rows) > 256:
            raise ValueError('Unsupported item inventory list.')
        parsed, seen = [], set()
        for row in rows:
            if name == 'reserve_slots':
                if not isinstance(row, dict) or set(row) != {'slot_key', 'condition_key'}:
                    raise ValueError('Unsupported reserve slot fields.')
                _integer(row['slot_key'], 1, 0xffffffff)
                _integer(row['condition_key'], 0, 0xffffffff)
                entry = ReserveSlotTarget(**row)
                identity = entry
            elif name == 'material_groups':
                if not isinstance(row, dict) or set(row) != {'group_key', 'value'}:
                    raise ValueError('Unsupported material group fields.')
                _integer(row['group_key'], 1, 65535)
                _integer(row['value'], 0, 0xffffffff)
                entry = MaterialGroup(**row)
                identity = entry.group_key
            else:
                _integer(row, 0 if name in ('tags', 'consumable_types') else 1, 0xffffffff)
                entry = identity = row
            if identity in seen:
                raise ValueError('Duplicate item inventory entry.')
            seen.add(identity)
            parsed.append(entry)
        values[name] = tuple(parsed)
    if all(value is None for value in values.values()):
        raise ValueError('Item inventory requires an explicit override.')
    return ItemInventorySettings(**values)


def encode_inventory_settings(settings):
    if type(settings) is not ItemInventorySettings or tuple(field.name for field in fields(settings)) != INVENTORY_FIELDS:
        raise ValueError('Unsupported item inventory settings type.')
    data = {name: getattr(settings, name) for name in INVENTORY_FIELDS}
    for name in LIST_FIELDS:
        if data[name] is not None:
            data[name] = list(data[name])
    for name, cls, names in (('reserve_slots', ReserveSlotTarget, ('slot_key', 'condition_key')),
                              ('material_groups', MaterialGroup, ('group_key', 'value'))):
        if data[name] is not None:
            if any(type(row) is not cls for row in data[name]):
                raise ValueError('Unsupported item inventory entry type.')
            data[name] = [{key: getattr(row, key) for key in names} for row in data[name]]
    decode_inventory_settings(data)
    return data
