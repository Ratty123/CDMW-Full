"""Create New Item regression coverage for the compact base/DLC generation."""
from dataclasses import replace
import struct

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.compact_static import read_compact_layout, field_payload
from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
from cdmw.core.structured_binary_editor import parse_pabgh_table, append_table_rows, replace_table_row
from cdmw.core.iteminfo_settings import read_item_settings, set_item_settings
from cdmw.core.iteminfo_inventory import read_item_inventory, set_item_inventory
from cdmw.core.iteminfo_definition import read_definition_fields, set_definition_fields
from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.core.iteminfo_stats import read_item_stats, set_item_stats
from cdmw.domain.new_item.item_settings import ItemSettings, RepairEntry
from cdmw.domain.new_item.item_inventory import ItemInventorySettings
from cdmw.domain.new_item.item_stats import ItemStatSettings, StatOverride, PassiveSkill
from cdmw.services.new_item_service import NewItemService
from tests.compact_item_fixtures import files, item, table, store, group, text, OPTIONAL
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import build_package, _read, TEMPLATE

ROOT = 'gamedata/binarystaticinfo__/bin/'


def setup(tmp_path, *, dlc=False, localized=False):
    source = files()
    entries = parse_archive_pamt(build_package(tmp_path/'game', source))
    if dlc:
        from cdmw.core.item_layout import replace_layout_fields
        body,head = source[ROOT+'iteminfo.staticinfobody'],source[ROOT+'iteminfo.staticinfoheader']
        raw = next(body[s:e] for row,s,e in parse_pabgh_table(head,payload=body).row_spans(len(body)) if row.row_id==TEMPLATE)
        body = replace_layout_fields(read_item_layout(raw),{'_itemMemo':text('DLC override')}).raw
        values = {}
        if localized:
            from cdmw.core.paloc_format import parse_paloc,encode_paloc,entries_like
            layout = read_item_layout(body)
            template = parse_iteminfo_row(body,structured=True)
            names = {'_itemName': '9000000000070','_itemDesc': '9000000000071'}
            body = replace_layout_fields(layout,{field:layout.data(field)[:9]+text(key) for field,key in names.items()}).raw
            for path,data in source.items():
                if path.endswith('/item.paloc'):
                    paloc = parse_paloc(data)
                    added = (entries_like(paloc,template.name_key,{names['_itemName']:'Owned DLC name'})
                             + entries_like(paloc,template.desc_key,{names['_itemDesc']:'Owned DLC description'}))
                    values[path.replace('/item.paloc','/item.dlc_01.paloc')] = encode_paloc(replace(paloc,entries=added))
        for kind, pair in (
            ('iteminfo', table([(TEMPLATE, body)])),
            ('storeinfo', table([(2003, store(2003, 'Store_Pai_BlackMarket', [TEMPLATE]))], 2)),
            ('itemgroupinfo', table([(17011, group(17011, 'ItemGroup_Equip', [TEMPLATE]))], 2))):
            values[ROOT+kind+'.dlc_01.staticinfobody'], values[ROOT+kind+'.dlc_01.staticinfoheader'] = pair
        values[ROOT+'aiactionattributeinfo.dlc_01.staticinfoheader'] = b'\0\0'
        values[ROOT+'equiptypeinfo.dlc_01.staticinfoheader'] = b'\0\0'
        entries += parse_archive_pamt(build_package(tmp_path/'game/dlc/dlc_01', values))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read)


