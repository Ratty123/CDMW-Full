from dataclasses import replace
import struct

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_inventory import read_item_inventory, set_item_inventory
from cdmw.domain.new_item.item_inventory import (ItemInventorySettings, MaterialGroup, ReserveSlotTarget,
    BOOLEAN_FIELDS, INTEGER_FIELDS, LIST_FIELDS, PAIR_FIELDS, encode_inventory_settings, decode_inventory_settings)
from tests.item_layout_fixtures import full_item, counted


def inventory_fields():
    return {'_maxStackCount': struct.pack('<Q', (1 << 40) + 19), '_itemTagList': counted((9876, 5432)),
        '_consumableTypeList': counted((0, 0xffffffff)), '_useImmediately': b'\x01',
        '_applyMaxStackCap': b'\x01', '_quickSlotIndex': b'\xff', '_usableAlertType': b'\x07',
        '_hideFromInventoryOnPopItem': b'\x01', '_enableAlertSystemToUI': b'\x01',
        '_isHasItemUseDataInventoryBuff': b'\x01',
        '_transmutationMaterialItemList': counted((1001295,)),
        '_transmutationMaterialGimmickList': counted((700001,)),
        '_transmutationMaterialItemGroupList': struct.pack('<IHI', 1, 17010, 0xffffffff),
        '_reserveSlotTargetDataList': struct.pack('<III', 1, 800001, 900001)}


def inventory_choices():
    return ItemInventorySettings(max_stack_count=(1 << 64) - 1, apply_max_stack_cap=False,
        tags=(0, 0xffffffff), consumable_types=(), use_immediately=False, quick_slot_index=0,
        reserve_slots=(ReserveSlotTarget(800002, 0),), usable_alert_type=255, hide_on_pop=False,
        enable_alert_ui=False, inventory_buff=False, material_gimmicks=(700002,), material_items=(1001295,),
        material_groups=(MaterialGroup(17011, 1),))


@pytest.mark.parametrize('current', (False, True))
def test_inventory_edits_have_exact_declared_boundaries_and_full_width(current):
    raw = full_item(current=current, fields=inventory_fields())
    source = read_item_inventory(raw)
    assert source.max_stack_count == (1 << 40) + 19
    assert source.material_groups == (MaterialGroup(17010, 0xffffffff),)
    assert source.reserve_slots == (ReserveSlotTarget(800001, 900001),)
    choices = inventory_choices()
    result = set_item_inventory(raw, choices)
    assert read_item_inventory(result) == choices
    before, after = read_item_layout(raw), read_item_layout(result)
    assigned = set(BOOLEAN_FIELDS.values()) | {row[0] for row in INTEGER_FIELDS.values()} | set(LIST_FIELDS.values()) | set(PAIR_FIELDS.values())
    assert all(before.data(name) == after.data(name) for name in before.fields if name not in assigned)
    assert after.data('_maxStackCount') == b'\xff' * 8
    assert after.data('_transmutationMaterialItemGroupList') == struct.pack('<IHI', 1, 17011, 1)
    # Every field, including unrelated nonempty enhancement data, survives resizing.
    only_tags = set_item_inventory(raw, ItemInventorySettings(tags=()))
    assert read_item_inventory(only_tags) == replace(source, tags=())
    assert set_item_inventory(result, ItemInventorySettings(max_stack_count=1))[after.fields['_maxStackCount'].start:after.fields['_maxStackCount'].start+8] == struct.pack('<Q', 1)


@pytest.mark.parametrize('name,value', (('max_stack_count', 0), ('max_stack_count', 1 << 64),
    ('max_stack_count', True), ('quick_slot_index', 256), ('usable_alert_type', -1), ('use_immediately', 1),
    ('tags', (1, 1)), ('consumable_types', (-1,)), ('material_items', (0,)),
    ('tags', tuple(range(257))), ('material_groups', (MaterialGroup(65536, 1),)),
    ('material_groups', (MaterialGroup(1, 0), MaterialGroup(1, 2))),
    ('reserve_slots', (ReserveSlotTarget(0, 1),)), ('reserve_slots', (ReserveSlotTarget(1, 0),) * 2)))
def test_inventory_wire_rejects_out_of_range_values_and_duplicates(name, value):
    with pytest.raises(ValueError):
        encode_inventory_settings(replace(ItemInventorySettings(), **{name: value}))


def test_inventory_wire_is_closed_and_distinguishes_inherit_false_zero_and_clear():
    choice = ItemInventorySettings(tags=(), use_immediately=False, quick_slot_index=0)
    data = encode_inventory_settings(choice)
    assert decode_inventory_settings(data) == choice
    assert data['tags'] == [] and data['consumable_types'] is None
    for altered in ({**data, 'future': 1}, {key: value for key, value in data.items() if key != 'tags'},
                    {**data, 'tags': [True]}, {**data, 'material_groups': [{'group_key': 1, 'value': 0, 'future': 1}]}):
        with pytest.raises(ValueError):
            decode_inventory_settings(altered)
    with pytest.raises(ValueError):
        encode_inventory_settings(ItemInventorySettings())
    with pytest.raises(ValueError):
        set_item_inventory(full_item()[:-1], choice)
