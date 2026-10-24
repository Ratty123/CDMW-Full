from copy import deepcopy
import struct

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings, encode_behavior_settings, decode_behavior_settings
from tests.item_layout_fixtures import full_item
from tests.item_behavior_fixtures import behavior_fields


@pytest.mark.parametrize('current',(False,True))
def test_independent_nonempty_behavior_families_round_trip_exactly(current):
    raw=full_item(current=current,fields=behavior_fields(current))
    value=read_behavior_fields(raw)
    assert value['fixed_pages'][0]['right_knowledge']==600002
    assert value['inspections'][0]['description']['key']==(1001295<<32)|0x77
    assert value['docking']['docking_tags']==[1,2,3,4]
    assert value['inventory_change']['inventory']==65535
    assert value['money']['units'][0]['unit']==42
    assert value['money']['price_floor']==(1<<64)-1
    assert value['icons'][0]['gimmick_states']==[333,444]
    assert value['prefabs'][0]['scale']==[1.25,0.5,-2.0]
    assert value['drop_defaults']['socket_materials'][0]['count']==(1<<64)-1
    assert value['default_subitem']=={'type':9,'value':700001}
    assert value['inspect_action']['catch_tag_hash']==(456 if current else 0)
    assert set_behavior_fields(raw,value)==raw


@pytest.mark.parametrize('current',(False,True))
def test_resize_clear_and_explicit_false_zero_preserve_all_unassigned_bytes(current):
    raw=full_item(current=current,fields=behavior_fields(current)); before=read_item_layout(raw)
    overrides={'memo':'Longer 日本語 memo','fixed_pages':[],'docking':None,'money':None,
               'discard_attach_terrain':False,'discard_y_bits':0,'default_subitem':{'type':17,'value':None}}
    output=set_behavior_fields(raw,overrides); after=read_item_layout(output)
    actual=read_behavior_fields(output)
    assert all(actual[name]==value for name,value in overrides.items())
    assigned={'_itemMemo','_fixedPageDataList','_dockingChildData','_moneyTypeDefine','_discardAttachTerrain','_discardOffsetY','_defaultSubItem'}
    assert all(before.data(name)==after.data(name) for name in before.fields if name not in assigned)


@pytest.mark.parametrize('name,value',(
    ('unknown',0),('item_type',256),('category',True),('discard_attach_terrain',1),
    ('fixed_pages',[{'left_texture':'x'}]),('docking',{'item':1}),
    ('default_subitem',{'type':254,'value':None}),('default_subitem',{'type':17,'value':1}),
    ('item_groups',[1,1]),('memo','x'*4097),('prefabs',[{}])))
def test_behavior_wire_is_closed_and_refuses_malformed_values(name,value):
    with pytest.raises(ValueError): encode_behavior_settings(ItemBehaviorSettings({name:value}))


def test_behavior_settings_copy_inputs_and_legacy_generation_refuses_new_member():
    data={'fields':{'fixed_pages':[]}}; value=decode_behavior_settings(data); data['fields']['fixed_pages'].append({})
    assert encode_behavior_settings(value)=={'fields':{'fixed_pages':[]}}
    with pytest.raises(ValueError): decode_behavior_settings(dict(data,extra=1))
    raw=full_item(current=False,fields=behavior_fields(False)); action=read_behavior_fields(raw)['inspect_action']; action['catch_tag_hash']=1
    with pytest.raises(ValueError,match='generation'): set_behavior_fields(raw,{'inspect_action':action})


@pytest.mark.parametrize('tag',(0,3,9,14,15,16,17,18,255))
def test_default_subitem_storage_dispatch_in_both_locations(tag):
    raw=full_item(); value=read_behavior_fields(raw)['drop_defaults']
    subitem={'type':tag,'value':123 if tag in (0,3,9) else None}; value['subitem']=subitem
    output=set_behavior_fields(raw,{'drop_defaults':value,'default_subitem':subitem})
    assert read_behavior_fields(output)['drop_defaults']['subitem']==subitem
    assert read_behavior_fields(output)['default_subitem']==subitem


@pytest.mark.parametrize('current',(False,True))
def test_clone_rebinds_complete_presentation_references_without_changing_conditions(current):
    from cdmw.core.iteminfo_row import parse_iteminfo_row,clone_iteminfo_row
    raw=full_item(current=current,fields=behavior_fields(current))
    before=read_behavior_fields(raw)
    clone=clone_iteminfo_row(parse_iteminfo_row(raw,structured=True),key=1990001,string_key='OwnedBehavior',
        name_key=str((1990001<<32)|0x70),desc_key=str((1990001<<32)|0x71),replace_hashes={111:999,222:888})
    after=read_behavior_fields(clone)
    assert after['icons'][0]==dict(before['icons'][0],icon=999,highlight_icon=888)
    assert after['prefabs'][0]==dict(before['prefabs'][0],prefabs=[999,112])
    assert after['inspections']==before['inspections']
    assert after['money']==before['money']