def test_compact_snapshot_plan_export_and_readback(tmp_path):
    service, snapshot = setup(tmp_path)
    plan = service.plan(spec('CompactOwned'), snapshot, capture_independent=True)
    service.export_loose(plan, tmp_path/'output', manager='CDUMM')
    body = plan.loose_files[ROOT+'iteminfo.staticinfobody']
    header = plan.loose_files[ROOT+'iteminfo.staticinfoheader']
    rows = {r.row_id: body[s:e] for r, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body))}
    owned = parse_iteminfo_row(rows[plan.spec.item_key], structured=True)
    assert owned.string_key == plan.spec.internal_name
    assert owned.layout_generation == 'compact'
    assert rows[TEMPLATE] == snapshot.rows[TEMPLATE].raw
    for kind in ('storeinfo','itemgroupinfo','multichangeinfo','dropsetinfo'):
        path = ROOT+kind+'.staticinfobody'
        if path in plan.loose_files:
            payload, directory = plan.loose_files[path], plan.loose_files[ROOT+kind+'.staticinfoheader']
            for row, start, end in parse_pabgh_table(directory, payload=payload).row_spans(len(payload)):
                assert read_compact_layout(payload[start:end],kind).integer('_key') == row.row_id
    from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, unpack_recipe
    package = read_package(package_bytes(from_plan(plan, 'a'*32)))
    assert unpack_recipe(package)[0].display_names == plan.spec.display_names


def test_empty_dlc_and_populated_overrides_load_together(tmp_path):
    _, snapshot = setup(tmp_path, dlc=True)
    assert snapshot.rows[TEMPLATE].memo == 'DLC override'
    assert snapshot.row_sources['iteminfo'][TEMPLATE].payload_entry.path.endswith('.dlc_01.staticinfobody')
    assert len([g for g in snapshot.item_groups if g.key == 17011]) == 1
    assert len([s for s in snapshot.stores if s.key == 2003]) == 1
    from cdmw.services.new_item_tables import row_pair
    assert row_pair(snapshot.discovery_view(), 'storeinfo', 2003).payload_entry.path.endswith('.dlc_01.staticinfobody')


def test_dlc_shop_and_group_changes_export_back_to_their_source(tmp_path):
    from cdmw.domain.new_item.spec import Placement,PlacementKind
    from cdmw.core.storeinfo_table import parse_store_table
    from cdmw.core.itemgroupinfo_table import parse_item_group_table
    service,snapshot = setup(tmp_path,dlc=True)
    choice = replace(spec('DlcOwned'),placement=Placement(kind=PlacementKind.INSERT,store_name='Store_Pai_BlackMarket'))
    plan = service.plan(choice,snapshot)
    for kind,parser in (('storeinfo',parse_store_table),('itemgroupinfo',parse_item_group_table)):
        stem = ROOT+kind+'.dlc_01'
        values = parser(plan.loose_files[stem+'.staticinfobody'],plan.loose_files[stem+'.staticinfoheader'])
        if kind=='storeinfo': assert any(e.item_key==plan.spec.item_key for s in values for e in s.entries)
        else: assert any(plan.spec.item_key in g.members for g in values)


def test_dlc_text_is_available_without_copying_unedited_dlc_entries_into_base(tmp_path):
    from cdmw.core.paloc_format import parse_paloc
    service,snapshot = setup(tmp_path,dlc=True,localized=True)
    assert snapshot.item_display_names()[TEMPLATE] == 'Owned DLC name'
    assert snapshot.paloc_table('ara').index()['9000000000071'].text == 'Owned DLC description'
    plan = service.plan(spec('DlcText'),snapshot)
    for language in ('eng','ara'):
        result = parse_paloc(plan.loose_files[f'gamedata/stringtable/binary__/{language}/item.paloc']).index()
        assert result[plan.spec.desc_key].text == 'Owned DLC description'
        assert '9000000000071' not in result


