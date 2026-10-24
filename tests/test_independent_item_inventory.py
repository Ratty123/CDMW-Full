from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_inventory import read_item_inventory
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.item_inventory import ItemInventorySettings
from cdmw.domain.new_item.item_settings import ItemSettings
from cdmw.domain.new_item.item_stats import ItemStatSettings
from cdmw.domain.new_item.rules import validate_spec
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, unpack_recipe
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.test_independent_item_settings import extended_game, TEMPLATE
from tests.test_independent_items import setup_game
from tests.test_iteminfo_inventory import inventory_fields, inventory_choices
from tests.test_new_item_service import _table4
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def inventory_game(extended_game, monkeypatch):
    import tests.test_new_item_provenance as source
    original = source.current_files
    control = {'missing': '', 'name': 'Original', 'duplicate': False}
    def files(*args, **kwargs):
        result = original(*args, **kwargs)
        base = 'gamedata/binarystaticinfo__/bin/'
        payload, header = result[base+'iteminfo.staticinfobody'], result[base+'iteminfo.staticinfoheader']
        rows = []
        for entry, start, end in parse_pabgh_table(header, payload=payload).row_spans(len(payload)):
            raw = payload[start:end]
            if entry.row_id == TEMPLATE:
                raw = replace_layout_fields(read_item_layout(raw), inventory_fields()).raw
            rows.append((entry.row_id, raw))
        result[base+'iteminfo.staticinfobody'], result[base+'iteminfo.staticinfoheader'] = _table4(rows)
        if control.get('duplicate_group'):
            payload, header = result[base+'itemgroupinfo.staticinfobody'], result[base+'itemgroupinfo.staticinfoheader']
            groups = [(entry.row_id, payload[start:end]) for entry, start, end in
                parse_pabgh_table(header, payload=payload).row_spans(len(payload))]
            groups.append(next(group for group in groups if group[0] == 17011))
            result[base+'itemgroupinfo.staticinfobody'], result[base+'itemgroupinfo.staticinfoheader'] = _table4(groups)
        for table, keys in (('gimmickinfo', (700001, 700002)), ('reserveslotinfo', (800001, 800002)), ('conditioninfo', (900001,))):
            rows = [(key, struct.pack('<II', key, len(control['name'])) + control['name'].encode()) for key in keys]
            if control['missing'] == table:
                key = keys[-1] + 10
                rows = [(key, struct.pack('<II', key, 0))]
            if control['duplicate'] and table == 'reserveslotinfo':
                rows.append(rows[0])
            result[base+table+'.staticinfobody'], result[base+table+'.staticinfoheader'] = _table4(rows)
        return result
    monkeypatch.setattr(source, 'current_files', files)
    return control


@pytest.mark.parametrize('virtual', (False, True))
def test_inventory_round_trip_both_routes_rebuild_remove_and_frozen_recipe(tmp_path, inventory_game, virtual):
    service, snapshot, _ = setup_game(tmp_path/'author')
    choice = inventory_choices()
    plan = service.plan(replace(shop_spec('Inventory'), inventory_settings=choice), snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    assert package.manifest['requires'] == {'item.legacy': 1, 'item.inventory': 1}
    assert unpack_recipe(read_package(package_bytes(package)))[0].inventory_settings == choice
    old = from_plan(replace(plan, spec=replace(plan.spec, inventory_settings=None)), package.identity)
    assert old.recipe == package.recipe and package.manifest['provenance']['source_digest'] == old.digest
    with pytest.raises(IndependentItemError, match='v1'):
        encode(plan.spec)
    assert all(any(path.endswith('/'+table+'.staticinfobody') for path in package.dependencies)
               for table in ('gimmickinfo', 'reserveslotinfo'))
    setup_game(tmp_path/'recipient')
    root = tmp_path/'recipient/game'
    before = game_bytes(root)
    if virtual:
        path = tmp_path/'inventory.cditem'; path.write_bytes(package_bytes(package))
        profile = VirtualProfile((path,))
        prepared = prepare_profile(profile, root); publish_profile(prepared)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw = virtual_row(root, key).raw
        assert dict(prepare_profile(profile, root).files) == dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile(()), root))
    else:
        backups = Backups(tmp_path)
        backups.apply(prepare_install([package_bytes(package)], root).preparation)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw = snapshot_of(root).rows[key].raw
        backups.apply(prepare_rebuild(package.identity, root).preparation)
        assert snapshot_of(root).rows[key].raw == raw
        backups.apply(prepare_remove(package.identity, root))
    assert read_item_inventory(raw) == choice
    assert game_bytes(root) == before


