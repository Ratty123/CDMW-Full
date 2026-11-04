"""Owned records for the ItemInfo sound fields introduced by game 1.0.0.3527."""
import struct

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.compact_static import field_payload
from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_row import (
    ItemInfoRowError, clone_iteminfo_row, parse_iteminfo_row, rebuild_stat_block,
    set_max_stack_count,
)
from cdmw.core.new_item_record import RecordError
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.services.new_item_snapshot import NewItemSnapshotError, build_snapshot
from tests.compact_item_fixtures import files, item, table, text
from tests.test_new_item_compact_dlc import dlc_game
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import build_package, _read, TEMPLATE
from cdmw.services.new_item_service import NewItemService

ROOT = 'gamedata/binarystaticinfo__/bin/'
SOUND = 'Owned_Charge_Sound'
SOCKET = 'Owned_Charge_Socket'


def patched(raw, sound=SOUND, socket=SOCKET):
    # Locate the insertion with the established older reader, independently of
    # the new grammar. All input bytes come from the project's owned fixtures.
    position = read_item_layout(raw).fields['_filterType'].end
    return raw[:position] + text(sound) + text(socket) + raw[position:]


@pytest.mark.parametrize('sound,socket', [('', ''), (SOUND, SOCKET), ('Charge_音', 'Socket_音')])
def test_both_layouts_preserve_fields_through_edits_and_clone(sound, socket):
    old = item()
    for raw in (old, patched(old, sound, socket)):
        row = parse_iteminfo_row(raw)
        assert row.key == parse_iteminfo_row(old).key
        assert row.string_key == parse_iteminfo_row(old).string_key
        assert rebuild_stat_block(row) == raw
        outputs = [raw, set_max_stack_count(row, 17), clone_iteminfo_row(
            row, key=1990001, string_key='PatchedClone', name_key='owned_name',
            desc_key='owned_description', replace_hashes={})]
        for output in outputs:
            layout = read_item_layout(output)
            assert layout.generation == 'compact'
            if raw == old:
                assert '_soundNameOnMaxCharged' not in layout.fields
            else:
                assert field_payload(layout, '_soundNameOnMaxCharged') == text(sound)
                assert field_payload(layout, '_soundSocketNameOnMaxCharged') == text(socket)
        assert parse_iteminfo_row(outputs[1]).max_stack_count == 17
        assert parse_iteminfo_row(outputs[2]).key == 1990001


@pytest.mark.parametrize('damage', ['truncated', 'extra', 'sound'])
def test_unknown_layouts_are_refused_with_reader_details(damage):
    raw = patched(item())
    layout = read_item_layout(raw)
    if damage == 'truncated':
        raw = raw[:-1]
    elif damage == 'extra':
        raw += b'\0'
    else:
        at = layout.fields['_soundNameOnMaxCharged'].start
        raw = raw[:at] + struct.pack('<I', 0xFFFFFFFF) + raw[at + 4:]
    with pytest.raises(RecordError, match='compact ItemInfo layout'):
        read_item_layout(raw)
    with pytest.raises(ItemInfoRowError, match='Unsupported ItemInfo row layout') as error:
        parse_iteminfo_row(raw)
    assert 'pre-3527:' in str(error.value) and '3527:' in str(error.value)
    if damage == 'sound':
        assert '_soundNameOnMaxCharged at row offset' in str(error.value)


def test_snapshot_plan_and_export_readback_keep_patched_sound_fields(tmp_path):
    source = files()
    body, head = source[ROOT+'iteminfo.staticinfobody'], source[ROOT+'iteminfo.staticinfoheader']
    rows = [(row.row_id, patched(body[start:end])) for row, start, end in
            parse_pabgh_table(head, payload=body).row_spans(len(body))]
    source[ROOT+'iteminfo.staticinfobody'], source[ROOT+'iteminfo.staticinfoheader'] = table(rows)
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path/'game', source)), read_entry=_read)
    assert set(snapshot.rows) == {key for key, _raw in rows}
    plan = service.plan(spec('PatchedOwned'), snapshot, capture_independent=True)
    service.export_loose(plan, tmp_path/'output', manager='DMM')
    body, head = plan.loose_files[ROOT+'iteminfo.staticinfobody'], plan.loose_files[ROOT+'iteminfo.staticinfoheader']
    cloned = next(body[start:end] for row, start, end in
                  parse_pabgh_table(head, payload=body).row_spans(len(body)) if row.row_id == plan.spec.item_key)
    layout = read_item_layout(cloned)
    assert layout.data('_soundNameOnMaxCharged') == text(SOUND)
    assert layout.data('_soundSocketNameOnMaxCharged') == text(SOCKET)
    assert parse_iteminfo_row(cloned).string_key == 'PatchedOwned'


@pytest.mark.parametrize('dlc', [False, True])
def test_snapshot_failure_identifies_base_or_dlc_source(tmp_path, dlc):
    root = dlc_game(tmp_path/'game') if dlc else tmp_path/'game'
    if dlc:
        from cdmw.core.archive_format import discover_pamt_files
        entries = [entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt)]
        stem = 'iteminfo.dlc_01'
    else:
        entries = parse_archive_pamt(build_package(root, files()))
        stem = 'iteminfo'
    target = ROOT + stem + '.staticinfobody'
    header = _read(next(entry for entry in entries if entry.path == ROOT + stem + '.staticinfoheader'))
    def broken(entry):
        raw = _read(entry)
        if entry.path == target:
            row, start, end = parse_pabgh_table(header, payload=raw).row_spans(len(raw))[0]
            offset = start + read_item_layout(raw[start:end]).fields['_occupiedEquipSlotDataList'].start
            raw = raw[:offset] + b'\2' + raw[offset + 1:]
        return raw
    with pytest.raises(NewItemSnapshotError) as error:
        build_snapshot(entries, read_entry=broken)
    message = str(error.value)
    assert 'ItemInfo row ' in message and 'did not decode' in message
    assert target in message
    assert 'row offset 0x' in message and 'length ' in message
    assert '_occupiedEquipSlotDataList' in message


def test_mixed_old_base_and_patched_dlc_snapshot(tmp_path):
    from cdmw.core.archive_format import discover_pamt_files
    root = dlc_game(tmp_path/'game')
    entries = [entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt)]
    stem = ROOT + 'iteminfo.dlc_01'
    body = _read(next(entry for entry in entries if entry.path == stem + '.staticinfobody'))
    head = _read(next(entry for entry in entries if entry.path == stem + '.staticinfoheader'))
    rows = [(row.row_id, patched(body[start:end])) for row, start, end in
            parse_pabgh_table(head, payload=body).row_spans(len(body))]
    body, head = table(rows)
    replacements = {stem + '.staticinfobody': body, stem + '.staticinfoheader': head}
    snapshot = build_snapshot(entries, read_entry=lambda entry: replacements.get(entry.path, _read(entry)))
    assert read_item_layout(snapshot.rows[TEMPLATE].raw).data('_soundNameOnMaxCharged') == text(SOUND)
    assert any('_soundNameOnMaxCharged' not in read_item_layout(row.raw).fields for key, row in snapshot.rows.items() if key != TEMPLATE)
