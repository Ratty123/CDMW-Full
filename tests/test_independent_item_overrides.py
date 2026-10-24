from copy import deepcopy
from uuid import uuid4

import pytest

from cdmw.core.iteminfo_declared_fields import read_field
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_operations import from_declared_iteminfo_operations,from_iteminfo_operations
from cdmw.services.independent_item_package import package_bytes,read_package,package_metadata
from cdmw.services.independent_item_install import prepare_install,prepare_rebuild,prepare_remove,load_registry
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_independent_item_behavior import behavior_game,definition_game,extended_game
from tests.test_independent_items import setup_game
from tests.test_independent_item_fields import virtual_row
from tests.test_archive_overlay_manager import Backups,snapshot_of
from tests.test_virtual_loader import game_bytes
from tests.test_iteminfo_overrides import declared


def package(snapshot,family,name,value,identity=None):
    raw=snapshot.rows[1001295].raw
    return from_declared_iteminfo_operations(snapshot,identity or uuid4().hex,'Stock '+name,[declared(raw,family,name,value)])


@pytest.mark.parametrize('virtual',(False,True))
@pytest.mark.parametrize('reverse',(False,True))
def test_variable_stock_fields_compose_rebuild_remove_and_allocate_no_items(tmp_path,behavior_game,virtual,reverse):
    _,snapshot,_=setup_game(tmp_path/'author')
    packages=[package(snapshot,'behavior','memo','A longer owned stock memo'),
              package(snapshot,'inventory','tags',[1,2,0xffffffff])]
    assert package_metadata(read_package(package_bytes(packages[0])))['requires']=={'item.overrides':1}
    setup_game(tmp_path/'recipient'); root=tmp_path/'recipient/game'; before=game_bytes(root)
    chosen=packages[::-1] if reverse else packages
    if virtual:
        paths=[]
        for value in chosen:
            path=tmp_path/(value.identity+'.cditem'); path.write_bytes(package_bytes(value)); paths.append(path)
        profile=VirtualProfile(tuple(paths)); prepared=prepare_profile(profile,root); publish_profile(prepared)
        raw=virtual_row(root).raw
        assert dict(prepare_profile(profile,root).files)==dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile((next(path for path in paths if path.stem==packages[1].identity),)),root))
        assert read_field(virtual_row(root).raw,('behavior','memo'))==read_field(snapshot.rows[1001295].raw,('behavior','memo'))
        publish_profile(prepare_profile(VirtualProfile(()),root))
    else:
        backups=Backups(tmp_path); backups.apply(prepare_install([package_bytes(p) for p in chosen],root).preparation)
        raw=snapshot_of(root).rows[1001295].raw
        backups.apply(prepare_rebuild(packages[0].identity,root).preparation)
        assert snapshot_of(root).rows[1001295].raw==raw
        backups.apply(prepare_remove(packages[0].identity,root))
        assert read_field(snapshot_of(root).rows[1001295].raw,('inventory','tags'))==[1,2,0xffffffff]
        backups.apply(prepare_remove(packages[1].identity,root))
    assert read_field(raw,('behavior','memo'))=='A longer owned stock memo'
    assert read_field(raw,('inventory','tags'))==[1,2,0xffffffff]
    registry=load_registry(root)
    assert all(not entry['values'] and not entry['paths'] and not entry['stem'] for entry in registry['items'].values())
    assert game_bytes(root)==before


def test_frozen_field_v1_does_not_accept_new_operations_and_new_admission_is_closed(tmp_path,behavior_game):
    _,snapshot,_=setup_game(tmp_path); raw=snapshot.rows[1001295].raw
    operation=declared(raw,'properties','required_level',123)
    with pytest.raises(IndependentItemError): from_iteminfo_operations(snapshot,uuid4().hex,'No v1 extension',[operation])
    value=from_declared_iteminfo_operations(snapshot,uuid4().hex,'Declared',[operation])
    for change in ('unknown','future','wrong_kind','offset'):
        meta=deepcopy(value.manifest)
        if change=='unknown': meta['modules'][0]['data']['operations'][0]['field']['name']='unknown'
        elif change=='future': meta['requires']['item.overrides']=meta['modules'][0]['version']=2
        elif change=='wrong_kind': meta['modules'][0]['data']['operations'][0]['kind']='field.assign'
        else: meta['modules'][0]['data']['operations'][0]['field']={'offset':10}
        with pytest.raises(IndependentItemError): read_v2(meta,{})


