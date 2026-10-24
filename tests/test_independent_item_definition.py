from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_definition import read_definition_fields, decode_local_string, encode_local_string
from cdmw.core.paloc_format import parse_paloc, encode_paloc, entries_like, add_localization_entries
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.item_definition import ItemDefinitionSettings
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_codec import encode
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package, unpack_recipe
from cdmw.services.independent_mod_package import read_v2
from cdmw.services.new_item_definition import load_definition_index
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_fields import virtual_row
from tests.test_independent_item_settings import extended_game, TEMPLATE
from tests.test_independent_items import setup_game
from tests.test_iteminfo_definition import definition_fields
from tests.test_new_item_service import _table4
from tests.test_virtual_loader import game_bytes


MAP_NAME = 'MapIcon_OwnedDefinition'
MAP_XML = 'ui/xml/texture/definition_map.xml'
MAP_DDS = 'ui/texture/icon/definition_map.dds'
SECONDARY = str((TEMPLATE << 32) | 0x72)


@pytest.fixture
def definition_game(extended_game, monkeypatch):
    import tests.test_new_item_provenance as source
    original = source.current_files
    control = {'missing': '', 'changed': '', 'blocked': '', 'duplicate': '', 'no_description': False,
               'donor': False, 'map_xml': None, 'map_duplicate': False, 'malformed': ''}
    def files():
        result = original()
        base = 'gamedata/binarystaticinfo__/bin/'
        body, header = result[base+'iteminfo.staticinfobody'], result[base+'iteminfo.staticinfoheader']
        data = definition_fields()
        data.update(_packedItemInfo=struct.pack('<I', TEMPLATE), _unpackedItemInfo=struct.pack('<I', TEMPLATE),
                    _convertItemInfoByDropNPC=struct.pack('<I', TEMPLATE), _mapIconPath=struct.pack('<I', stringinfo_key(MAP_NAME)))
        rows = []
        primary_description = None
        for entry, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
            raw = body[start:end]
            if entry.row_id == TEMPLATE:
                layout = read_item_layout(raw)
                primary_description = decode_local_string(layout.data('_itemDesc'))['text_key']
                if control['no_description']: data['_itemDesc2'] = bytes(13)
                raw = replace_layout_fields(layout, data).raw
            elif entry.row_id == 1005300 and control['donor']:
                key = (entry.row_id << 32) | 0x76
                raw = replace_layout_fields(read_item_layout(raw), {'_itemDesc2': encode_local_string(
                    {'category': 7, 'key': key, 'text_key': str(key)})}).raw
            rows.append((entry.row_id, raw))
        result[base+'iteminfo.staticinfobody'], result[base+'iteminfo.staticinfoheader'] = _table4(rows)
        for table, keys, width in (('knowledgeinfo', (600001,), 4), ('effectinfo', (500001, 500002), 4),
                ('gimmickinfo', (700001, 700002, 700003), 4), ('characterinfo', (900001,), 4),
                ('tribeinfo', (101,), 4), ('patterndescriptioninfo', (800001,), 4),
                ('localstringinfo', (400001,), 4), ('crafttoolinfo', (4321,), 2)):
            source_keys = (keys[-1] + 10,) if control['missing'] == table else keys
            rows = []
            if base+table+'.staticinfobody' in result:
                original_body = result[base+table+'.staticinfobody']
                original_header = result[base+table+'.staticinfoheader']
                rows.extend((entry.row_id, original_body[start:end]) for entry, start, end in
                    parse_pabgh_table(original_header, payload=original_body).row_spans(len(original_body))
                    if entry.row_id not in keys)
            for key in source_keys:
                name = ('Changed_' if control['changed'] == table else 'Owned_') + table
                raw = key.to_bytes(width, 'little') + struct.pack('<I', len(name)) + name.encode() + bytes([int(control['blocked'] == table)])
                if control['malformed'] == table: raw = raw[:width] + b'\xff\xff\xff\xff'
                rows.append((key, raw))
            if control['duplicate'] == table: rows.append(rows[0])
            result[base+table+'.staticinfobody'], result[base+table+'.staticinfoheader'] = _table4(rows)
        for path in tuple(result):
            if path.endswith('.paloc'):
                table = parse_paloc(result[path])
                additions = entries_like(table, primary_description, {SECONDARY: 'Original secondary'})
                if control['donor']:
                    additions += entries_like(table, primary_description, {str((1005300 << 32) | 0x76): 'Donor secondary'})
                result[path] = encode_paloc(add_localization_entries(table, additions))
        stem = base+'stringinfo.'
        result[stem+'staticinfobody'], result[stem+'staticinfoheader'], _ = append_stringinfo_strings(
            result[stem+'staticinfobody'], result[stem+'staticinfoheader'], [MAP_NAME])
        dds = next(raw for path, raw in result.items() if path.endswith('.dds'))
        result[MAP_DDS] = dds
        result[MAP_XML] = f'<Texture Name="{MAP_NAME}" Filename="{MAP_DDS}" X="0" Y="0"/>'.encode()
        if control['map_xml'] is not None: result[MAP_XML] = control['map_xml']
        if control['map_duplicate']:
            result['ui/xml/texture/other_map.xml'] = result[MAP_XML].replace(b'X="0"', b'X="8"')
        if control['changed'] == 'map': result[MAP_XML] = result[MAP_XML].replace(b'X="0"', b'X="1"')
        if control['missing'] == 'map': del result[MAP_DDS]
        return result
    monkeypatch.setattr(source, 'current_files', files)
    return control


