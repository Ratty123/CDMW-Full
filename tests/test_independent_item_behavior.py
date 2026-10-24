from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_behavior import read_behavior_fields
from cdmw.core.paloc_format import parse_paloc, encode_paloc, add_localization_entries, entries_like
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package, unpack_recipe
from cdmw.services.independent_item_install import prepare_install, prepare_rebuild, prepare_remove, load_registry
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from cdmw.services.new_item_behavior import load_behavior_index
from tests.test_independent_item_definition import definition_game, SECONDARY, MAP_NAME, MAP_XML, MAP_DDS
from tests.test_independent_item_settings import extended_game
from tests.test_independent_items import setup_game
from tests.test_new_item_service import TEMPLATE, ICON_STRING, ICON, _table4
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.item_behavior_fixtures import behavior_fields, text
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def behavior_game(definition_game,monkeypatch):
    import tests.test_new_item_provenance as source
    original=source.current_files
    control={'missing':'','changed':'','blocked':'','duplicate':''}
    def files():
        result=original(); base='gamedata/binarystaticinfo__/bin/'
        body,header=result[base+'iteminfo.staticinfobody'],result[base+'iteminfo.staticinfoheader']
        rows=[]; category=equip=None; categories=set()
        for entry,start,end in parse_pabgh_table(header,payload=body).row_spans(len(body)):
            raw=body[start:end]
            if entry.row_id==TEMPLATE:
                layout=read_item_layout(raw); data=behavior_fields()
                # Preserve the actual fixture model family and known tables.
                for name in ('_itemType','_categoryInfo','_equipTypeInfo','_prefabDataList','_itemIconList'):
                    data[name]=layout.data(name)
                category=layout.integer('_categoryInfo'); equip=layout.integer('_equipTypeInfo')
                data['_itemGroupInfoList']=struct.pack('<IHH',2,17010,17011)
                data['_emojiTextureID']=text(MAP_NAME)
                # Reuse an existing qualified description namespace and references.
                data['_inspectDataList']=data['_inspectDataList'].replace(struct.pack('<I',600002),struct.pack('<I',600001))
                for field in ('_fixedPageDataList','_dynamicPageDataList'):
                    data[field]=data[field].replace(struct.pack('<I',600002),struct.pack('<I',600001))
                money=data['_moneyTypeDefine']
                from cdmw.core.stringinfo_table import stringinfo_key
                money=money.replace(struct.pack('<II',111,222),struct.pack('<II',stringinfo_key(MAP_NAME),stringinfo_key(MAP_NAME)))
                data['_moneyTypeDefine']=money
                raw=replace_layout_fields(layout,data).raw
                # The older definition fixture intentionally carries an unused
                # seal target. This fixture exercises the recursive graph.
                from cdmw.core.iteminfo_definition import read_definition_fields,set_definition_fields
                definitions=read_definition_fields(raw)
                definitions['sealable_items'][0]['target']=TEMPLATE
                raw=set_definition_fields(raw,{'sealable_items':definitions['sealable_items']})
            rows.append((entry.row_id,raw))
            try: categories.add(read_item_layout(raw).integer('_categoryInfo'))
            except ValueError: pass
        result[base+'iteminfo.staticinfobody'],result[base+'iteminfo.staticinfoheader']=_table4(rows)
        tables=(('categoryinfo',tuple(sorted(categories-{0})),2),('equiptypeinfo',(equip,),4),('charactergroupinfo',(4,5),2),
                ('stageinfo',(300001,),4),('gameadviceinfo',(300002,),4),('missioninfo',(300003,),4),
                ('conditioninfo',(400001,400002,400003),4))
        for table,keys,width in tables:
            rows=[]
            if base+table+'.staticinfobody' in result:
                data=result[base+table+'.staticinfobody']; head=result[base+table+'.staticinfoheader']
                rows=[(entry.row_id,data[start:end]) for entry,start,end in parse_pabgh_table(head,payload=data).row_spans(len(data)) if entry.row_id not in keys]
            for key in keys:
                if control['missing']==table:
                    key=key+1 if key<0xffffffff else key-1
                name=('Changed_' if control['changed']==table else 'Owned_')+table
                rows.append((key,key.to_bytes(width,'little')+text(name)+bytes([int(control['blocked']==table)])))
            if control['duplicate']==table: rows.append(rows[-1])
            result[base+table+'.staticinfobody'],result[base+table+'.staticinfoheader']=_table4(rows)
        for path in tuple(result):
            if path.endswith('.paloc'):
                table=parse_paloc(result[path]); key=str((TEMPLATE<<32)|0x77)
                result[path]=encode_paloc(add_localization_entries(table,entries_like(table,SECONDARY,{key:'Owned inspection'})))
        for name in ('left','right','default'):
            result[f'ui/texture/{name}.dds']=result[MAP_DDS]
        # Ordinary fixture icons also have an explicit, unambiguous registry entry.
        if not any(ICON_STRING.lower().encode() in raw.lower() for path,raw in result.items() if path.startswith('ui/xml/texture/') and path.endswith('.xml')):
            result['ui/xml/texture/behavior_icons.xml']=f'<Texture Name="{ICON_STRING}" Filename="{ICON}"/>'.encode()
        if control['changed']=='texture': result[MAP_XML]+=b'\n'
        if control['missing']=='texture': del result['ui/texture/left.dds']
        result['owned/unused.bin']=b'Unrelated source input'
        return result
    monkeypatch.setattr(source,'current_files',files)
    return control