@pytest.mark.parametrize('table', ('gimmickinfo', 'reserveslotinfo', 'conditioninfo'))
def test_missing_inherited_inventory_dependencies_refuse(tmp_path, inventory_game, table):
    inventory_game['missing'] = table
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='Missing .* dependency'):
        service.plan(replace(shop_spec('Missing'), inventory_settings=ItemInventorySettings(tags=())), snapshot)


def test_changed_inventory_dependency_refuses_before_writes(tmp_path, inventory_game):
    service, snapshot, _ = setup_game(tmp_path/'author')
    package = from_plan(service.plan(replace(shop_spec('Pinned'), inventory_settings=inventory_choices()),
        snapshot, capture_independent=True), uuid4().hex)
    inventory_game['name'] = 'Changed'
    setup_game(tmp_path/'recipient'); root = tmp_path/'recipient/game'
    before = game_bytes(root)
    with pytest.raises(IndependentItemError, match='dependenc|source|match'):
        prepare_install([package_bytes(package)], root)
    assert game_bytes(root) == before


def test_inventory_admission_is_closed_and_does_not_widen_old_schemas(tmp_path, inventory_game):
    service, snapshot, _ = setup_game(tmp_path)
    settings = inventory_choices()
    spec = replace(shop_spec('Combined'), inventory_settings=settings,
                   item_settings=ItemSettings(discardable=False), stat_settings=ItemStatSettings(passive_skills=()))
    package = from_plan(service.plan(spec, snapshot, capture_independent=True), uuid4().hex)
    assert package.manifest['requires'] == {'item.legacy': 1, 'item.properties': 2, 'item.stats': 1, 'item.inventory': 1}
    assert unpack_recipe(read_package(package_bytes(package)))[0].inventory_settings == settings
    for change in ('unknown', 'duplicate', 'orphan', 'missing_capability', 'future', 'overlap'):
        meta = deepcopy(package.manifest)
        module = next(row for row in meta['modules'] if row['type'] == 'item.inventory')
        if change == 'unknown': module['data']['future'] = 1
        elif change == 'duplicate': meta['modules'].append(dict(module, id='duplicate'))
        elif change == 'orphan': meta['modules'] = [module]
        elif change == 'missing_capability': del meta['requires']['item.inventory']
        elif change == 'future': module['version'] = meta['requires']['item.inventory'] = 2
        else:
            legacy = next(row for row in meta['modules'] if row['type'] == 'item.legacy')
            legacy['data']['spec']['fields']['max_stack_count'] = 3
        with pytest.raises(IndependentItemError): read_v2(meta, package.blobs)
    assert any(issue.field == 'inventory_settings' for issue in validate_spec(replace(spec, max_stack_count=2)))


@pytest.mark.parametrize('name,value', (('material_items', (4294967295,)), ('material_groups', None)))
def test_missing_material_item_or_group_refuses(tmp_path, inventory_game, name, value):
    from cdmw.domain.new_item.item_inventory import MaterialGroup
    service, snapshot, _ = setup_game(tmp_path)
    choice = replace(inventory_choices(), **{name: (MaterialGroup(65535, 0),) if value is None else value})
    with pytest.raises(ValueError, match='Missing .*material item|Missing or ambiguous itemgroupinfo'):
        service.plan(replace(shop_spec('Missing'), inventory_settings=choice), snapshot)


def test_duplicate_reserve_slot_table_identity_refuses(tmp_path, inventory_game):
    inventory_game['duplicate'] = True
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='unqualified row identity'):
        service.plan(replace(shop_spec('Duplicate'), inventory_settings=inventory_choices()), snapshot)


def test_duplicate_material_group_identity_refuses(tmp_path, inventory_game):
    inventory_game['duplicate_group'] = True
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='ambiguous itemgroupinfo dependency'):
        service.plan(replace(shop_spec('Duplicate'), inventory_settings=inventory_choices()), snapshot)


@pytest.mark.parametrize('table,field', (('gimmickinfo', 'material_gimmicks'),
    ('reserveslotinfo', 'reserve_slots'), ('conditioninfo', 'reserve_slots')))
def test_clearing_a_list_removes_its_dependency_requirement(tmp_path, inventory_game, table, field):
    inventory_game['missing'] = table
    service, snapshot, _ = setup_game(tmp_path)
    choice = ItemInventorySettings(**{field: ()})
    service.plan(replace(shop_spec('Cleared'), inventory_settings=choice), snapshot, capture_independent=True)