@pytest.mark.parametrize('variant', [False, True])
def test_dlc_prefabs_resolve_and_clone_without_copying_the_dlc_table_into_base(tmp_path, variant):
    from cdmw.core.pappt_format import parse_pappt, encode_pappt
    from tests.test_new_item_variant_authoring import selections
    source = files()
    path = 'character/bin__/partprefabtable.pappt'
    dlc_path = 'character/bin__/partprefabtable_dlc_01.pappt'
    original = parse_pappt(source[path])
    base = replace(original, records=original.records[:2])
    dlc = replace(original, records=original.records[2:])
    source[path] = encode_pappt(base)
    entries = parse_archive_pamt(build_package(tmp_path/'game', source))
    entries += parse_archive_pamt(build_package(tmp_path/'game/dlc/dlc_01', {dlc_path:encode_pappt(dlc)}))
    service = NewItemService()
    snapshot = service.build_snapshot(entries, read_entry=_read)
    assert snapshot.pappt.index() == original.index()
    choice = replace(spec('DlcPrefab'), variants=(selections(snapshot)[0],)) if variant else replace(
        spec('DlcPrefab'), effect='fx_test_fire.level.effect')
    plan = service.plan(choice, snapshot)
    exported = parse_pappt(plan.loose_files[path]).index()
    clones = set(plan.manifest['pappt_records'].values()) | set(plan.manifest.get('sheathed_records', {}).values())
    assert set(exported) == set(base.index()) | clones
    assert not set(dlc.index()) & set(exported)
    assert dlc_path not in plan.loose_files
    assert snapshot.payload(dlc_path) == encode_pappt(dlc)


def test_unavailable_dlc_recipe_and_reward_keys_are_still_reserved(tmp_path):
    from cdmw.core.item_layout import replace_layout_fields
    from cdmw.services.new_item_acquisition_index import load_acquisition_index
    from tests.compact_item_fixtures import recipe, reward
    from tests.test_new_item_service import OTHER
    service, snapshot = setup(tmp_path)
    entries = list(snapshot.entries.values())
    values = {}
    for kind,raw in (('multichangeinfo',recipe(1990000,'ReservedDlc',OTHER,1990000)),
                     ('dropsetinfo',reward(1990000,OTHER))):
        raw = replace_layout_fields(read_compact_layout(raw,kind),{'_isBlocked':b'\1'}).raw
        values[ROOT+kind+'.dlc_01.staticinfobody'],values[ROOT+kind+'.dlc_01.staticinfoheader'] = table([(1990000,raw)])
    entries += parse_archive_pamt(build_package(tmp_path/'game/dlc/dlc_01',values))
    snapshot = service.build_snapshot(entries,read_entry=_read)
    index = load_acquisition_index(snapshot)
    assert 1990000 in index.unsupported['multichangeinfo'] and 1990000 in index.unsupported['dropsetinfo']
    plan = service.plan(spec('Reserved'),snapshot)
    for kind in ('multichangeinfo','dropsetinfo'):
        body,head = plan.loose_files[ROOT+kind+'.staticinfobody'],plan.loose_files[ROOT+kind+'.staticinfoheader']
        added = {r.row_id for r in parse_pabgh_table(head,payload=body).rows if r.row_id >= 1990000}
        assert added and 1990000 not in added


@pytest.mark.parametrize('dlc',[False,True])
def test_compact_stock_export_preserves_source_table_and_optional_fields(tmp_path,dlc):
    from cdmw.services.independent_item_operations import stock_item_operations,from_declared_iteminfo_operations,lower_field_operations
    from cdmw.services.new_item_tables import row_pair
    _,snapshot = setup(tmp_path,dlc=dlc)
    choice = replace(spec('Stock'),inventory_settings=ItemInventorySettings(max_stack_count=333))
    operations = stock_item_operations(snapshot,choice)
    package = from_declared_iteminfo_operations(snapshot,'b'*32,'Stock',operations)
    changes = lower_field_operations(package,snapshot,{})
    pair = row_pair(snapshot,'iteminfo',TEMPLATE)
    assert set(changes) == {pair.payload_entry.path,pair.header_entry.path}
    body,head = changes[pair.payload_entry.path]['after'],changes[pair.header_entry.path]['after']
    raw = next(body[s:e] for row,s,e in parse_pabgh_table(head,payload=body).row_spans(len(body)) if row.row_id==TEMPLATE)
    assert read_item_inventory(raw).max_stack_count == 333
    assert read_item_layout(raw).data('_lostItemRecoveryType') == b'\2'


