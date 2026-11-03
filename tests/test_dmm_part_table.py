"""New items register only their own parts; installed mod records survive."""
from dataclasses import replace
import json

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pappt_format import (HeadPrefabRecord, PartPrefabRecord, PartPrefabTable,
                                   PartPrefabPart, encode_pappt, parse_pappt)
from cdmw.services.dmm_part_table import PART_TABLE, part_operations
from cdmw.services.dmm_send import OPERATIONS_FILE, write_operations
from cdmw.services.new_item_planning import ModelFiles
from cdmw.domain.new_item.spec import ModelSource
from tests.test_new_item_provenance import spec
from tests.test_independent_items import imported_game
from tests.test_new_item_service import imported_pac, PAC_XML


def test_additions_leave_private_heads_refits_and_rules_untouched(tmp_path):
    stock = PartPrefabRecord('stock', 'armor', '', parts=(PartPrefabPart('CD_Upperbody'),))
    own = stock.cloned('cdmw_owned')
    base = PartPrefabTable((stock,), tag_prefix=b'\x01')
    table = replace(base, records=base.records + (own,))
    files, targets = part_operations({PART_TABLE: encode_pappt(table), own.prefab_path: b'owned'},
                                    lambda _: encode_pappt(base))
    assert PART_TABLE not in files and files == {own.prefab_path: b'owned'}
    assert targets == [dict(file=PART_TABLE, intents=[dict(op='list_append', key=0, field='primary', new=dict(
        key_a='cdmw_owned', key_b='armor', key_c='', bool_flag=1, asset_id='', flag=1,
        children=[dict(sub_key='CD_Upperbody', sub_flag=1)]))])]
    # Apply the emitted append to a table already extended by CC/FAF. No table
    # replacement or condition-rule operation can touch these unrelated records.
    installed = replace(base, records=base.records + (stock.cloned('faf_owned'),),
                        head_records=(HeadPrefabRecord('cc_private_head', 'heads'),))
    merged = replace(installed, records=installed.records + (own,))
    assert parse_pappt(encode_pappt(merged)).head_records == installed.head_records
    assert merged.records[:2] == installed.records
    write_operations(tmp_path, 'Item', targets)
    changed = json.loads(json.dumps(targets))
    changed[0]['intents'][0]['new']['asset_id'] = 'Chest01'
    write_operations(tmp_path, 'Item', changed)
    actual = json.loads((tmp_path/OPERATIONS_FILE).read_text())['targets']
    assert actual == changed  # A resend never adds a second record of the same name.


@pytest.mark.parametrize('case', ('head', 'existing', 'foreign', 'duplicate'))
def test_replacements_and_unowned_registrations_are_refused(case):
    stock = PartPrefabRecord('stock', 'armor', '')
    own = stock.cloned('new')
    base = PartPrefabTable((stock,))
    after = replace(base, records=(stock, own))
    files = {own.prefab_path: b'owned'}
    if case == 'head': after = replace(after, head_records=(HeadPrefabRecord('private', 'heads'),))
    if case == 'existing': after = replace(after, records=(replace(stock, folder='changed'), own))
    if case == 'foreign': files.clear()
    if case == 'duplicate': after = replace(after, records=(stock, own, own))
    files[PART_TABLE] = encode_pappt(after)
    with pytest.raises(ValueError):
        part_operations(files, lambda _: encode_pappt(base))


def test_real_dmm_export_has_owned_part_intents_and_no_table_copy(tmp_path):
    service, snapshot = imported_game(tmp_path)
    choice = replace(spec('NewArmor'), model_source=ModelSource.IMPORTED)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
    plan = service.plan(choice, snapshot, model=model, capture_independent=True)
    output = tmp_path/'export'
    service.export_loose(plan, output, manager='DMM')
    paths = {entry.path for entry in parse_archive_pamt(output/'0036/0.pamt')}
    assert PART_TABLE not in paths
    targets = json.loads((output/OPERATIONS_FILE).read_text())['targets']
    part_intents = next(row['intents'] for row in targets if row['file'] == PART_TABLE)
    expected = set(plan.manifest['pappt_records'].values()) | set(plan.manifest.get('sheathed_records', {}).values())
    assert {row['new']['key_a'] for row in part_intents} == expected
    assert all(row['op'] == 'list_append' and row['field'] == 'primary' for row in part_intents)
    assert not any('conditionalpartprefab' in path for path in paths)
    # The portable-package route must use the same merge contract after rebasing.
    from cdmw.services.independent_item_package import from_plan, package_bytes
    from cdmw.services.dmm_send import send_item_packages
    package = tmp_path/'new-item.cdmw'
    package.write_bytes(package_bytes(from_plan(plan, 'b' * 32)))
    mods = tmp_path/'owned-dmm/mods'
    mods.mkdir(parents=True)
    sent = send_item_packages((package,), tmp_path/'game', mods, 'Portable item')
    assert PART_TABLE not in {entry.path for entry in parse_archive_pamt(sent.folder/'0036/0.pamt')}
    targets = json.loads((sent.folder/OPERATIONS_FILE).read_text())['targets']
    assert next(row['intents'] for row in targets if row['file'] == PART_TABLE)