def settings(snapshot):
    values=read_behavior_fields(snapshot.rows[TEMPLATE].raw)
    values['memo']='An independently authored memo'
    values['discard_attach_terrain']=False
    return ItemBehaviorSettings(values)


@pytest.mark.parametrize('virtual',(False,True))
def test_all_remaining_families_compile_package_rebuild_remove_and_keep_v1(tmp_path,behavior_game,virtual):
    service,snapshot,_=setup_game(tmp_path/'author')
    assert load_behavior_index(snapshot).choices['categoryinfo']
    selected=settings(snapshot)
    spec=replace(shop_spec('Behavior'),behavior_settings=selected)
    plan=service.plan(spec,snapshot,capture_independent=True)
    package=from_plan(plan,uuid4().hex)
    assert package.manifest['requires']=={'item.legacy':1,'item.behavior':1}
    assert unpack_recipe(read_package(package_bytes(package)))[0].behavior_settings==selected
    legacy=from_plan(replace(plan,spec=replace(plan.spec,behavior_settings=None)),package.identity)
    assert package_metadata(legacy)['version']==1 and legacy.recipe==package.recipe
    with pytest.raises(IndependentItemError,match='v1'): encode(spec)
    assert 'ui/texture/left.dds' in package.dependencies
    assert any(path.endswith('/conditioninfo.staticinfobody') for path in package.dependencies)
    setup_game(tmp_path/'recipient'); root=tmp_path/'recipient/game'; before=game_bytes(root)
    if virtual:
        path=tmp_path/'behavior.cditem'; path.write_bytes(package_bytes(package)); profile=VirtualProfile((path,))
        prepared=prepare_profile(profile,root); publish_profile(prepared)
        key=load_registry(root)['items'][package.identity]['values']['iteminfo']['item']; raw=virtual_row(root,key).raw
        assert dict(prepare_profile(profile,root).files)==dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile(()),root))
    else:
        backups=Backups(tmp_path); backups.apply(prepare_install([package_bytes(package)],root).preparation)
        key=load_registry(root)['items'][package.identity]['values']['iteminfo']['item']; raw=snapshot_of(root).rows[key].raw
        backups.apply(prepare_rebuild(package.identity,root).preparation)
        assert snapshot_of(root).rows[key].raw==raw
        backups.apply(prepare_remove(package.identity,root))
    assert read_behavior_fields(raw)==selected.fields
    assert game_bytes(root)==before


@pytest.mark.parametrize('missing',('categoryinfo','equiptypeinfo','charactergroupinfo','stageinfo','gameadviceinfo','missioninfo','conditioninfo','texture'))
def test_missing_remaining_dependencies_refuse(tmp_path,behavior_game,missing):
    behavior_game['missing']=missing
    service,snapshot,_=setup_game(tmp_path)
    with pytest.raises(ValueError): service.plan(replace(shop_spec('MissingBehavior'),behavior_settings=settings(snapshot)),snapshot)


def test_behavior_module_admission_remains_closed_and_required(tmp_path,behavior_game):
    service,snapshot,_=setup_game(tmp_path)
    package=from_plan(service.plan(replace(shop_spec('AdmissionBehavior'),behavior_settings=settings(snapshot)),snapshot,capture_independent=True),uuid4().hex)
    for change in ('unknown','duplicate','orphan','future','missing_capability'):
        meta=deepcopy(package.manifest); module=next(row for row in meta['modules'] if row['type']=='item.behavior')
        if change=='unknown': module['data']['fields']['future']=0
        elif change=='duplicate': meta['modules'].append(dict(module,id='another'))
        elif change=='orphan': meta['modules']=[module]
        elif change=='future': module['version']=meta['requires']['item.behavior']=2
        else: del meta['requires']['item.behavior']
        with pytest.raises(IndependentItemError): read_v2(meta,package.blobs)
