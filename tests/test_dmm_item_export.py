"""V3 output is opt-in and retains the existing semantic proof boundary."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import threading
from uuid import uuid4

import pytest

from cdmw.core.dmm_item_fields import item_patches
from cdmw.core.item_recipe_table import parse_item_recipe
from cdmw.core.item_reward_table import parse_item_reward_set
from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.core.new_item_record import text_bytes
from cdmw.core.paloc_format import parse_paloc
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.item_settings import ItemSettings, QuantityEdit
from cdmw.services.dmm_item_export import build_field_json
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.services.independent_item_install import prepare_install, load_registry, resolve_items
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package
from cdmw.services.mod_merge_service import export_merged_mod
from cdmw.services.new_item_mod_base import mod_folder_payloads
from tests.item_layout_fixtures import full_item, counted
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_item_settings import extended_game
from tests.test_independent_items import setup_game


@pytest.fixture
def installed(tmp_path, extended_game):
    service, snapshot, _ = setup_game(tmp_path)
    packages = [from_plan(service.plan(replace(shop_spec(name), item_tier=tier,
        item_settings=ItemSettings(quantities=(QuantityEdit('price', 1, (1 << 64) - 1),))),
        snapshot, capture_independent=True), uuid4().hex) for name, tier in (('Alpha', 2), ('Beta', 4))]
    root = tmp_path / 'game'
    Backups(tmp_path).apply(prepare_install([package_bytes(p) for p in packages], root).preparation)
    return root, packages


def targets(document):
    return {target['file']: target['intents'] for target in document['targets']}


def patches(intent):
    return {patch['path']: patch['new'] for patch in intent['patches']}


def test_export_preserves_original_packages_bindings_dependencies_and_default_route(tmp_path, installed):
    root, packages = installed
    before, registry = files_in(root), load_registry(root)
    default = export_merged_mod(prepare_independent_mod_merge(root), tmp_path / 'default')
    assert default.manager == 'DMM'
    assert not (default.package_root / 'mod.field.json').exists()
    assert mod_folder_payloads(default.package_root)
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    result = export_merged_mod(plan, tmp_path / 'v3', dmm_v3=True)
    assert {p.relative_to(result.package_root).as_posix() for p in result.package_root.rglob('*') if p.is_file()} == {
        'mod.field.json', 'modinfo.json', 'README.txt', 'cdmw-source/' + SEMANTIC_EXPORT_FILE}
    retained = read_semantic_export(result.package_root / 'cdmw-source')
    assert retained.bindings == plan.semantic_export.bindings
    assert retained.witnesses == plan.semantic_export.witnesses
    assert retained.packages == plan.semantic_export.packages
    assert {(read_package(p).identity, read_package(p).digest) for p in retained.packages} == {
        (p.identity, p.digest) for p in packages}
    # Re-admission uses the real source checks and exact saved bindings, without
    # relying on the outer DMM JSON or weakening ordinary folder admission.
    setup_game(tmp_path / 'recipient')
    recipient = tmp_path / 'recipient/game'
    resolved = resolve_items([result.package_root / 'cdmw-source' / SEMANTIC_EXPORT_FILE], recipient, rebuild=True)
    assert all(resolved.registry['items'][p.identity]['values'] == registry['items'][p.identity]['values'] for p in packages)
    assert files_in(root) == before and load_registry(root) == registry
    with pytest.raises(ValueError, match='field JSON cannot be read as ordinary'):
        mod_folder_payloads(result.package_root)


def test_complete_clone_patches_refinement_real_payload_stock_groups_and_all_locales(installed):
    root, packages = installed
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    doc = build_field_json(plan.semantic_export, 'Two items')
    data = targets(json.loads(json.dumps(doc, ensure_ascii=False)))
    ids = {load_registry(root)['items'][p.identity]['values']['iteminfo']['item'] for p in packages}
    assert doc['format'] == 3
    items = data['iteminfo.pabgb']
    assert {i['new_key'] for i in items} == ids
    assert all(i['source_key'] == 1001295 for i in items)
    for item in items:
        values = patches(item)
        assert item['op'] == 'clone_record' and 'key' not in item
        assert values['string_key'].startswith('CDI_')
        assert values['item_tier'] in (2, 4)
        assert values['price_list'][0]['price']['price'] == (1 << 64) - 1
        assert values['item_name']['index'] == item['new_key'] << 32 | 0x70
        assert values['item_desc']['index'] == item['new_key'] << 32 | 0x71
        assert len(values['multi_change_info_list']) == 2
    recipes = data['multichangeinfo.pabgb']
    drops = data['dropsetinfo.pabgb']
    drop_ids = {i['new_key'] for i in drops}
    assert len(recipes) == len(drops) == 4
    assert all(set(patches(i)['result_drop_info_list']) <= drop_ids for i in recipes)
    files = {path: raw for path, raw, _ in plan.files}
    base = 'gamedata/binarystaticinfo__/bin/'
    body, header = (files[base + 'dropsetinfo.' + suffix] for suffix in ('staticinfobody', 'staticinfoheader'))
    rewards = {row.row_id: parse_item_reward_set(body[start:end]) for row, start, end in
               parse_pabgh_table(header, payload=body).row_spans(len(body))}
    body, header = (files[base + 'multichangeinfo.' + suffix] for suffix in ('staticinfobody', 'staticinfoheader'))
    expected_recipes = {row.row_id: parse_item_recipe(body[start:end]) for row, start, end in
                        parse_pabgh_table(header, payload=body).row_spans(len(body))}
    for intent in recipes:
        final = expected_recipes[intent['new_key']]
        values = patches(intent)
        assert values['result_drop_info_list'] == list(final.reward_keys)
        assert [r['item_info'] for r in values['fixed_material_data_list']] == [r.item_key for r in final.ingredients]
        assert [r['count'] for r in values['fixed_material_data_list']] == [r.quantity for r in final.ingredients]
    for drop in drops:
        for entry, expected in zip(patches(drop)['list'], rewards[drop['new_key']].entries, strict=True):
            assert entry['raw_at_120'] in ids
            assert entry['variant'] == dict(tag=0, lookup=entry['raw_at_120'])
            assert entry['raw_56'] == expected.enhancement & 0xffff
            assert (entry['raw_16'], entry['raw_32'], entry['raw_40'], entry['raw_48']) == (
                expected.weight, expected.sub_weight, expected.minimum, expected.maximum)
    stock = data['storeinfo.pabgb']
    assert all(i['op'] == 'array_append' and i['field'] == 'stock_data_list' for i in stock)
    assert {i['new']['value']['raw_q'] for i in stock} == ids
    assert all(i['new']['value']['payload']['body'] == i['new']['value']['raw_q'] for i in stock)
    assert len({i['new']['raw_d'] for i in stock}) == len(stock)
    groups = data['itemgroupinfo.pabgb']
    assert all(i['op'] == 'array_union' and set(i['new']) == ids for i in groups)
    # Compare against the actual compiled PALOC output, including inherited
    # categories, missing-language fallback and exact decimal composite keys.
    for path, raw, _ in plan.files:
        if path.endswith('.paloc'):
            old = parse_paloc(plan.semantic_export.originals[path]).index()
            new = parse_paloc(raw).index()
            language = Path(path).parent.name
            intents = data[f'localizationstring_{language}.paloc']
            assert {i['entry']: (i['key'], i['new']) for i in intents} == {
                key: (row.category, row.text) for key, row in new.items() if key not in old}
            assert all(type(i['entry']) is str and int(i['entry']) >> 32 in ids for i in intents)


def test_item_field_values_cover_full_signed_stats_sockets_passives_and_no_opaque_loss():
    # Independent construction, with signed counters and nonzero upper words.
    stat = lambda key, value: struct.pack('<IIq', 1, key, value)
    level = (struct.pack('<H', 2) + stat(10, -(1 << 50)) + stat(11, 1 << 55) + stat(12, -33)
        + struct.pack('<IIB', 1, 13, 255) + struct.pack('<IIQII', 1, 1, (1 << 64) - 1, 77, 1)
        + struct.pack('<III', 1, 440001, 19) + struct.pack('<I', 123))
    source = full_item()
    final = full_item(fields={'_enchantDataList': struct.pack('<I', 1) + level,
        '_equipPassiveSkillList': struct.pack('<III', 1, 600001, 42),
        '_dropDefaultData': struct.pack('<HII', 4, 1, 99) + struct.pack('<IIQ', 1, 1, 1 << 40) + b'\x12\x01\x01'})
    values = {p['path']: p['new'] for p in item_patches(source, final)}
    entry = values['enchant_data_list'][0]
    assert entry['level'] == 2 and entry['unk_u32_112'] == 123
    assert entry['enchant_stat_data'] == dict(max_stat_list=[dict(stat=10, change_mb=-(1 << 50))],
        regen_stat_list=[dict(stat=11, change_mb=1 << 55)], stat_list_static=[dict(stat=12, change_mb=-33)],
        stat_list_static_level=[dict(stat=13, change_mb=-1)])
    assert entry['buy_price_list'] == [dict(key=1, price=dict(price=(1 << 64) - 1, sym_no=77, item_info_wrapper=1))]
    assert values['drop_default_data']['socket_item_list'] == [99]
    assert values['drop_default_data']['add_socket_material_item_list'] == [dict(item=1, value=1 << 40)]
    assert values['equip_passive_skill_list'] == [dict(skill=600001, level=42)]
    with pytest.raises(ValueError, match='changed ItemInfo field _itemTagList'):
        item_patches(source, full_item(fields={'_itemTagList': counted([123])}))
    with pytest.raises(ValueError, match='four equipment passive skills'):
        item_patches(source, full_item(fields={'_equipPassiveSkillList': struct.pack('<I', 5) + bytes(40)}))


def test_unsupported_resources_stock_edits_and_source_equal_modules_refuse(tmp_path, installed):
    root, _ = installed
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    semantic = plan.semantic_export
    foreign = replace(semantic, files=(*semantic.files, ('character/model/custom.pac', b'asset', 0)),
        originals=dict(semantic.originals, **{'character/model/custom.pac': None}))
    with pytest.raises(ValueError, match='new resources are unsupported'):
        build_field_json(foreign, 'No partial exports')
    # Explicit source-equal stock operations have semantic preconditions that a
    # simple V3 set cannot retain; even an operation with no byte delta refuses.
    _, snapshot, _ = setup_game(tmp_path / 'fields')
    field = field_package(snapshot, value=snapshot.rows[1001295].max_stack_count)
    Backups(tmp_path).apply(prepare_install([package_bytes(field)], root).preparation)
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    with pytest.raises(ValueError, match='stock field edits'):
        export_merged_mod(plan, tmp_path / 'refused', dmm_v3=True)
    assert not (tmp_path / 'refused').exists()


@pytest.mark.parametrize('failure', ['cancel', 'stale'])
def test_final_publication_rechecks_sources_and_cancellation(tmp_path, installed, monkeypatch, failure):
    root, _ = installed
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    destination = tmp_path / 'preserved-empty'
    destination.mkdir()
    stop = threading.Event()
    import cdmw.core.mod_compatibility as owner
    write = owner.write_semantic_export
    def changed(*args, **kwargs):
        result = write(*args, **kwargs)
        if failure == 'cancel':
            stop.set()
        else:
            index = root / '0009/0.pamt'
            index.write_bytes(index.read_bytes() + b'changed')
        return result
    monkeypatch.setattr(owner, 'write_semantic_export', changed)
    with pytest.raises((RunCancelled, ValueError), match='cancel|stopped|[Ss]ource'):
        export_merged_mod(plan, destination, dmm_v3=True, stop_event=stop)
    assert list(destination.iterdir()) == []
    assert not list(tmp_path.glob('.preserved-empty.cdmw-stage-*'))


def test_update_and_reexport_reuse_assigned_item_and_refinement_ids(tmp_path, installed):
    root, packages = installed
    before = load_registry(root)
    service, snapshot, _ = setup_game(tmp_path / 'update-author')
    updated = from_plan(service.plan(replace(shop_spec('Renamed'), item_tier=5), snapshot,
        capture_independent=True), packages[0].identity)
    Backups(tmp_path).apply(prepare_install([package_bytes(updated)], root).preparation)
    plan = prepare_independent_mod_merge(root, dmm_v3=True)
    document = targets(build_field_json(plan.semantic_export, 'Updated'))
    current = load_registry(root)
    assert all(current['items'][p.identity]['values'] == before['items'][p.identity]['values'] for p in packages)
    key = current['items'][updated.identity]['values']['iteminfo']['item']
    intent = next(i for i in document['iteminfo.pabgb'] if i['new_key'] == key)
    assert patches(intent)['string_key'] == 'CDI_' + updated.identity
    assert patches(intent)['item_tier'] == 5


def test_data_only_field_json_is_not_silently_admitted_as_an_empty_mod(tmp_path):
    (tmp_path / 'custom.field.json').write_text(json.dumps(dict(format=3,
        targets=[dict(file='iteminfo.pabgb', intents=[])])))
    with pytest.raises(ValueError, match='field JSON cannot be read as ordinary'):
        mod_folder_payloads(tmp_path)


def test_legacy_partial_rows_refuse_v3_without_disabling_existing_exports(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    package = from_plan(service.plan(shop_spec('Partial'), snapshot, capture_independent=True), uuid4().hex)
    root = tmp_path / 'game'
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    default = export_merged_mod(prepare_independent_mod_merge(root), tmp_path / 'default-partial')
    assert mod_folder_payloads(default.package_root)
    with pytest.raises(ValueError, match='complete ItemInfo layout'):
        export_merged_mod(prepare_independent_mod_merge(root, dmm_v3=True), tmp_path / 'unsupported-v3', dmm_v3=True)
    assert not (tmp_path / 'unsupported-v3').exists()
