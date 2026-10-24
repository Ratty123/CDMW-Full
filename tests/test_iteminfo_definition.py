from copy import deepcopy
import struct

import pytest

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_definition import read_definition_fields, set_definition_fields, decode_local_string
from cdmw.domain.new_item.item_definition import ItemDefinitionSettings, encode_definition_settings, decode_definition_settings
from tests.item_layout_fixtures import full_item, counted


def _text(text):
    raw = text.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def sealable(kind, target, *, item=1001295, count=1 << 40):
    prefix = struct.pack('<BIQ', kind, item, count)
    return prefix + (_text(target) if kind == 2 else b'' if kind == 5 else struct.pack('<I', target))


def definition_fields(current=True):
    # Independent bytes for every variable-width family, including every seal target.
    stats = (struct.pack('<IIq', 1, 1000002, -(1 << 63)) + struct.pack('<IIq', 1, 1000003, (1 << 63) - 1)
             + struct.pack('<IIq', 1, 1000002, 1 << 40) + struct.pack('<IIB', 1, 1000003, 255))
    parameter = b'\x09' + struct.pack('<BQ', 7, (1001295 << 32) | 0x72) + _text(str((1001295 << 32) | 0x72))
    faction = b'\x01' + struct.pack('<IIQQQ', 1, 1001295, 1 << 40, 0, (1 << 64) - 1)
    faction += struct.pack('<IIQQQ', 1, 15, 7, 1, 15) + (struct.pack('<I', 0xffffffff) if current else b'')
    fields = {
        '_knowledgeInfo': struct.pack('<I', 600001), '_knowledgeObtainType': b'\x04',
        '_itemDesc2': struct.pack('<BQ', 7, (1001295 << 32) | 0x72) + _text(str((1001295 << 32) | 0x72)),
        '_packedItemInfo': struct.pack('<I', 1000214), '_unpackedItemInfo': struct.pack('<I', 1000215),
        '_convertItemInfoByDropNPC': struct.pack('<I', 1000216),
        '_itemBundleDataList': struct.pack('<IQI', 1, (1 << 64) - 1, 700001), '_isDyeable': b'\x01',
        '_occupiedEquipSlotDataList': struct.pack('<III', 1, 123456, 2) + b'\x00\xff',
        '_equipAbleHash': struct.pack('<I', 0xffffffff), '_sharpnessData': struct.pack('<HH', 65535, 4321) + stats,
        '_mapIconPath': struct.pack('<I', 1234567897), '_useMapIconAlert': b'\x01',
        '_itemEffectInfo': struct.pack('<I', 500001), '_destroyEffecInfo': struct.pack('<I', 500002),
        '_patternDescriptionDataList': struct.pack('<III', 1, 800001, 1) + parameter,
        '_gimmickInfo': struct.pack('<I', 700002), '_gimmickTagList': struct.pack('<I', 2) + _text('source_tag') + _text('材料'),
        '_sealableItemInfoList': struct.pack('<I', 2) + sealable(0, 1000220) + sealable(2, 'source_tag'),
        '_sealableCharacterInfoList': struct.pack('<I', 1) + sealable(3, 900001),
        '_sealableGimmickInfoList': struct.pack('<I', 1) + sealable(1, 700003),
        '_sealableGimmickTagList': struct.pack('<I', 1) + sealable(5, None),
        '_sealableTribeInfoList': struct.pack('<I', 1) + sealable(4, 101),
        '_sealableMoneyInfoList': counted((0, 0xffffffff)), '_factionManagementData': faction,
        '_itemPushInventoryContentsType': b''.join(struct.pack('<H', n) for n in range(10 if current else 9)),
        '_respawnTimeSeconds': struct.pack('<Q', (1 << 64) - 1),
    }
    return fields


