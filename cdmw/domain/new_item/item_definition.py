"""Closed item.definition@1 fields; earlier item capabilities remain frozen."""
from copy import deepcopy
from dataclasses import dataclass, field, fields
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ItemDefinitionSettings:
    fields: Mapping[str, object] = field(default_factory=dict)
    secondary_description: Mapping[str, object] | None = None


# These are source field locations and storage contracts, not gameplay enums.
# name -> (ItemInfo field, editor section)
FLAGS = {
    'dyeable': ('_isDyeable', 'flags'), 'editable_grime': ('_isEditableGrime', 'flags'),
    'housing_only': ('_isHousingOnly', 'flags'), 'reward_loot': ('_isRewardLootDrop', 'flags'),
    'equip_in_clone_actor': ('_enableEquipInCloneActor', 'flags'),
    'trade_market': ('_isRegisterTradeMarket', 'flags'), 'editor_usable': ('_isEditorUsable', 'flags'),
    'shield': ('_isShieldItem', 'flags'), 'tower_shield': ('_isTowerShieldItem', 'flags'),
    'wild': ('_isWild', 'flags'), 'preorder': ('_isPreorderItem', 'flags'),
    'average_price': ('_useAveragePrice', 'flags'),
    'save_on_use': ('_isSaveGameDataAtUseItem', 'flags'), 'logout_on_use': ('_isLogoutAtUseItem', 'flags'),
    'map_icon_alert': ('_useMapIconAlert', 'presentation'),
    'all_gimmicks_sealable': ('_isAllGimmickSealable', 'world'),
    'delete_on_gimmick_unlock': ('_deleteByGimmickUnlock', 'world'),
    'use_drop_target': ('_useDropSetTarget', 'world'),
}
# name -> (ItemInfo field, width, editor section, established reference table)
NUMBERS = {
    'knowledge_key': ('_knowledgeInfo', 4, 'text', 'knowledgeinfo'),
    'knowledge_obtain_type': ('_knowledgeObtainType', 1, 'text', None),
    'packed_item': ('_packedItemInfo', 4, 'links', 'iteminfo'),
    'unpacked_item': ('_unpackedItemInfo', 4, 'links', 'iteminfo'),
    'drop_npc_item': ('_convertItemInfoByDropNPC', 4, 'links', 'iteminfo'),
    'compatibility_hash': ('_equipAbleHash', 4, 'equipment', None),
    'map_icon': ('_mapIconPath', 4, 'presentation', None),
    'item_effect': ('_itemEffectInfo', 4, 'presentation', 'effectinfo'),
    'destroy_effect': ('_destroyEffecInfo', 4, 'presentation', 'effectinfo'),
    'gimmick_key': ('_gimmickInfo', 4, 'world', 'gimmickinfo'),
    'unlock_message': ('_gimmickUnlockMessageLocalStringInfo', 4, 'world', 'localstringinfo'),
    'max_drop_subitems': ('_maxDropResultSubItemCount', 4, 'world', None),
    'respawn_value': ('_respawnTimeSeconds', 8, 'world', None),
}
# name -> (ItemInfo field, closed value kind, editor section)
COLLECTIONS = {
    'bundles': ('_itemBundleDataList', 'bundles', 'links'),
    'occupied_slots': ('_occupiedEquipSlotDataList', 'slots', 'equipment'),
    'sharpness': ('_sharpnessData', 'sharpness', 'equipment'),
    'pattern_descriptions': ('_patternDescriptionDataList', 'patterns', 'presentation'),
    'gimmick_tags': ('_gimmickTagList', 'strings', 'world'),
    'sealable_items': ('_sealableItemInfoList', 'sealable', 'world'),
    'sealable_characters': ('_sealableCharacterInfoList', 'sealable', 'world'),
    'sealable_gimmicks': ('_sealableGimmickInfoList', 'sealable', 'world'),
    'sealable_tags': ('_sealableGimmickTagList', 'sealable', 'world'),
    'sealable_tribes': ('_sealableTribeInfoList', 'sealable', 'world'),
    'sealable_money': ('_sealableMoneyInfoList', 'u32s', 'world'),
    'inventory_routing': ('_itemPushInventoryContentsType', 'routing', 'world'),
    'faction': ('_factionManagementData', 'faction', 'world'),
}
SEAL_TARGETS = {0: 'iteminfo', 1: 'gimmickinfo', 2: 'tag', 3: 'characterinfo', 4: 'tribeinfo', 5: None}


