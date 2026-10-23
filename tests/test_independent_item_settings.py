from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_settings import read_item_settings
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.item_settings import ItemSettings, RepairEntry, QuantityEdit
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package, unpack_recipe
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.item_layout_fixtures import full_item, counted, use_action
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.test_independent_items import setup_game
from tests.test_new_item_service import TEMPLATE, STEM, ICON_STRING, MC_ROW_0, MC_ROW_1, _table4
from tests.test_virtual_loader import game_bytes


@pytest.fixture
def extended_game(monkeypatch):
    from tests import test_new_item_provenance as source
    original = source.current_files
    control = {'use_kind': 9}
    def files():
        result = original()
        base = 'gamedata/binarystaticinfo__/bin/'
        name = base + 'iteminfo.'
        body, header = result[name + 'staticinfobody'], result[name + 'staticinfoheader']
        rows = []
        for entry, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
            raw = body[start:end]
            if entry.row_id == TEMPLATE:
                icon = struct.pack('<III', 1, stringinfo_key(ICON_STRING), 0) + bytes(6)
                raw = full_item(raw, stems=(STEM + '_r', 'cd_phm_01_sword_0168_r_in_index01', STEM + '_l'),
                    fields={'_itemIconList': icon, '_multiChangeInfoList': counted((MC_ROW_0, MC_ROW_1)),
                            '_itemTagList': counted((9876, 5432))})
            rows.append((entry.row_id, raw))
        result[name + 'staticinfobody'], result[name + 'staticinfoheader'] = _table4(rows)
        from tests.test_iteminfo_row import build_row
        food = full_item(build_row(key=1005300, string_key='UseTemplate', equip='', item_type=28001,
            stems=(), levels=[], prices=((1, 5),), socket_items=(), adds=()),
            fields={'_itemUseInfoList': counted((1000031,))})
        rows.append((1005300, food))
        result[name + 'staticinfobody'], result[name + 'staticinfoheader'] = _table4(rows)
        name = base + 'itemuseinfo.'
        body, header = result[name + 'staticinfobody'], result[name + 'staticinfoheader']
        rows = [(entry.row_id, body[start:end]) for entry, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body))]
        payload = b'' if control['use_kind'] == 9 else struct.pack('<HH', 1, 2)
        rows.append((1000031, use_action(kind=control['use_kind'], payload=payload)))
        result[name + 'staticinfobody'], result[name + 'staticinfoheader'] = _table4(rows)
        return result
    monkeypatch.setattr(source, 'current_files', files)
    return control


def settings():
    return ItemSettings(repairs=(RepairEntry(1, 200, 0, 1 << 40),), blocked_store_sell=True,
        discardable=False, important_item=True, destroy_when_broken=False, preserved_on_extract=True,
        can_disassemble=True, extractable=True, extraction_reward=880000, minimum_extract_level=3,
        use_actions=(1000031,), cooldowns=(0, 1 << 63, (1 << 64) - 1), charge_type=2,
        maximum_charges=(0, 1 << 31, 0xffffffff), shared_cooldown_group=0xffffffff,
        quantities=(QuantityEdit('price', 1, (1 << 64) - 1), QuantityEdit('stat', 1000002, -(1 << 40), 0)))


@pytest.mark.parametrize('virtual', (False, True))
def test_all_extended_settings_compile_rebuild_remove_and_preserve_legacy_package_wire(tmp_path, extended_game, virtual):
    service, snapshot, _ = setup_game(tmp_path / 'author')
    choice = replace(shop_spec('Extended'), item_settings=settings())
    plan = service.plan(choice, snapshot, capture_independent=True)
    graph = plan.reference_assessment
    assert any(edge.source == f'iteminfo:{plan.spec.item_key}' and edge.evidence == 'Declared final ItemInfo prefab field'
               for edge in graph.edges)
    assert any(edge.source == f'iteminfo:{plan.spec.item_key}' and edge.evidence == 'Declared final ItemInfo icon field'
               for edge in graph.edges)
    assert any('engine aliases' in reason for reason in graph.unresolved)
    package = from_plan(plan, uuid4().hex)
    meta = package_metadata(package)
    assert meta['requires'] == {'item.legacy': 1, 'item.properties': 2}
    assert unpack_recipe(read_package(package_bytes(package)))[0].item_settings == settings()
    assert 'gamedata/binarystaticinfo__/bin/itemuseinfo.staticinfobody' in package.dependencies
    with pytest.raises(IndependentItemError, match='v1'):encode(choice)
    legacy = from_plan(replace(plan, spec=replace(plan.spec, item_settings=None)), package.identity)
    assert package.recipe == legacy.recipe
    assert package.manifest['provenance']['source_digest'] == legacy.digest
    assert package_metadata(legacy)['version'] == 1
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = game_bytes(root)
    backups = Backups(tmp_path)
    if virtual:
        path = tmp_path / 'extended.cditem'
        path.write_bytes(package_bytes(package))
        profile = VirtualProfile((path,))
        prepared = prepare_profile(profile, root)
        publish_profile(prepared)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw = virtual_row(root, key).raw
        assert dict(prepare_profile(profile, root).files) == dict(prepared.files)
        publish_profile(prepare_profile(VirtualProfile(()), root))
    else:
        backups.apply(prepare_install([package_bytes(package)], root).preparation)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw = snapshot_of(root).rows[key].raw
        backups.apply(prepare_rebuild(package.identity, root).preparation)
        assert snapshot_of(root).rows[key].raw == raw
        backups.apply(prepare_remove(package.identity, root))
    assert game_bytes(root) == before
    actual, quantities = read_item_settings(raw)
    assert replace(actual, quantities=settings().quantities) == settings()
    assert {(row.kind, row.level, row.key): row.value for row in quantities}[('price', None, 1)] == (1 << 64) - 1
    assert read_item_layout(raw).data('_itemTagList') == counted((9876, 5432))


