"""Owned records for the opaque DropInfoData byte in game 1.0.0.3663."""
from dataclasses import replace

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.compact_static import read_compact_layout
from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
from cdmw.core.new_item_record import RecordError
from cdmw.core.storeinfo_table import parse_store_row, encode_store_row, parse_store_table
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.spec import Placement, PlacementKind
from cdmw.services.new_item_service import NewItemService
from tests.compact_item_fixtures import files, reward, store, table
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import build_package, _read, TEMPLATE, OTHER

ROOT = 'gamedata/binarystaticinfo__/bin/'


def patched(raw, kind, extras=None):
    # Insert into established older fixture boundaries, independently of the
    # new reader. No extracted game bytes or executable addresses are used.
    layout = read_compact_layout(raw, kind)
    spans = [member.span for member in layout.members
             if member.owner == 'DropInfoData' and member.name == '_enchantLevel']
    assert spans and all(span.size == 2 for span in spans)
    extras = extras if extras is not None else [b'\xa5'] * len(spans)
    assert len(extras) == len(spans)
    for span, extra in reversed(list(zip(spans, extras))):
        raw = raw[:span.end] + extra + raw[span.end:]
    if kind == 'dropsetinfo':
        at = layout.fields['_isEqualPercent'].end
        raw = raw[:at] + b'\x01' + raw[at:]
    return raw


@pytest.mark.parametrize('extra', [None, b'\0', b'\1', b'\xa5'])
def test_shop_roundtrip_and_stock_clone_preserve_source_layout(extra):
    raw = store(3101, 'OwnedPatchShop', [TEMPLATE, OTHER])
    if extra is not None:
        raw = patched(raw, 'storeinfo', [extra, extra])
    source = parse_store_row(raw, key=3101, layout='compact')
    assert encode_store_row(source) == raw
    assert [entry.item_key for entry in source.entries] == [TEMPLATE, OTHER]
    clone = replace(source.entries[0], item_key=1990010, min_price_percent=1234567)
    changed = replace(source, entries=(clone, source.entries[1]))
    decoded = parse_store_row(encode_store_row(changed), key=3101, layout='compact')
    assert decoded.entries[0].item_key == 1990010
    assert decoded.entries[0].min_price_percent == 1234567
    assert decoded.entries[1].compact_raw == source.entries[1].compact_raw
    assert len(decoded.entries[0].drop_bytes) == (63 if extra is None else 64)
    if extra is not None:
        assert decoded.entries[0].drop_bytes[-5:-4] == extra


def test_reward_clone_append_and_reorder_retain_each_opaque_byte():
    source = parse_item_reward_set(reward(7101, TEMPLATE))
    old = encode_item_reward_set(source.with_entries((source.entries[0], replace(source.entries[0], item_key=OTHER))))
    raw = patched(old, 'dropsetinfo', [b'\x01', b'\xa5'])
    row = parse_item_reward_set(raw)
    assert encode_item_reward_set(row) == raw
    assert [entry.compact_enchant_extra for entry in row.entries] == [b'\x01', b'\xa5']
    clone = replace(row.entries[0], item_key=1990011, enhancement=7, minimum=2, maximum=3)
    edited = row.with_entries((row.entries[1], clone, row.entries[0]), key=7102, name='OwnedPatchReward')
    result = parse_item_reward_set(encode_item_reward_set(edited))
    assert result == edited
    assert read_compact_layout(result.compact_raw, 'dropsetinfo').data('_isToVehicle') == b'\1'
    assert [entry.compact_enchant_extra for entry in result.entries] == [b'\xa5', b'\x01', b'\x01']
    empty = parse_item_reward_set(encode_item_reward_set(row.with_entries(())))
    assert empty.entries == ()
    assert read_compact_layout(empty.compact_raw, 'dropsetinfo').data('_isToVehicle') == b'\1'
    with pytest.raises(RecordError, match='legacy layout'):
        encode_item_reward_set(replace(result, compact_raw=b'', policy=bytes(13), cache=bytes(10)))
    with pytest.raises(RecordError, match='differs from its source'):
        encode_item_reward_set(row.with_entries((replace(row.entries[0], compact_enchant_extra=b''),)))