def _integer(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Item definition integer is outside its range.')


def _text(value, limit=4096):
    if type(value) is not str or '\0' in value or len(value.encode('utf-8')) > limit:
        raise ValueError('Invalid item definition text.')


def _record(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Unsupported item definition record fields.')


def _list(value, limit=256):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('Unsupported item definition list.')


def _unique(rows, identity):
    seen = set()
    for row in rows:
        key = identity(row)
        if key in seen:
            raise ValueError('Duplicate item definition entry.')
        seen.add(key)


def _stat_list(value, parameter=False):
    _list(value)
    for row in value:
        _record(row, ('stat', 'value'))
        _integer(row['stat'], 0xffffffff, 1)
        _integer(row['value'], 255 if parameter else (1 << 63) - 1, 0 if parameter else -(1 << 63))
    _unique(value, lambda row: row['stat'])


def _localized(value, parameter=False):
    _record(value, ('kind', 'category', 'key', 'text_key') if parameter else ('category', 'key', 'text_key'))
    if parameter:
        _integer(value['kind'], 255)
    _integer(value['category'], 255)
    _integer(value['key'], (1 << 64) - 1)
    _text(value['text_key'])


def _collection(kind, value):
    if kind == 'sharpness':
        _record(value, ('limit', 'craft_tool', 'maximum', 'regeneration', 'static', 'parameters'))
        _integer(value['limit'], 65535)
        _integer(value['craft_tool'], 65535)
        for name in ('maximum', 'regeneration', 'static', 'parameters'):
            _stat_list(value[name], name == 'parameters')
        return
    if kind == 'faction':
        _record(value, ('valid', 'costs', 'prices', 'tier'))
        if type(value['valid']) is not bool:
            raise ValueError('Item faction validity requires a boolean.')
        if value['tier'] is not None:
            _integer(value['tier'], 0xffffffff)
        for name in ('costs', 'prices'):
            _list(value[name])
            for row in value[name]:
                _record(row, ('item', 'count', 'minimum', 'maximum'))
                _integer(row['item'], 0xffffffff, 1)
                for counter in ('count', 'minimum', 'maximum'):
                    _integer(row[counter], (1 << 64) - 1)
            _unique(value[name], lambda row: row['item'])
        return
    _list(value, 10 if kind == 'routing' else 8 if kind == 'slots' else 256)
    for row in value:
        if kind == 'bundles':
            _record(row, ('minimum', 'gimmick'))
            _integer(row['minimum'], (1 << 64) - 1)
            _integer(row['gimmick'], 0xffffffff, 1)
        elif kind == 'slots':
            _record(row, ('name_hash', 'indexes'))
            _integer(row['name_hash'], 0xffffffff, 1)
            _list(row['indexes'], 16)
            for index in row['indexes']:
                _integer(index, 255)
            _unique(row['indexes'], lambda index: index)
        elif kind == 'patterns':
            _record(row, ('pattern', 'parameters'))
            _integer(row['pattern'], 0xffffffff, 1)
            _list(row['parameters'], 64)
            for parameter in row['parameters']:
                _localized(parameter, True)
        elif kind == 'sealable':
            _record(row, ('target_type', 'item', 'count', 'target'))
            _integer(row['target_type'], 5)
            _integer(row['item'], 0xffffffff, 1)
            _integer(row['count'], (1 << 64) - 1)
            if row['target_type'] == 2:
                _text(row['target'], 1024)
            elif row['target_type'] == 5:
                if row['target'] is not None:
                    raise ValueError('An empty seal target cannot carry a payload.')
            else:
                _integer(row['target'], 0xffffffff)
        elif kind == 'strings':
            _text(row, 1024)
        else:
            _integer(row, 65535 if kind == 'routing' else 0xffffffff)
    if kind == 'routing':
        if len(value) not in (9, 10):
            raise ValueError('Inventory routing requires its complete source-generation array.')
    elif kind in ('slots', 'bundles', 'patterns'):
        _unique(value, lambda row: row[{'slots': 'name_hash', 'bundles': 'gimmick', 'patterns': 'pattern'}[kind]])
    elif kind in ('strings', 'u32s'):
        _unique(value, lambda row: row)
    elif kind == 'sealable':
        _unique(value, lambda row: (row['target_type'], row['item'], row['target']))


def decode_definition_settings(data):
    _record(data, ('fields', 'secondary_description'))
    values = data['fields']
    if not isinstance(values, dict) or set(values) - set(FLAGS) - set(NUMBERS) - set(COLLECTIONS):
        raise ValueError('Unsupported item.definition fields.')
    for name, value in values.items():
        if name in FLAGS:
            if type(value) is not bool:
                raise ValueError('Item definition flags require booleans.')
        elif name in NUMBERS:
            _integer(value, (1 << (8 * NUMBERS[name][1])) - 1)
        else:
            _collection(COLLECTIONS[name][1], value)
    text = data['secondary_description']
    if text is not None:
        _record(text, ('source_item', 'texts'))
        if text['source_item'] is not None:
            _integer(text['source_item'], 0xffffffff, 1)
        if not isinstance(text['texts'], dict) or len(text['texts']) > 32:
            raise ValueError('Unsupported secondary description translations.')
        for language, value in text['texts'].items():
            if type(language) is not str or not language or len(language) > 16:
                raise ValueError('Invalid secondary description language.')
            _text(value, 16384)
        if not text['texts'] and text['source_item'] is not None:
            raise ValueError('Clearing a secondary description cannot select a source item.')
    if not values and text is None:
        raise ValueError('Item definition requires an explicit override.')
    return ItemDefinitionSettings(deepcopy(values), deepcopy(text))


def encode_definition_settings(settings):
    if type(settings) is not ItemDefinitionSettings or tuple(row.name for row in fields(settings)) != ('fields', 'secondary_description'):
        raise ValueError('Unsupported item definition settings type.')
    data = {'fields': deepcopy(dict(settings.fields)), 'secondary_description': deepcopy(settings.secondary_description)}
    decode_definition_settings(data)
    return data
