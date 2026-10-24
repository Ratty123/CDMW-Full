from copy import deepcopy
import hashlib

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_declared_fields import FIELDS, DEFINITION_ROOTS, field_root, read_field, write_field
from cdmw.domain.new_item.iteminfo_operations import compile_assignments,compose_assignments,ItemFieldConflict
from cdmw.domain.new_item.iteminfo_overrides import ADAPTER,decode_declared_assignment
from tests.item_layout_fixtures import full_item
from tests.item_behavior_fixtures import behavior_fields
from tests.test_iteminfo_operations import assignment


def declared(raw,family,name,value,identity='replace'):
    key=read_item_layout(raw).integer('_key')
    return {'id':identity,'kind':'field.replace','target':{'table':'ItemInfo','adapter':ADAPTER,'key':key},
        'field':{'family':family,'name':name},'value_type':'declared','expect':read_field(raw,(family,name)),
        'value':deepcopy(value),'precondition_base':'source','source_row':hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize('current',(False,True))
def test_all_declared_stock_field_readers_and_writers_preserve_exact_source_bytes(current):
    raw=full_item(current=current,fields=behavior_fields(current))
    for selector in list(FIELDS)+[('definition',name) for name in DEFINITION_ROOTS]:
        value=read_field(raw,selector)
        assert write_field(raw,selector,value)==raw,selector


def test_variable_stock_fields_compose_without_offsets_and_preserve_unassigned_fields():
    raw=full_item(); key=read_item_layout(raw).integer('_key'); rows={key:raw}
    operations=[declared(raw,'behavior','memo','A longer stock memo','memo'),
                declared(raw,'inventory','tags',[1,2,0xffffffff],'tags'),
                declared(raw,'inventory','max_stack_count',(1<<64)-1,'stack')]
    compiled=compile_assignments([('owner',operations)],rows)
    output=compose_assignments(rows,compiled)[key]
    assert read_field(output,('behavior','memo'))=='A longer stock memo'
    assert read_field(output,('inventory','max_stack_count'))==(1<<64)-1
    before,after=read_item_layout(raw),read_item_layout(output)
    assert all(before.data(name)==after.data(name) for name in before.fields if name not in ('_itemMemo','_itemTagList','_maxStackCount'))


def test_declared_and_legacy_assignments_detect_overlap_and_keep_disjoint_behavior():
    raw=full_item(); key=read_item_layout(raw).integer('_key'); rows={key:raw}
    legacy=assignment(raw,value=7); modern=declared(raw,'behavior','memo','Owned stock edit')
    for contributions in ([('old',[legacy]),('new',[modern])],[('new',[modern]),('old',[legacy])]):
        compiled=compile_assignments(contributions,rows); result=compose_assignments(rows,compiled)[key]
        assert read_field(result,('inventory','max_stack_count'))==7
        assert read_field(result,('behavior','memo'))=='Owned stock edit'
    modern=declared(raw,'inventory','max_stack_count',8)
    with pytest.raises(ItemFieldConflict): compile_assignments([('old',[legacy]),('new',[modern])],rows)
    modern=declared(raw,'inventory','max_stack_count',7)
    assert read_field(compose_assignments(rows,compile_assignments([('old',[legacy]),('new',[modern])],rows))[key],('inventory','max_stack_count'))==7


def test_declared_conflicts_source_changes_and_legacy_record_protection_refuse():
    raw=full_item(); key=read_item_layout(raw).integer('_key'); rows={key:raw}
    first=declared(raw,'behavior','memo','A'); second=declared(raw,'behavior','memo','B')
    with pytest.raises(ItemFieldConflict): compile_assignments([('one',[first]),('two',[second])],rows)
    with pytest.raises(ItemFieldConflict): compile_assignments([('one',[first])],rows,protected={key:['legacy']})
    changed=dict(first,expect='Wrong')
    with pytest.raises(ValueError): compile_assignments([('one',[changed])],rows)
    changed=dict(first,source_row='0'*64)
    with pytest.raises(ValueError): compile_assignments([('one',[changed])],rows)
    compiled=compile_assignments([('one',[first])],rows)
    with pytest.raises(ValueError): compose_assignments({key:raw+b'changed'},compiled)


@pytest.mark.parametrize('change',('unknown','offset','bool','future','identity'))
def test_declared_operations_are_closed_and_reject_unsafe_selectors(change):
    raw=full_item(); value=declared(raw,'properties','required_level',3)
    if change=='unknown': value['field']['name']='future'
    elif change=='offset': value['field']={'offset':44}
    elif change=='bool': value['value']=True
    elif change=='future': value['target']['adapter']='future'
    else: value['field']={'family':'behavior','name':'_key'}
    with pytest.raises(ValueError): decode_declared_assignment('owner',value)


@pytest.mark.parametrize('family,name,value',(
    ('inventory','tags',[1,1]),('inventory','material_items',[0]),
    ('settings','use_actions',[1,1]),('settings','repairs',[{'resource_item':1,'repair_value':0,'repair_style':0,'resource_count':0}]),
    ('stats','passive_skills',[{'skill_key':1,'level':1},{'skill_key':1,'level':2}]),
    ('progression','prices',[{'item':1,'amount':1,'symbol':0,'wrapper':2}]),
    ('behavior','money',{'price_floor':0,'units':[],'future':0})))
def test_stock_complete_fields_keep_existing_domain_constraints(family,name,value):
    with pytest.raises(ValueError): decode_declared_assignment('owner',declared(full_item(),family,name,value))


def test_stock_prefab_scale_is_verified_in_its_canonical_float32_storage():
    import struct
    raw=full_item(fields=behavior_fields()); key=read_item_layout(raw).integer('_key')
    prefabs=read_field(raw,('behavior','prefabs')); prefabs[0]['scale'][0]=1.1
    operations=compile_assignments([('owner',[declared(raw,'behavior','prefabs',prefabs)])],{key:raw})
    result=compose_assignments({key:raw},operations)[key]
    assert read_field(result,('behavior','prefabs'))[0]['scale'][0]==struct.unpack('<f',struct.pack('<f',1.1))[0]


def test_stock_primary_text_aliases_cannot_break_existing_row_readers():
    raw=full_item(); key=read_item_layout(raw).integer('_key')
    value=read_field(raw,('text','name')); value.update(key=(1005300<<32)|0x70,text_key=str((1005300<<32)|0x70))
    with pytest.raises(ValueError): compile_assignments([('owner',[declared(raw,'text','name',value)])],{key:raw})


@pytest.mark.parametrize('modern',(False,True))
def test_dispatch_preserves_single_use_contribution_and_compiled_iterators(modern):
    raw=full_item(); key=read_item_layout(raw).integer('_key')
    operation=declared(raw,'inventory','max_stack_count',7) if modern else assignment(raw,value=7)
    compiled=compile_assignments(((owner,operations) for owner,operations in [('owner',[operation])]),{key:raw})
    result=compose_assignments({key:raw},iter(compiled))[key]
    assert read_field(result,('inventory','max_stack_count'))==7


def test_dispatch_keeps_legacy_malformed_contribution_error_contract():
    from cdmw.domain.new_item.independent import IndependentItemError
    with pytest.raises(IndependentItemError): compile_assignments([('owner',None)],{})
