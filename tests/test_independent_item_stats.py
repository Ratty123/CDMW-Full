from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_stats import read_item_stats
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.item_settings import ItemSettings
from cdmw.domain.new_item.item_settings import QuantityEdit
from cdmw.domain.new_item.item_stats import ItemStatSettings, StatOverride, PassiveSkill
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package, unpack_recipe
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.new_item_settings import load_use_action, load_settings_index
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.item_layout_fixtures import use_action
from tests.item_stat_fixtures import stat_item
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.test_independent_item_settings import extended_game
from tests.test_independent_items import setup_game
from tests.test_new_item_service import TEMPLATE, _table4
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def stat_game(extended_game, monkeypatch):
    from tests import test_new_item_provenance as source
    original = source.current_files
    control = {'skill_name': 'OwnedPassive', 'missing_skill': False, 'missing_status': False}
    def files():
        result = original()
        base = 'gamedata/binarystaticinfo__/bin/'
        name = base + 'iteminfo.'
        body, header = result[name+'staticinfobody'], result[name+'staticinfoheader']
        sample = read_item_layout(stat_item())
        fields = {field:sample.data(field) for field in ('_enchantDataList', '_equipPassiveSkillList')}
        rows = [(entry.row_id, replace_layout_fields(read_item_layout(body[start:end]), fields).raw
                 if entry.row_id == TEMPLATE else body[start:end]) for entry,start,end in
                parse_pabgh_table(header,payload=body).row_spans(len(body))]
        result[name+'staticinfobody'],result[name+'staticinfoheader'] = _table4(rows)
        def named(key, text):
            data=text.encode('utf-8')
            return struct.pack('<II',key,len(data))+data+b'\0'
        rows=[(600002,named(600002,'OtherPassive'))]
        if not control['missing_skill']:
            rows.insert(0,(600001,named(600001,control['skill_name'])))
        if control.get('duplicate_skill'):
            rows.append((600001,named(600001,'AmbiguousPassive')))
        result[base+'skillinfo.staticinfobody'],result[base+'skillinfo.staticinfoheader'] = _table4(rows)
        if control['missing_status']:
            name=base+'statusinfo.'
            body,header=result[name+'staticinfobody'],result[name+'staticinfoheader']
            rows=[(entry.row_id,body[start:end]) for entry,start,end in
                  parse_pabgh_table(header,payload=body).row_spans(len(body)) if entry.row_id!=1000003]
            result[name+'staticinfobody'],result[name+'staticinfoheader']=_table4(rows)
        return result
    monkeypatch.setattr(source,'current_files',files)
    return control


def choices():
    return ItemStatSettings((StatOverride('regeneration',0,1000003,-(1<<40)),
        StatOverride('regeneration_max',1,1000002,(1<<63)-1),StatOverride('level_stat',1,1000003,255),
        StatOverride('regeneration',1,1000002,12),StatOverride('level_stat',0,1000003,None)),
        (PassiveSkill(600002,0xffffffff),))


@pytest.mark.parametrize('virtual',(False,True))
def test_stats_and_passives_compile_rebuild_remove_and_keep_frozen_recipe(tmp_path,stat_game,virtual):
    service,snapshot,_=setup_game(tmp_path/'author')
    assert load_settings_index(snapshot).skills  # The UI loads this before Build plan.
    plan=service.plan(replace(shop_spec('Stats'),stat_settings=choices()),snapshot,capture_independent=True)
    package=from_plan(plan,uuid4().hex)
    assert package_metadata(package)['requires']=={'item.legacy':1,'item.stats':1}
    assert unpack_recipe(read_package(package_bytes(package)))[0].stat_settings==choices()
    legacy=from_plan(replace(plan,spec=replace(plan.spec,stat_settings=None)),package.identity)
    assert package.recipe==legacy.recipe and package_metadata(legacy)['version']==1
    assert package.manifest['provenance']['source_digest']==legacy.digest
    with pytest.raises(IndependentItemError,match='v1'):
        encode(plan.spec)
    assert any(path.endswith('/skillinfo.staticinfobody') for path in package.dependencies)
    setup_game(tmp_path/'recipient')
    root=tmp_path/'recipient/game'
    before=game_bytes(root)
    if virtual:
        path=tmp_path/'stats.cditem';path.write_bytes(package_bytes(package))
        profile=VirtualProfile((path,))
        prepared=prepare_profile(profile,root);publish_profile(prepared)
        key=load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw=virtual_row(root,key).raw
        assert dict(prepare_profile(profile,root).files)==dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile(()),root))
    else:
        backups=Backups(tmp_path)
        backups.apply(prepare_install([package_bytes(package)],root).preparation)
        key=load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw=snapshot_of(root).rows[key].raw
        backups.apply(prepare_rebuild(package.identity,root).preparation)
        assert snapshot_of(root).rows[key].raw==raw
        backups.apply(prepare_remove(package.identity,root))
    assert game_bytes(root)==before
    stats,skills=read_item_stats(raw)
    values={(row.kind,row.level,row.key):row.value for row in stats}
    assert all(values.get((edit.kind,edit.level,edit.key))==edit.value for edit in choices().statistics)
    assert ('level_stat',0,1000003) not in values
    assert skills==choices().passive_skills


