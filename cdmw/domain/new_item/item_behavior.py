"""Closed item.behavior@1 values for the remaining ItemInfo authoring families.

Descriptors are application-owned storage contracts. Packages supply values,
never descriptors, offsets, reader addresses or executable expressions.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields
from math import isfinite
from typing import Mapping


def record(**members):
    return ('record', tuple(members.items()))


def sequence(value, maximum=256):
    return ('list', value, maximum)


def array(value, count):
    return ('array', value, count)


def optional(value):
    return ('optional', value)


LOCAL = record(category='u8', key='u64', text_key='text')
PAGE = record(left_texture='text', right_texture='text', left_knowledge='u32', right_knowledge='u32')
INSPECTION = record(item='u32', gimmick='u32', character='u32', spawn_reason_hash='u32', socket='text',
    speak_character='u32', target_tag='u32', reward_own_knowledge='bool', reward_knowledge='u32', description=LOCAL,
    board_key='u32', action_type='u8', gimmick_state_hash='u32', target_page='u32', left_page='bool',
    page_knowledge='u32', read_after_reward='bool', refer_to_left_page='bool', effect='u32', complete_effect='u32')
INSPECT_ACTION = record(action_hash='u32', catch_tag_hash='u32', catcher_socket='text', target_socket='text')
DROP = record(enchant_level='u16', socket_items=sequence('u32', 8),
    socket_materials=sequence(record(item='u32', count='u64'), 8), subitem='subitem', valid_sockets='u8', use_sockets='bool')
DOCKING = record(gimmick='u32', character='u32', item='u32', parent_socket='text', child_socket='text',
    docking_tags=array('u32', 4), equipment_slot='u16', spawn_distance='u32', equip_gimmick='bool',
    damage_parent='bool', body_part='bool', docking_type='u8', summoner_team='bool', player_only='bool',
    npc_only='u32', sync_break_parent='bool', hit_part='u8', detected_by_npc='bool', bag_docking='bool',
    collision='bool', disable_other_gimmick_collision='bool', slot_key='text', inherit_summoner='bool',
    summon_tags=array('u32', 4), animation_root_bone='text')
INVENTORY_CHANGE = record(event_type='u8', player_condition='u32', target_condition='u32', event_condition='u32', inventory='u16')
MONEY_UNIT = record(unit='u32', ui_component='text', minimum='u32', icon='u32', money_icon='u32', name=LOCAL, description=LOCAL)
MONEY = record(price_floor='u64', units=sequence(MONEY_UNIT))
ICON = record(icon='u32', highlight_icon='u32', check_sealed='bool', gimmick_states=sequence('u32'), check_usable='bool')
PREFAB = record(scale=array('f32', 3), prefabs=sequence('u32'), animations=sequence('u32'),
    equipment_slots=sequence('u16'), tribe_genders=sequence('u32'), docking_switch='u32',
    use_gimmick_prefab='bool', craft_material='bool', data_type='u8')

# wire name -> (complete ItemInfo field, storage shape, editor section)
BEHAVIOR_FIELDS = {
    'item_type': ('_itemType', 'u8', 'classification'),
    'category': ('_categoryInfo', 'u16', 'classification'),
    'equipment_type': ('_equipTypeInfo', 'u32', 'classification'),
    'material_key': ('_materialKey', 'u32', 'classification'),
    'material_match': ('_materialMatchInfo', 'u32', 'classification'),
    'item_groups': ('_itemGroupInfoList', sequence('u16'), 'classification'),
    'hackable_character_groups': ('_hackableCharacterGroupInfoList', sequence('u16'), 'classification'),
    'stage': ('_stageInfo', 'u32', 'classification'),
    'advice': ('_lookDetailGameAdviceInfoWrapper', 'u32', 'classification'),
    'mission': ('_lookDetailMissionInfo', 'u32', 'classification'),
    'broken_prefix': ('_brokenItemPrefixString', 'u32', 'metadata'),
    'memo': ('_itemMemo', 'text', 'metadata'), 'filter_type': ('_filterType', 'text', 'metadata'),
    'default_texture': ('_defaultTexturePath', 'text', 'metadata'), 'emoji_texture': ('_emojiTextureID', 'text', 'metadata'),
    'drop_stat_type': ('_applyDropStatType', 'u8', 'drops'),
    'drop_defaults': ('_dropDefaultData', DROP, 'drops'),
    'default_subitem': ('_defaultSubItem', 'subitem', 'drops'),
    'discard_y_bits': ('_discardOffsetY', 'u32', 'drops'),
    'discard_attach_terrain': ('_discardAttachTerrain', 'bool', 'drops'),
    'fixed_pages': ('_fixedPageDataList', sequence(PAGE), 'inspection'),
    'dynamic_pages': ('_dynamicPageDataList', sequence(PAGE), 'inspection'),
    'inspections': ('_inspectDataList', sequence(INSPECTION), 'inspection'),
    'inspect_action': ('_inspectAction', INSPECT_ACTION, 'inspection'),
    'docking': ('_dockingChildData', optional(DOCKING), 'interaction'),
    'inventory_change': ('_inventoryChangeData', optional(INVENTORY_CHANGE), 'interaction'),
    'money': ('_moneyTypeDefine', optional(MONEY), 'currency'),
    'icons': ('_itemIconList', sequence(ICON), 'presentation'),
    'prefabs': ('_prefabDataList', sequence(PREFAB), 'presentation'),
}
SUBITEM_TYPES = frozenset((0, 3, 9, 14, 15, 16, 17, 18, 255))


@dataclass(frozen=True, slots=True)
class ItemBehaviorSettings:
    fields: Mapping[str, object] = field(default_factory=dict)


def validate_value(shape, value):
    if isinstance(shape, str):
        if shape.startswith('u'):
            if type(value) is not int or not 0 <= value < 1 << int(shape[1:]):
                raise ValueError('Item behavior integer is outside its storage range.')
        elif shape == 'i64':
            if type(value) is not int or not -(1<<63) <= value < (1<<63):
                raise ValueError('Item behavior signed counter is outside its storage range.')
        elif shape == 'bool':
            if type(value) is not bool: raise ValueError('Item behavior flags require booleans.')
        elif shape == 'text':
            if type(value) is not str or '\0' in value or len(value.encode('utf-8')) > 4096:
                raise ValueError('Unsupported item behavior text.')
        elif shape == 'f32':
            if type(value) not in (int, float) or not isfinite(value) or abs(value) > 3.4028234663852886e38:
                raise ValueError('Prefab scale requires finite float32 values.')
        elif shape == 'subitem':
            if not isinstance(value, dict) or set(value) != {'type', 'value'} or type(value['type']) is not int or value['type'] not in SUBITEM_TYPES:
                raise ValueError('Unsupported default-subitem discriminator.')
            if value['type'] in (0, 3, 9): validate_value('u32', value['value'])
            elif value['value'] is not None: raise ValueError('An empty default subitem cannot carry a value.')
        else: raise ValueError('Unsupported application storage descriptor.')
        return
    kind = shape[0]
    if kind == 'optional':
        if value is not None: validate_value(shape[1], value)
    elif kind == 'record':
        if not isinstance(value, dict) or set(value) != {name for name, _shape in shape[1]}:
            raise ValueError('Unsupported item behavior record fields.')
        for name, child in shape[1]: validate_value(child, value[name])
    elif kind in ('array', 'list'):
        if not isinstance(value, list) or (len(value) != shape[2] if kind == 'array' else len(value) > shape[2]):
            raise ValueError('Unsupported item behavior list length.')
        for child in value: validate_value(shape[1], child)
    else: raise ValueError('Unsupported application storage descriptor.')


def decode_behavior_settings(data):
    if not isinstance(data, dict) or set(data) != {'fields'} or not isinstance(data['fields'], dict) or not data['fields']:
        raise ValueError('Item behavior requires a closed nonempty fields object.')
    for name, value in data['fields'].items():
        if name not in BEHAVIOR_FIELDS: raise ValueError('Unsupported item.behavior field.')
        validate_value(BEHAVIOR_FIELDS[name][1], value)
        if name in ('item_groups', 'hackable_character_groups') and len(set(value)) != len(value):
            raise ValueError('Duplicate item behavior group.')
        if name == 'money' and value is not None:
            if len({unit['unit'] for unit in value['units']}) != len(value['units']): raise ValueError('Duplicate currency unit.')
    return ItemBehaviorSettings(deepcopy(data['fields']))


def encode_behavior_settings(settings):
    if type(settings) is not ItemBehaviorSettings or tuple(row.name for row in fields(settings)) != ('fields',):
        raise ValueError('Unsupported item behavior settings type.')
    data = {'fields': deepcopy(dict(settings.fields))}
    decode_behavior_settings(data)
    return data