def choices(snapshot):
    values = read_definition_fields(snapshot.rows[TEMPLATE].raw)
    for name in ('packed_item', 'unpacked_item', 'drop_npc_item'): values[name] = TEMPLATE
    for rows in (values['faction']['costs'], values['faction']['prices']):
        for row in rows: row['item'] = TEMPLATE
    values['sealable_items'][0]['target'] = TEMPLATE
    values['dyeable'] = False
    values['knowledge_obtain_type'] = 255
    values['occupied_slots'][0]['indexes'] = [255]
    values['sharpness']['parameters'][0]['value'] = 0
    return ItemDefinitionSettings(values, {'source_item': None, 'texts': {'eng': 'An owned secondary description'}})


@pytest.mark.parametrize('virtual', (False, True))
def test_all_six_areas_compile_round_trip_rebuild_remove_and_preserve_v1(tmp_path, definition_game, virtual):
    service, snapshot, _ = setup_game(tmp_path/'author')
    assert load_definition_index(snapshot).descriptions
    settings = choices(snapshot)
    plan = service.plan(replace(shop_spec('Definition'), definition_settings=settings), snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    assert package.manifest['requires'] == {'item.legacy': 1, 'item.definition': 1}
    assert unpack_recipe(read_package(package_bytes(package)))[0].definition_settings == settings
    legacy = from_plan(replace(plan, spec=replace(plan.spec, definition_settings=None)), package.identity)
    assert package.recipe == legacy.recipe and package.manifest['provenance']['source_digest'] == legacy.digest
    assert package_metadata(legacy)['version'] == 1
    with pytest.raises(IndependentItemError, match='v1'): encode(plan.spec)
    assert MAP_DDS in package.dependencies and MAP_XML in package.dependencies
    assert any(path.endswith('/crafttoolinfo.staticinfobody') for path in package.dependencies)
    setup_game(tmp_path/'recipient'); root = tmp_path/'recipient/game'; before = game_bytes(root)
    if virtual:
        path = tmp_path/'definition.cditem'; path.write_bytes(package_bytes(package))
        profile = VirtualProfile((path,)); prepared = prepare_profile(profile, root); publish_profile(prepared)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        raw = virtual_row(root, key).raw
        assert dict(prepare_profile(profile, root).files) == dict(prepared.files)
        # The compiled owned text key follows the recipient's allocated identity.
        own_key = str((key << 32) | 0x72)
        assert decode_local_string(read_item_layout(raw).data('_itemDesc2'))['text_key'] == own_key
        publish_profile(prepare_profile(VirtualProfile(()), root))
    else:
        backups = Backups(tmp_path); backups.apply(prepare_install([package_bytes(package)], root).preparation)
        key = load_registry(root)['items'][package.identity]['values']['iteminfo']['item']
        recipient = snapshot_of(root); raw = recipient.rows[key].raw
        own_key = str((key << 32) | 0x72)
        assert recipient.english.index()[own_key].text == 'An owned secondary description'
        assert recipient.english.index()[SECONDARY].text == 'Original secondary'
        backups.apply(prepare_rebuild(package.identity, root).preparation)
        assert snapshot_of(root).rows[key].raw == raw
        backups.apply(prepare_remove(package.identity, root))
    assert read_definition_fields(raw) == settings.fields
    assert game_bytes(root) == before


@pytest.mark.parametrize('missing', ('knowledgeinfo', 'effectinfo', 'gimmickinfo', 'characterinfo',
    'tribeinfo', 'patterndescriptioninfo', 'crafttoolinfo', 'map'))
def test_missing_definition_dependencies_refuse(tmp_path, definition_game, missing):
    definition_game['missing'] = missing
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='Missing|missing'):
        service.plan(replace(shop_spec('Missing'), definition_settings=choices(snapshot)), snapshot)