def test_changed_resources_and_missing_dependency_graph_refuse_before_recipient_writes(tmp_path,behavior_game):
    _,snapshot,_=setup_game(tmp_path/'author')
    value=package(snapshot,'behavior','memo','Pinned dependencies')
    assert 'ui/texture/left.dds' in value.dependencies
    setup_game(tmp_path/'recipient'); root=tmp_path/'recipient/game'; before=game_bytes(root)
    meta=deepcopy(value.manifest); del meta['dependencies']['ui/texture/left.dds']
    malformed=read_v2(meta,{})
    with pytest.raises(IndependentItemError,match='dependency graph'): prepare_install([package_bytes(malformed)],root)
    assert game_bytes(root)==before


@pytest.mark.parametrize('virtual',(False,True))
def test_borrowed_stock_records_are_protected_from_other_override_packages(tmp_path,behavior_game,virtual):
    _,snapshot,_=setup_game(tmp_path/'author')
    borrower=package(snapshot,'inventory','material_items',[1005300])
    editor=from_declared_iteminfo_operations(snapshot,uuid4().hex,'Edited material',[
        declared(snapshot.rows[1005300].raw,'properties','required_level',123)])
    setup_game(tmp_path/'recipient'); root=tmp_path/'recipient/game'; before=game_bytes(root)
    with pytest.raises(ValueError,match='requires this complete record unchanged'):
        if virtual:
            paths=[]
            for value in (borrower,editor):
                path=tmp_path/(value.identity+'.cditem'); path.write_bytes(package_bytes(value)); paths.append(path)
            prepare_profile(VirtualProfile(tuple(paths)),root)
        else: prepare_install([package_bytes(value) for value in (borrower,editor)],root)
    assert game_bytes(root)==before


def test_stock_disable_rebuild_and_enable_preserve_variable_field_intent(tmp_path,behavior_game):
    from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    _,snapshot,_=setup_game(tmp_path); root=tmp_path/'game'; backups=Backups(tmp_path)
    first=package(snapshot,'behavior','memo','Variable memo'); second=package(snapshot,'inventory','tags',[321])
    backups.apply(prepare_install([package_bytes(first),package_bytes(second)],root).preparation)
    registry=load_registry(root); layer=registry['items'][first.identity]['layer']
    backups.apply(prepare_overlay_enabled(root,layer,False)); backups.apply(prepare_overlay_rebuild(root))
    raw=snapshot_of(root).rows[1001295].raw
    assert read_field(raw,('behavior','memo'))==read_field(snapshot.rows[1001295].raw,('behavior','memo'))
    assert read_field(raw,('inventory','tags'))==[321]
    backups.apply(prepare_overlay_enabled(root,layer,True))
    assert read_field(snapshot_of(root).rows[1001295].raw,('behavior','memo'))=='Variable memo'


def test_unrelated_preparation_reads_do_not_expand_a_stock_packages_requirements(tmp_path,behavior_game):
    from cdmw.services.independent_item_operations import lower_field_operations
    _,snapshot,_=setup_game(tmp_path)
    value=package(snapshot,'behavior','memo','Scoped source receipts')
    assert 'owned/unused.bin' not in value.dependencies
    snapshot.payload('owned/unused.bin')
    assert lower_field_operations(value,snapshot,{})


def test_variable_stock_publication_failure_restores_exact_owned_archive_and_registry_bytes(tmp_path,behavior_game,monkeypatch):
    import cdmw.services.archive_overlay_manager as overlays
    from tests.test_independent_item_regressions import files_in
    _,snapshot,_=setup_game(tmp_path); root=tmp_path/'game'
    value=package(snapshot,'behavior','memo','A resized record requiring new directory offsets')
    preparation=prepare_install([package_bytes(value)],root).preparation
    before=files_in(root); original=overlays.atomic_write_bytes
    def fail(path,data):
        original(path,data)
        if path.name=='independent-items.json': raise OSError('injected stock publication failure')
    monkeypatch.setattr(overlays,'atomic_write_bytes',fail)
    with pytest.raises(OSError,match='injected stock'): Backups(tmp_path).apply(preparation)
    assert files_in(root)==before


def test_stock_studio_refuses_overlapping_stack_controls(tmp_path,behavior_game):
    from dataclasses import replace
    from cdmw.domain.new_item.item_inventory import ItemInventorySettings
    from cdmw.services.independent_item_operations import stock_item_operations
    from tests.test_archive_overlay_manager import shop_spec
    _,snapshot,_=setup_game(tmp_path)
    spec=replace(shop_spec('StockOverlap'),max_stack_count=7,inventory_settings=ItemInventorySettings(max_stack_count=8))
    with pytest.raises(ValueError,match='both legacy and inventory'): stock_item_operations(snapshot,spec)