@pytest.mark.parametrize('extra', [b'\0', b'\xa5'])
def test_v3_reward_export_preserves_the_new_byte(extra):
    from cdmw.services.dmm_item_export import _reward_patches
    raw = patched(reward(7101, TEMPLATE), 'dropsetinfo', [extra])
    row = parse_item_reward_set(raw)
    owned = row.with_entries((replace(row.entries[0], item_key=1990011),), key=7102)
    patches = {entry['path']: entry['new'] for entry in _reward_patches(raw, encode_item_reward_set(owned))}
    assert patches['list'][0]['raw_58'] == extra[0]
    assert patches['list'][0]['variant']['lookup'] == 1990011


@pytest.mark.parametrize('damage', ['truncated', 'trailer', 'mixed'])
def test_incomplete_or_mixed_shop_layouts_are_refused(damage):
    raw = store(3101, 'OwnedPatchShop', [TEMPLATE, OTHER])
    raw = patched(raw, 'storeinfo', [b'\xa5', b'' if damage == 'mixed' else b'\xa5'])
    if damage == 'truncated':
        raw = raw[:-1]
    elif damage == 'trailer':
        raw += b'\xff'
    with pytest.raises(RecordError):
        parse_store_row(raw, layout='compact')


@pytest.mark.parametrize('dlc', [False, True])
def test_new_item_snapshot_plan_and_export_readback(tmp_path, dlc):
    source = files()
    updated = {}
    for kind, width in (('storeinfo', 2), ('dropsetinfo', 4)):
        body, header = source[ROOT+kind+'.staticinfobody'], source[ROOT+kind+'.staticinfoheader']
        rows = [(entry.row_id, patched(body[start:end], kind)) for entry, start, end in
                parse_pabgh_table(header, payload=body).row_spans(len(body))]
        stem = ROOT + kind + ('.dlc_01' if dlc else '')
        updated[stem+'.staticinfobody'], updated[stem+'.staticinfoheader'] = table(rows, width)
        source[ROOT+kind+'.staticinfobody'], source[ROOT+kind+'.staticinfoheader'] = table(rows, width)
    if not dlc:
        source.update(updated)
    entries = parse_archive_pamt(build_package(tmp_path/'game', source))
    if dlc:
        entries += parse_archive_pamt(build_package(tmp_path/'game/dlc/dlc_01', updated))
    service = NewItemService()
    snapshot = service.build_snapshot(entries, read_entry=_read)
    assert snapshot.rows[TEMPLATE]
    choice = replace(spec('PatchedDropOwned'),
                     placement=Placement(kind=PlacementKind.INSERT, store_name='Store_Pai_BlackMarket'))
    plan = service.plan(choice, snapshot, capture_independent=True)
    service.export_loose(plan, tmp_path/'output', manager='DMM')
    import json
    from cdmw.services.dmm_send import OPERATIONS_FILE
    operations = json.loads((tmp_path/'output'/OPERATIONS_FILE).read_text(encoding='utf8'))
    shop = next(target for target in operations['targets'] if target['file'] == 'storeinfo.pabgb')
    assert shop['intents'] and all(intent['new']['value']['raw_h'] == 0xa5 for intent in shop['intents'])
    exported_stock = []
    for path, body in plan.loose_files.items():
        if '/storeinfo' in path and path.endswith('.staticinfobody'):
            rows = parse_store_table(body, plan.loose_files[path.replace('.staticinfobody', '.staticinfoheader')])
            assert all(encode_store_row(row) == row.raw for row in rows)
            if dlc != ('.dlc_01.' in path):
                continue
            exported_stock.extend(entry for row in rows for entry in row.entries if entry.item_key == plan.spec.item_key)
    assert exported_stock and all(entry.drop_bytes[-5:-4] == b'\xa5' for entry in exported_stock)