def test_compact_unset_and_virtual_root_texture_references(tmp_path):
    from types import SimpleNamespace
    from cdmw.services.new_item_behavior import texture_reference
    from cdmw.services.new_item_definition import resolve_map_icon
    from cdmw.core.stringinfo_table import stringinfo_key
    from tests.test_pathc_format import dds_header,dds_payload
    assert resolve_map_icon(SimpleNamespace(),0xeac5e173) is None
    texture_reference(SimpleNamespace(),0xeac5e173)
    cleared = set_behavior_fields(item(),{'default_texture':''})
    assert read_behavior_fields(cleared)['default_texture'] == 0xeac5e173
    name = '/character/texture/owned.dds'
    payloads = {name.lstrip('/'):dds_payload(dds_header(width=4,height=4))}
    snapshot = SimpleNamespace(stringinfo_texts={stringinfo_key(name):name},has_entry=payloads.__contains__,payload=payloads.__getitem__)
    texture_reference(snapshot,stringinfo_key(name))
    with pytest.raises(ValueError,match='Unqualified'):
        texture_reference(snapshot,123456)


def test_compact_texture_hash_is_traced_and_pinned_by_stock_export(tmp_path):
    from cdmw.core.stringinfo_table import append_stringinfo_strings,stringinfo_key
    from cdmw.services.independent_item_operations import stock_item_operations,from_declared_iteminfo_operations
    from tests.test_pathc_format import dds_header,dds_payload
    source = files()
    name = '/character/texture/owned.dds'
    source[name.lstrip('/')] = dds_payload(dds_header(width=4,height=4))
    sb,sh = ROOT+'stringinfo.staticinfobody',ROOT+'stringinfo.staticinfoheader'
    source[sb],source[sh],_keys = append_stringinfo_strings(source[sb],source[sh],[name])
    ib,ih = ROOT+'iteminfo.staticinfobody',ROOT+'iteminfo.staticinfoheader'
    raw = next(source[ib][s:e] for r,s,e in parse_pabgh_table(source[ih],payload=source[ib]).row_spans(len(source[ib])) if r.row_id==TEMPLATE)
    raw = set_behavior_fields(raw,{'default_texture':stringinfo_key(name)})
    source[ib],source[ih] = replace_table_row(source[ib],source[ih],TEMPLATE,raw)
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path/'game',source)),read_entry=_read)
    choice = replace(spec('Texture'),inventory_settings=ItemInventorySettings(max_stack_count=333))
    package = from_declared_iteminfo_operations(snapshot,'c'*32,'Texture',stock_item_operations(snapshot,choice))
    assert name.lstrip('/') in package.dependencies


@pytest.mark.parametrize('absent', [(), tuple(OPTIONAL)])
def test_compact_optional_fields_edit_and_preserve_unassigned_bytes(absent):
    raw = item(absent=absent)
    before = read_item_layout(raw)
    assert read_item_settings(raw)[0].important_item is None
    assert read_item_inventory(raw).quick_slot_index is None
    raw = set_item_settings(raw, ItemSettings(repairs=(RepairEntry(1, 50, 0, 1<<40),), cooldowns=(0,1<<63,9)))
    assert read_item_settings(raw)[0].repairs[0].resource_count == 1<<40
    raw = set_item_inventory(raw, ItemInventorySettings(max_stack_count=(1<<64)-1, tags=(42,)))
    assert read_item_inventory(raw).max_stack_count == (1<<64)-1
    raw = set_definition_fields(raw, {'inventory_routing': list(range(12))})
    assert read_definition_fields(raw)['inventory_routing'] == list(range(12))
    raw = set_behavior_fields(raw, {'memo':'Owned DLC 日本語','default_texture':123})
    assert read_behavior_fields(raw)['default_texture'] == 123
    after = read_item_layout(raw)
    changed = {'_repairDataList','_cooltime','_maxStackCount','_itemTagList','_itemPushInventoryContentsType','_itemMemo','_defaultTexturePath'}
    assert all(before.data(name) == after.data(name) for name in before.fields if name not in changed)
    assert field_payload(after,'_itemDesc2') == (None if absent else bytes(13))