@pytest.mark.parametrize('missing',('missing_skill','missing_status'))
def test_missing_inherited_stat_or_passive_dependencies_refuse(tmp_path,stat_game,missing):
    stat_game[missing]=True
    service,snapshot,_=setup_game(tmp_path)
    choice=ItemStatSettings((StatOverride('level_stat',0,1000003,0),))
    with pytest.raises(ValueError,match='Missing .* dependency'):
        service.plan(replace(shop_spec('Missing'),stat_settings=choice),snapshot,capture_independent=True)


def test_changed_passive_definition_refuses_before_recipient_writes(tmp_path,stat_game):
    service,snapshot,_=setup_game(tmp_path/'author')
    package=from_plan(service.plan(replace(shop_spec('Pinned'),stat_settings=choices()),snapshot,
        capture_independent=True),uuid4().hex)
    stat_game['skill_name']='ChangedPassive'
    setup_game(tmp_path/'recipient');root=tmp_path/'recipient/game'
    before=game_bytes(root)
    with pytest.raises(IndependentItemError,match='dependenc|source|match'):
        prepare_install([package_bytes(package)],root)
    assert game_bytes(root)==before


def test_stats_combine_with_unchanged_property_v2_and_full_width_static_edits(tmp_path,stat_game):
    service,snapshot,_=setup_game(tmp_path)
    spec=replace(shop_spec('Combined'),stat_settings=choices(),
        item_settings=ItemSettings(quantities=(QuantityEdit('stat',1000002,1<<40,0),)))
    plan=service.plan(spec,snapshot,capture_independent=True)
    package=from_plan(plan,uuid4().hex)
    assert package_metadata(package)['requires']=={'item.legacy':1,'item.properties':2,'item.stats':1}
    decoded=unpack_recipe(read_package(package_bytes(package)))[0]
    assert decoded.item_settings==spec.item_settings and decoded.stat_settings==spec.stat_settings
    module=next(module for module in package.manifest['modules'] if module['type']=='item.properties')
    assert set(module['data'])=={'item_tier','required_level','max_durability','settings'}
    body=plan.loose_files[snapshot.iteminfo.payload_entry.path]
    header=plan.loose_files[snapshot.iteminfo.header_entry.path]
    raw=next(body[start:end] for row,start,end in parse_pabgh_table(header,payload=body).row_spans(len(body))
             if row.row_id==plan.spec.item_key)
    from cdmw.core.iteminfo_settings import read_item_settings
    assert next(row.value for row in read_item_settings(raw)[1] if (row.kind,row.level)==('stat',0))==1<<40


def test_duplicate_dependency_row_identities_refuse(tmp_path,stat_game):
    stat_game['duplicate_skill']=True
    service,snapshot,_=setup_game(tmp_path)
    with pytest.raises(ValueError,match='unqualified row identity'):
        service.plan(replace(shop_spec('Ambiguous'),stat_settings=ItemStatSettings(passive_skills=(PassiveSkill(600001,1),))),
                     snapshot,capture_independent=True)


@pytest.mark.parametrize('mutation',('extra','overflow','duplicate','orphan','downgrade'))
def test_stats_modules_refuse_malformed_duplicate_or_unsupported_versions(tmp_path,stat_game,mutation):
    service,snapshot,_=setup_game(tmp_path)
    package=from_plan(service.plan(replace(shop_spec('Wire'),stat_settings=choices()),snapshot,
        capture_independent=True),uuid4().hex)
    meta=deepcopy(package.manifest);module=meta['modules'][-1]
    if mutation=='extra':module['data']['raw_offset']=4
    elif mutation=='overflow':module['data']['statistics'][-1]['value']=256
    elif mutation=='duplicate':meta['modules'].append(dict(module,id='other_stats'))
    elif mutation=='orphan':meta['modules']=[module];meta['requires'].pop('item.legacy')
    else:meta['requires']['item.stats']=module['version']=2
    with pytest.raises(IndependentItemError):read_v2(meta,package.blobs)


@pytest.mark.parametrize('kind,payload,table',(
    (8,struct.pack('<IIB',600001,3,0),'skillinfo'),
    (7,struct.pack('<I',700001),'sublevelinfo'),
    (14,struct.pack('<III',700001,0,0),'characterinfo'),
))
def test_named_use_action_targets_are_checked_and_source_pinned(tmp_path,stat_game,monkeypatch,kind,payload,table):
    service,snapshot,_=setup_game(tmp_path)
    import cdmw.services.new_item_settings as settings
    original=settings._rows
    def rows(source,name,**kwargs):
        return {1000031:use_action(kind=kind,payload=payload)} if name=='itemuseinfo' else original(source,name,**kwargs)
    monkeypatch.setattr(settings,'_rows',rows)
    if table=='skillinfo':
        assert load_use_action(snapshot,1000031).kind==kind
        assert any(row.entry.path.endswith('/skillinfo.staticinfobody') for row in snapshot.provenance.capture().payloads)
    else:
        with pytest.raises(ValueError,match='no complete .* table|Missing .* dependency'):
            load_use_action(snapshot,1000031)
