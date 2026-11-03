"""Wearer edits preserve inherited selectors, variant boundaries and exports."""
from copy import deepcopy
from dataclasses import replace
import struct

import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings
from cdmw.domain.new_item.spec import ModelSource
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, unpack_recipe
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_wearers import PLAYER_SELECTORS, WearerSupportError, set_wearer_support, wearer_support
from tests.compact_item_fixtures import files, item, table
from tests.item_layout_fixtures import full_item, counted
from tests.test_new_item_service import build_package, _read, TEMPLATE, PAC_XML, imported_pac
from tests.test_new_item_provenance import spec


STRINGS = {stringinfo_key(text): text for text in (*PLAYER_SELECTORS.values(), 'human_female', 'player_5')}
KLIFF, DAMIANE, OONGKA = 4234598676, 650024735, 2278589063
ROOT = 'gamedata/binarystaticinfo__/bin/'


def _prefab(selectors, kind=0):
    return (struct.pack('<3f', 1, 2, 3) + counted((111 + kind,)) + counted(())
            + counted((), 'H') + counted(selectors) + struct.pack('<IBBB', 0, 0, 0, kind))


def _row(generation='compact'):
    prefabs = struct.pack('<I', 2) + _prefab((DAMIANE, stringinfo_key('human_female'), 123456789)) + _prefab((789,), 3)
    fields = {'_prefabDataList': prefabs}
    raw = item(fields=fields) if generation == 'compact' else full_item(current=generation == 'current', fields=fields)
    return parse_iteminfo_row(raw, structured=True)


@pytest.mark.parametrize('generation', ('legacy', 'current', 'compact'))
def test_add_remove_preserves_other_fields_selectors_and_drop_model(generation):
    row = _row(generation)
    assert wearer_support(row, None, STRINGS).inherited == {'damiane'}
    existing = ItemBehaviorSettings({'memo': 'Keep this author edit'})
    settings = set_wearer_support(row, existing, STRINGS, 'kliff', True)
    assert set_wearer_support(row, settings, STRINGS, 'kliff', True) == settings
    before = read_behavior_fields(row.raw)['prefabs']
    after = settings.fields['prefabs']
    assert after[0] == dict(before[0], tribe_genders=before[0]['tribe_genders'] + [KLIFF])
    assert after[1] == before[1]
    assert existing.fields == {'memo': 'Keep this author edit'}
    assert set_wearer_support(row, settings, STRINGS, 'kliff', False) == existing
    only = set_wearer_support(row, None, STRINGS, 'oongka', True)
    assert OONGKA in only.fields['prefabs'][0]['tribe_genders']
    assert set_wearer_support(row, only, STRINGS, 'oongka', False) is None
    output = read_item_layout(set_behavior_fields(row.raw, only.fields))
    original = read_item_layout(row.raw)
    assert all(output.data(name) == original.data(name) for name in original.fields if name != '_prefabDataList')


@pytest.mark.parametrize('case,reason', (
    ('multiple', 'ambiguous'), ('no_worn', 'ambiguous'), ('empty', 'no_selectors'),
    ('role', 'unsupported'), ('gimmick', 'unsupported'), ('not_equipment', 'not_equipment'),
    ('removed_inherited', 'unsupported'),
))
def test_ambiguous_or_unqualified_entries_are_refused_without_mutation(case, reason):
    row = _row()
    prefabs = read_behavior_fields(row.raw)['prefabs']
    if case == 'multiple': prefabs.insert(1, deepcopy(prefabs[0]))
    if case == 'no_worn': prefabs[0]['data_type'] = 3
    if case == 'empty': prefabs[0]['tribe_genders'] = []
    if case == 'role': prefabs[1]['data_type'] = 2
    if case == 'gimmick': prefabs[0]['use_gimmick_prefab'] = True
    if case == 'removed_inherited': prefabs[0]['tribe_genders'].remove(DAMIANE)
    settings = ItemBehaviorSettings({'prefabs': prefabs}) if case == 'removed_inherited' else None
    if case != 'removed_inherited':
        row = parse_iteminfo_row(set_behavior_fields(row.raw, {'prefabs': prefabs}), structured=True)
    if case == 'not_equipment': row = replace(row, equip_type_key=0)
    original = deepcopy(settings)
    with pytest.raises(WearerSupportError, match=reason):
        set_wearer_support(row, settings, STRINGS, 'kliff', True)
    assert settings == original