def test_compact_stats_rebuild_and_resized_directory():
    raw = item()
    original = parse_iteminfo_row(raw, structured=True)
    assert rebuild_stat_block(original) == raw
    changed = set_item_stats(raw, ItemStatSettings((StatOverride('regeneration',0,123,-(1<<40)),), (PassiveSkill(765,4),)))
    values, skills = read_item_stats(changed)
    assert values[0].value == -(1<<40) and skills == (PassiveSkill(765,4),)
    body, header = table([(original.key, raw)])
    body, header = replace_table_row(body, header, original.key, changed)
    second = item(fields={'_key':struct.pack('<I',1990042),'_stringKey':text('Other')})
    body, header = append_table_rows(body, header, [second])
    parsed = parse_pabgh_table(header,payload=body)
    assert parsed.key_layout == 'named'
    assert [r.row_id for r in parsed.rows] == [original.key,1990042]
    assert body == changed+second


def test_compact_noop_rebuild_keeps_absent_values_and_passive_buffs():
    from cdmw.core.item_layout import replace_layout_fields
    from cdmw.core.iteminfo_declared_fields import read_field,write_field
    raw = item(absent=OPTIONAL)
    row = parse_iteminfo_row(raw,structured=True)
    assert rebuild_stat_block(row,levels=(),socket_items=(),add_socket_materials=(),price_list=row.price_list) == raw
    raw = item()
    layout = read_item_layout(raw)
    field = bytearray(field_payload(layout,'_enchantDataList'))
    passive = next(m.span for m in layout.members if m.owner=='EnchantData' and m.name=='_equipPassiveBuffs')
    offset = passive.start - layout.fields['_enchantDataList'].start - 1
    field[offset:offset+4] = struct.pack('<III',1,765,2)
    raw = replace_layout_fields(layout,{'_enchantDataList':b'\1'+field}).raw
    values = read_field(raw,('progression','enchantments'))
    values[0]['static'][0]['value'] += 1
    changed = write_field(raw,('progression','enchantments'),values)
    assert parse_iteminfo_row(changed,structured=True).enchant_levels[0].passive_buffs == struct.pack('<III',1,765,2)


def test_compact_equipment_bonus_supports_multiple_effects_at_one_level():
    from cdmw.core.buffinfo_table import parse_equipment_buff,encode_equipment_buff
    # One-byte discriminant, compact common data, then type-2's 12-byte body.
    effect = b'\0\2'+bytes(34)+text('Owned bonus')+bytes(76)
    raw = (text('OwnedBuff')+struct.pack('<I',765)+b'\0\1'+bytes(15)
           +struct.pack('<iiI',0,2,3)+b''.join(struct.pack('<i',level)+effect for level in (1,1,2))+bytes(4))
    value = parse_equipment_buff(raw)
    assert encode_equipment_buff(value) == raw
    assert [level.level for level in value.levels] == [1,1,2]
    assert value.supports(0) and value.supports(2) and not value.supports(3)


def test_pre_dlc_static_mod_base_cannot_replace_compact_tables(tmp_path):
    from tests.test_new_item_provenance import current_files
    from cdmw.services.new_item_mod_base import build_mod_base_snapshot
    service,snapshot = setup(tmp_path)
    folder = tmp_path/'older-mod'
    original = current_files()
    for suffix in ('staticinfobody','staticinfoheader'):
        relative = ROOT+'iteminfo.'+suffix
        path = folder/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(original[relative])
    with pytest.raises(ValueError,match='different static-table format'):
        build_mod_base_snapshot(service,snapshot,folder,read_entry=_read)
    assert (folder/(ROOT+'iteminfo.staticinfobody')).read_bytes() == original[ROOT+'iteminfo.staticinfobody']