@pytest.mark.parametrize('changed', ('knowledgeinfo', 'effectinfo', 'crafttoolinfo', 'map'))
def test_changed_definition_sources_refuse_before_recipient_writes(tmp_path, definition_game, changed):
    service, snapshot, _ = setup_game(tmp_path/'author')
    package = from_plan(service.plan(replace(shop_spec('Pinned'), definition_settings=choices(snapshot)),
        snapshot, capture_independent=True), uuid4().hex)
    definition_game['changed'] = changed
    setup_game(tmp_path/'recipient'); root = tmp_path/'recipient/game'; before = game_bytes(root)
    with pytest.raises(IndependentItemError, match='dependenc|source|match'):
        prepare_install([package_bytes(package)], root)
    assert game_bytes(root) == before


def test_definition_module_admission_refuses_unknown_duplicate_orphan_and_future(tmp_path, definition_game):
    service, snapshot, _ = setup_game(tmp_path)
    package = from_plan(service.plan(replace(shop_spec('Admission'), definition_settings=choices(snapshot)),
        snapshot, capture_independent=True), uuid4().hex)
    for change in ('unknown', 'duplicate', 'orphan', 'future', 'missing_capability'):
        meta = deepcopy(package.manifest)
        module = next(row for row in meta['modules'] if row['type'] == 'item.definition')
        if change == 'unknown': module['data']['fields']['future'] = 1
        elif change == 'duplicate': meta['modules'].append(dict(module, id='duplicate'))
        elif change == 'orphan': meta['modules'] = [module]
        elif change == 'future': module['version'] = meta['requires']['item.definition'] = 2
        else: del meta['requires']['item.definition']
        with pytest.raises(IndependentItemError): read_v2(meta, package.blobs)


@pytest.mark.parametrize('table', ('knowledgeinfo', 'effectinfo', 'gimmickinfo', 'crafttoolinfo'))
def test_blocked_named_references_are_not_authoring_choices_or_valid_dependencies(tmp_path, definition_game, table):
    definition_game['blocked'] = table
    service, snapshot, _ = setup_game(tmp_path)
    index = load_definition_index(snapshot)
    forbidden = {'knowledgeinfo': 600001, 'effectinfo': 500001, 'gimmickinfo': 700001, 'crafttoolinfo': 4321}[table]
    assert forbidden not in dict(index.choices[table])
    with pytest.raises(ValueError, match='Blocked'):
        service.plan(replace(shop_spec('Blocked'), definition_settings=choices(snapshot)), snapshot)


@pytest.mark.parametrize('failure', ('duplicate', 'malformed'))
def test_craft_tool_uses_u16_key_and_refuses_duplicate_or_malformed_rows(tmp_path, definition_game, failure):
    definition_game[failure] = 'crafttoolinfo'
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError):
        service.plan(replace(shop_spec('CraftTool'), definition_settings=choices(snapshot)), snapshot)


@pytest.mark.parametrize('failure', ('ambiguous', 'conflicting', 'doctype', 'malformed'))
def test_map_registry_refuses_ambiguous_and_unsupported_bindings(tmp_path, definition_game, failure):
    if failure == 'ambiguous': definition_game['map_duplicate'] = True
    elif failure == 'conflicting':
        definition_game['map_xml'] = f'<Texture Name="{MAP_NAME}" Filename="{MAP_DDS}" FileName="other.dds"/>'.encode()
    elif failure == 'doctype': definition_game['map_xml'] = b'<!DOCTYPE Texture><Texture/>'
    else: definition_game['map_xml'] = b'<Texture'
    service, snapshot, _ = setup_game(tmp_path)
    with pytest.raises(ValueError, match='ambiguous|conflicting|declaration|XML'):
        service.plan(replace(shop_spec('Map'), definition_settings=choices(snapshot)), snapshot)


@pytest.mark.parametrize('field,value', (('compatibility_hash', 333),
    ('occupied_slots', [{'name_hash': 123456, 'indexes': [1]}]),
    ('occupied_slots', [{'name_hash': 87654, 'indexes': []}]),
    ('knowledge_key', 765432), ('unlock_message', 765432)))
def test_unknown_equipment_and_named_references_refuse(tmp_path, definition_game, field, value):
    service, snapshot, _ = setup_game(tmp_path)
    settings = choices(snapshot); values = dict(settings.fields, **{field: value})
    with pytest.raises(ValueError, match='source definition|Missing'):
        service.plan(replace(shop_spec('Unknown'), definition_settings=replace(settings, fields=values)), snapshot)