@pytest.mark.parametrize('mutation', ('extra', 'boolean', 'overflow', 'duplicate', 'v1-downgrade'))
def test_extended_settings_refuse_malformed_or_silently_downgraded_modules(tmp_path, extended_game, mutation):
    service, snapshot, _ = setup_game(tmp_path)
    package = from_plan(service.plan(replace(shop_spec('Extended'), item_settings=settings()), snapshot,
        capture_independent=True), uuid4().hex)
    meta = deepcopy(package.manifest)
    module = meta['modules'][1]
    data = module['data']['settings']
    if mutation == 'extra':data['raw_offset'] = 12
    elif mutation == 'boolean':data['discardable'] = 1
    elif mutation == 'overflow':data['cooldowns'][0] = 1 << 64
    elif mutation == 'duplicate':meta['modules'].append(dict(module, id='second_settings'))
    elif mutation == 'v1-downgrade':meta['requires']['item.properties'] = module['version'] = 1
    with pytest.raises(IndependentItemError):read_v2(meta, package.blobs)


@pytest.mark.parametrize('override', (
    ItemSettings(repairs=(RepairEntry(999999, 1, 0, 1),)),
    ItemSettings(extraction_reward=999999), ItemSettings(use_actions=(999999,)),
))
def test_missing_repair_reward_or_use_dependencies_refuse_during_planning(tmp_path, extended_game, override):
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='Missing|missing'):
        service.plan(replace(shop_spec('Missing'), item_settings=override), snapshot, capture_independent=True)


def test_changed_use_definition_is_an_exact_portable_dependency(tmp_path, extended_game):
    service, snapshot, _ = setup_game(tmp_path / 'author')
    package = from_plan(service.plan(replace(shop_spec('Use'), item_settings=ItemSettings(use_actions=(1000031,))),
        snapshot, capture_independent=True), uuid4().hex)
    extended_game['use_kind'] = 1
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = game_bytes(root)
    with pytest.raises(IndependentItemError, match='dependenc|source|match'):
        prepare_install([package_bytes(package)], root)
    assert game_bytes(root) == before


@pytest.mark.parametrize('kind', ('price', 'buy_price', 'stat'))
def test_legacy_and_full_width_edits_cannot_target_the_same_quantity(tmp_path, extended_game, kind):
    from cdmw.domain.new_item.spec import PriceEdit, BuyPriceEdit, StatEdit
    service, snapshot, _ = setup_game(tmp_path)
    legacy = {'price': {'price_edits': (PriceEdit(1, 7),)},
              'buy_price': {'buy_price_edits': (BuyPriceEdit(0, 1, 7),)},
              'stat': {'stat_edits': (StatEdit(0, 1000002, 7),)}}[kind]
    quantity = QuantityEdit(kind, 1000002 if kind == 'stat' else 1, 1 << 40, None if kind == 'price' else 0)
    choice = replace(shop_spec('ConflictingAmount'), item_settings=ItemSettings(quantities=(quantity,)), **legacy)
    with pytest.raises(ValueError, match='both legacy and full-width'):
        service.plan(choice, snapshot, capture_independent=True)


@pytest.mark.parametrize('virtual', (False, True))
def test_inventory_use_template_without_equipment_mesh_compiles_as_a_real_owned_item(tmp_path, extended_game, virtual):
    service, snapshot, _ = setup_game(tmp_path / 'author')
    choice = replace(shop_spec('NewUseItem'), template_key=1005300,
        item_settings=ItemSettings(use_actions=(1000031,), cooldowns=(5, 10, 15), maximum_charges=(1, 2, 3)))
    plan = service.plan(choice, snapshot, capture_independent=True)
    assert not plan.new_paths
    package = from_plan(plan, uuid4().hex)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    if virtual:
        path = tmp_path / 'use.cditem'
        path.write_bytes(package_bytes(package))
        publish_profile(prepare_profile(VirtualProfile((path,)), root))
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        row = virtual_row(root, key)
    else:
        Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        row = snapshot_of(root).rows[key]
    assert row.key != 1005300 and row.equip_type_key == 0
    values, _ = read_item_settings(row.raw)
    assert values.use_actions == (1000031,) and values.cooldowns == (5, 10, 15)