def test_removed_controls_are_disabled_without_disabling_the_settings_editor(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from tests.test_new_item_settings_editor import editor_fixture
    from tests import test_new_item_provenance as original
    values = files()
    monkeypatch.setattr(original,'current_files',lambda:dict(values))
    app = QApplication.instance() or QApplication([])
    controller,panel,editor = editor_fixture(tmp_path)
    try:
        assert editor.pages.isEnabled()
        assert not editor.policies['important_item'].isEnabled()
        assert editor.policies['discardable'].isEnabled()
        assert not editor.inventory.numbers['quick_slot_index'].isEnabled()
        assert not editor.inventory.overrides['consumable_types'].isEnabled()
        assert editor.inventory.overrides['tags'].isEnabled()
        assert editor.definition.isEnabled() and editor.behavior.isEnabled()
    finally:
        panel.deleteLater();controller.deleteLater();app.processEvents()


def test_compact_definition_and_behavior_trees_cover_every_field(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from tests.test_new_item_settings_editor import editor_fixture
    from tests.test_new_item_definition_editor import select_field
    from tests import test_new_item_provenance as original
    from cdmw.core.iteminfo_behavior import default_value
    from cdmw.domain.new_item.item_behavior import BEHAVIOR_FIELDS, DOCKING, INSPECTION
    from cdmw.domain.new_item.item_definition import FLAGS, NUMBERS, COLLECTIONS
    values = files()
    body,head = values[ROOT+'iteminfo.staticinfobody'],values[ROOT+'iteminfo.staticinfoheader']
    rows = []
    for row,start,end in parse_pabgh_table(head,payload=body).row_spans(len(body)):
        raw = body[start:end]
        if row.row_id == TEMPLATE:
            docking = dict(default_value(DOCKING),owner_condition=0,use_cooldown=True)
            inspection = dict(default_value(INSPECTION),extract_distance_bits=123,extract_angle_bits=456)
            raw = set_behavior_fields(raw,{'docking':docking,'inspections':[inspection]})
        rows.append((row.row_id,raw))
    values[ROOT+'iteminfo.staticinfobody'],values[ROOT+'iteminfo.staticinfoheader'] = table(rows)
    monkeypatch.setattr(original,'current_files',lambda:dict(values))
    app = QApplication.instance() or QApplication([])
    controller,panel,settings = editor_fixture(tmp_path)
    try:
        for name,(_field,section) in FLAGS.items(): select_field(settings.definition,section,name)
        for name,(_field,_width,section,_table) in NUMBERS.items(): select_field(settings.definition,section,name)
        for name,(_field,_kind,section) in COLLECTIONS.items(): select_field(settings.definition,section,name)
        select_field(settings.definition,'world','faction')
        settings.definition.tree.setCurrentIndex(settings.definition._nodes[('synergies',)].index())
        settings.definition.add.click()
        assert controller.draft.definition_settings.fields['faction']['synergies'] == [0]
        for name,(_field,_shape,section) in BEHAVIOR_FIELDS.items():
            select_field(settings.behavior,section,name)
        select_field(settings.behavior,'interaction','docking')
        assert settings.behavior._shape(('owner_condition',)) == 'u32'
        assert settings.behavior._nodes[('use_cooldown',)].isCheckable()
        select_field(settings.behavior,'inspection','inspections')
        settings.behavior._nodes[(0,'extract_distance_bits')].setText('789')
        assert controller.draft.behavior_settings.fields['inspections'][0]['extract_distance_bits'] == 789
        output = set_behavior_fields(controller.snapshot.rows[TEMPLATE].raw,controller.draft.behavior_settings.fields)
        assert read_behavior_fields(output)['docking']['use_cooldown'] is True
    finally:
        panel.deleteLater();controller.deleteLater();app.processEvents()


@pytest.mark.parametrize('corruption', ['truncated','trailer','presence','count'])
def test_compact_corruption_is_rejected(corruption):
    raw = item()
    layout = read_item_layout(raw)
    if corruption == 'truncated': raw = raw[:-1]
    elif corruption == 'trailer': raw += b'\0'
    else:
        field = '_itemDesc2' if corruption == 'presence' else '_itemGroupInfoList'
        span = layout.fields[field]
        bad = b'\2' if corruption == 'presence' else b'\xff'*4
        raw = raw[:span.start]+bad+raw[span.start+len(bad):]
    with pytest.raises(ValueError): read_compact_layout(raw)