def test_empty_secondary_description_needs_an_observed_donor_and_owns_its_tag(tmp_path, definition_game):
    from cdmw.services.new_item_definition import apply_definition
    definition_game.update(no_description=True, donor=True)
    _, snapshot, _ = setup_game(tmp_path)
    raw = snapshot.rows[TEMPLATE].raw
    text = {'source_item': None, 'texts': {'eng': 'Owned'}}
    with pytest.raises(ValueError, match='Choose a source item'):
        apply_definition(raw, ItemDefinitionSettings(secondary_description=text), snapshot, 123, TEMPLATE)
    text['source_item'] = 1005300
    edited, plan = apply_definition(raw, ItemDefinitionSettings(choices(snapshot).fields, text), snapshot, 123, TEMPLATE)
    assert decode_local_string(read_item_layout(edited).data('_itemDesc2')) == {
        'category': 7, 'key': (123 << 32) | 0x76, 'text_key': str((123 << 32) | 0x76)}
    assert plan.source_key == str((1005300 << 32) | 0x76)
    cleared, plan = apply_definition(edited, ItemDefinitionSettings(secondary_description={'source_item': None, 'texts': {}}), snapshot, 123, TEMPLATE)
    assert read_item_layout(cleared).data('_itemDesc2') == bytes(13) and plan is None
    with pytest.raises(ValueError, match='language is unavailable'):
        apply_definition(raw, ItemDefinitionSettings(secondary_description={'source_item': 1005300, 'texts': {'unknown': 'Text'}}), snapshot, 123, TEMPLATE)


def test_secondary_localization_uses_requested_language_then_english_then_source(tmp_path, definition_game):
    service, snapshot, _ = setup_game(tmp_path)
    languages = tuple(snapshot.languages)
    selected = next(language for language in languages if language != 'eng')
    for texts in ({selected: 'Localized'}, {'eng': 'English', selected: 'Localized'}):
        settings = replace(choices(snapshot), secondary_description={'source_item': None, 'texts': texts})
        plan = service.plan(replace(shop_spec('Localized'), definition_settings=settings), snapshot)
        own_key = str((plan.spec.item_key << 32) | 0x72)
        for language in languages:
            path = snapshot.paloc_entries[language].path
            table = parse_paloc(plan.loose_files[path])
            assert table.index()[own_key].text == texts.get(language, texts.get('eng', 'Original secondary'))


def test_definition_composes_with_unchanged_property_stat_and_inventory_modules(tmp_path, definition_game):
    from cdmw.domain.new_item.item_settings import ItemSettings
    from cdmw.domain.new_item.item_stats import ItemStatSettings
    from cdmw.domain.new_item.item_inventory import ItemInventorySettings
    service, snapshot, _ = setup_game(tmp_path)
    spec = replace(shop_spec('Combined'), item_tier=0, item_settings=ItemSettings(discardable=False),
        stat_settings=ItemStatSettings(passive_skills=()), inventory_settings=ItemInventorySettings(max_stack_count=1 << 63),
        definition_settings=choices(snapshot))
    package = from_plan(service.plan(spec, snapshot, capture_independent=True), uuid4().hex)
    restored = unpack_recipe(read_package(package_bytes(package)))[0]
    assert (restored.item_tier, restored.item_settings, restored.stat_settings, restored.inventory_settings,
            restored.definition_settings) == (spec.item_tier, spec.item_settings, spec.stat_settings, spec.inventory_settings, spec.definition_settings)
    assert package.manifest['requires'] == {'item.legacy': 1, 'item.properties': 2, 'item.stats': 1, 'item.inventory': 1, 'item.definition': 1}


def test_map_scan_cancellation_does_not_cache_partial_binding(tmp_path, definition_game, monkeypatch):
    import threading
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.services.new_item_definition import resolve_map_icon
    _, snapshot, _ = setup_game(tmp_path)
    stop = threading.Event(); original = type(snapshot).payload
    def cancel_after_xml(self, path):
        result = original(self, path)
        if path == MAP_XML: stop.set()
        return result
    monkeypatch.setattr(type(snapshot), 'payload', cancel_after_xml)
    with pytest.raises(RunCancelled): resolve_map_icon(snapshot, stringinfo_key(MAP_NAME), stop_event=stop)
    assert ('definition-map-icon', stringinfo_key(MAP_NAME)) not in snapshot._authoring_indexes


def test_existing_dmm_v3_export_refuses_definition_modules_instead_of_dropping_them(tmp_path, definition_game):
    from cdmw.services.dmm_item_export import build_field_json
    from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
    service, snapshot, _ = setup_game(tmp_path)
    package = from_plan(service.plan(replace(shop_spec('DefinitionExport'), definition_settings=choices(snapshot)),
        snapshot, capture_independent=True), uuid4().hex)
    root = tmp_path/'game'
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    export = prepare_independent_mod_merge(root, dmm_v3=True).semantic_export
    with pytest.raises(ValueError, match='DMM V3'):
        build_field_json(export, 'Refuse unsupported lowering')