@pytest.mark.parametrize('current', (False, True))
def test_six_definition_families_decode_and_round_trip_exact_bytes(current):
    raw = full_item(current=current, fields=definition_fields(current))
    data = read_definition_fields(raw)
    assert data['knowledge_key'] == 600001 and data['dyeable'] is True
    assert data['bundles'] == [{'minimum': (1 << 64) - 1, 'gimmick': 700001}]
    assert data['occupied_slots'] == [{'name_hash': 123456, 'indexes': [0, 255]}]
    assert data['sharpness']['maximum'][0]['value'] == -(1 << 63)
    assert data['sharpness']['parameters'] == [{'stat': 1000003, 'value': 255}]
    assert data['pattern_descriptions'][0]['parameters'][0]['key'] == (1001295 << 32) | 0x72
    assert data['sealable_items'][1]['target'] == 'source_tag'
    assert data['sealable_tags'][0]['target'] is None
    assert data['sealable_characters'][0]['target'] == 900001
    assert data['sealable_tribes'][0]['target'] == 101
    assert data['faction']['tier'] == (0xffffffff if current else None)
    assert data['faction']['costs'][0]['maximum'] == (1 << 64) - 1
    assert set_definition_fields(raw, data) == raw
    assert decode_local_string(read_item_layout(raw).data('_itemDesc2'))['text_key'] == str((1001295 << 32) | 0x72)


@pytest.mark.parametrize('current', (False, True))
def test_definition_resizing_and_false_zero_clear_preserve_every_unassigned_field(current):
    raw = full_item(current=current, fields=definition_fields(current))
    values = {'dyeable': False, 'knowledge_key': 0, 'bundles': [], 'occupied_slots': [],
              'sealable_items': [{'target_type': 2, 'item': 1001295, 'count': 0, 'target': 'A_longer_材料_tag'}],
              'respawn_value': 0, 'pattern_descriptions': []}
    output = set_definition_fields(raw, values)
    actual = read_definition_fields(output)
    assert all(actual[name] == value for name, value in values.items())
    before, after = read_item_layout(raw), read_item_layout(output)
    assigned = {'_isDyeable', '_knowledgeInfo', '_itemBundleDataList', '_occupiedEquipSlotDataList',
                '_sealableItemInfoList', '_respawnTimeSeconds', '_patternDescriptionDataList'}
    assert all(before.data(name) == after.data(name) for name in before.fields if name not in assigned)


@pytest.mark.parametrize('name,value', (('knowledge_key', True), ('dyeable', 1), ('respawn_value', 1 << 64),
    ('unknown', 0), ('occupied_slots', [{'name_hash': 1, 'indexes': [256]}]),
    ('bundles', [{'minimum': -1, 'gimmick': 1}]),
    ('sealable_items', [{'target_type': 5, 'item': 1, 'count': 0, 'target': 1}]),
    ('sealable_items', [{'target_type': 6, 'item': 1, 'count': 0, 'target': 1}]),
    ('inventory_routing', [0] * 11), ('pattern_descriptions', [{'pattern': 1, 'future': 0, 'parameters': []}]),
    ('gimmick_tags', ['same', 'same'])))
def test_definition_wire_refuses_unknown_fields_wrong_types_overflow_and_duplicates(name, value):
    with pytest.raises(ValueError):
        encode_definition_settings(ItemDefinitionSettings({name: value}))


def test_definition_wire_is_closed_and_copies_mutable_inputs():
    data = {'fields': {'bundles': []}, 'secondary_description': {'source_item': None, 'texts': {}}}
    settings = decode_definition_settings(data)
    data['fields']['bundles'].append({'minimum': 1, 'gimmick': 2})
    assert encode_definition_settings(settings)['fields']['bundles'] == []
    with pytest.raises(ValueError): decode_definition_settings({'fields': {}, 'secondary_description': None})
    with pytest.raises(ValueError): decode_definition_settings(dict(data, future=1))


def test_definition_generation_mismatches_and_unknown_seal_variants_refuse():
    raw = full_item(current=False, fields=definition_fields(False))
    with pytest.raises(ValueError, match='routing length'):
        set_definition_fields(raw, {'inventory_routing': [0] * 10})
    faction = deepcopy(read_definition_fields(raw)['faction']); faction['tier'] = 0
    with pytest.raises(ValueError, match='Faction tier'):
        set_definition_fields(raw, {'faction': faction})
    with pytest.raises(ValueError, match='Unknown|Unsupported'):
        replace_layout_fields(read_item_layout(raw), {'_sealableItemInfoList': struct.pack('<I', 1) + sealable(6, 1)})