def test_inherited_support_missing_strings_and_unrelated_overrides():
    row = _row()
    with pytest.raises(WearerSupportError, match='inherited'):
        set_wearer_support(row, None, STRINGS, 'damiane', False)
    assert not wearer_support(row, None, {}).available
    with pytest.raises(WearerSupportError, match='unsupported'):
        set_wearer_support(row, None, {}, 'kliff', True)
    with pytest.raises(WearerSupportError, match='not_equipment'):
        set_wearer_support(row, ItemBehaviorSettings({'equipment_type': 0}), STRINGS, 'kliff', True)
    prefabs = read_behavior_fields(row.raw)['prefabs']
    prefabs[0]['scale'] = [1.5, 1.0, 1.0]
    prefabs[1]['animations'] = [999]
    prefabs[0]['tribe_genders'].append(987654321)
    existing = ItemBehaviorSettings({'prefabs': prefabs, 'memo': 'Keep'})
    changed = set_wearer_support(row, existing, STRINGS, 'kliff', True)
    assert set_wearer_support(row, changed, STRINGS, 'kliff', False) == existing


@pytest.fixture
def wearer_game(tmp_path):
    source = files()
    body, header = source[ROOT+'iteminfo.staticinfobody'], source[ROOT+'iteminfo.staticinfoheader']
    rows = []
    for directory, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
        raw = body[start:end]
        if directory.row_id == TEMPLATE:
            prefabs = read_behavior_fields(raw)['prefabs']
            prefabs[0]['tribe_genders'] = [DAMIANE, stringinfo_key('human_female'), stringinfo_key('player_5')]
            drop = dict(deepcopy(prefabs[0]), data_type=3, tribe_genders=[])
            raw = set_behavior_fields(raw, {'prefabs': prefabs + [drop]})
        rows.append((directory.row_id, raw))
    source[ROOT+'iteminfo.staticinfobody'], source[ROOT+'iteminfo.staticinfoheader'] = table(rows)
    body, header = source[ROOT+'stringinfo.staticinfobody'], source[ROOT+'stringinfo.staticinfoheader']
    body, header, _ = append_stringinfo_strings(body, header, tuple(STRINGS.values()))
    source[ROOT+'stringinfo.staticinfobody'], source[ROOT+'stringinfo.staticinfoheader'] = body, header
    entries = parse_archive_pamt(build_package(tmp_path/'game', source))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read)


@pytest.mark.parametrize('imported', (False, True))
def test_dmm_and_item_package_keep_selectors_and_rebind_owned_models(tmp_path, wearer_game, imported):
    service, snapshot = wearer_game
    original = snapshot.rows[TEMPLATE]
    settings = set_wearer_support(original, None, snapshot.stringinfo_texts, 'kliff', True)
    choice = replace(spec('Wearers'), behavior_settings=settings,
                     model_source=ModelSource.IMPORTED if imported else ModelSource.TEMPLATE)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}) if imported else None
    plan = service.plan(choice, snapshot, model=model, capture_independent=True)
    package = read_package(package_bytes(from_plan(plan, 'f'*32)))
    continued = unpack_recipe(package)[0]
    assert continued.behavior_settings == settings
    assert package.manifest['requires']['item.behavior'] == 1
    service.export_loose(plan, tmp_path/'dmm', manager='DMM')
    pamt = next((tmp_path/'dmm').rglob('0.pamt'))
    entries = {entry.path: entry for entry in parse_archive_pamt(pamt)}
    body = read_archive_entry_data(entries[ROOT+'iteminfo.staticinfobody'])[0]
    header = read_archive_entry_data(entries[ROOT+'iteminfo.staticinfoheader'])[0]
    rows = {r.row_id: body[s:e] for r, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body))}
    assert rows[TEMPLATE] == original.raw
    exported = read_behavior_fields(rows[plan.spec.item_key])['prefabs']
    authored = settings.fields['prefabs']
    assert exported[0]['tribe_genders'] == authored[0]['tribe_genders']
    assert exported[1]['tribe_genders'] == authored[1]['tribe_genders']
    assert (exported[0]['prefabs'] != authored[0]['prefabs']) is imported
    assert all(dict(p, prefabs=[]) == dict(q, prefabs=[]) for p, q in zip(exported, authored))
