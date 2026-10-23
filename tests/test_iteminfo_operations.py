from dataclasses import replace
import hashlib
import struct

import pytest

from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import (
    ADAPTER, CURRENT_ADAPTER, ItemFieldConflict, compile_assignments, compose_assignments, decode_assignment,
)
from tests.test_iteminfo_row import build_row, DDD


def assignment(raw, *, identity='set-stack', stat=False, value=10, expect=None, level=0):
    row = parse_iteminfo_row(raw)
    return {'id': identity, 'kind': 'field.assign',
            'target': {'adapter': CURRENT_ADAPTER if row.stat_block_marker == 0x12 else ADAPTER, 'table': 'ItemInfo', 'key': row.key},
            'field': {'name': 'stat_value', 'enchant_level': level, 'status_key': DDD} if stat else {'name': 'max_stack_count'},
            'value_type': 'i32' if stat else 'u32',
            'expect': (row.stat(level, DDD).value if stat else row.max_stack_count) if expect is None else expect,
            'value': value, 'precondition_base': 'source', 'source_row': hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize('reverse', [False, True])
def test_disjoint_edits_to_one_row_commute_and_removal_recomposes(reverse):
    raw = build_row()
    rows = {parse_iteminfo_row(raw).key: raw}
    stack = ('stack-owner', [assignment(raw, value=7)])
    stat = ('stat-owner', [assignment(raw, identity='damage', stat=True, value=13000)])
    selected = [stack, stat][::-1] if reverse else [stack, stat]
    compiled = compile_assignments(selected, rows)
    result = compose_assignments(rows, compiled)
    row = parse_iteminfo_row(result[next(iter(rows))])
    assert row.max_stack_count == 7 and row.stat(0, DDD).value == 13000
    assert result == compose_assignments(rows, compile_assignments(list(reversed(selected)), rows))
    assert all(value.source_reads and value.writes and value.invariants for value in compiled)
    offsets = {i for value in compiled for i in range(value.offset, value.offset + 4)}
    assert all(a == b for i, (a, b) in enumerate(zip(raw, row.raw)) if i not in offsets)
    removed = compose_assignments(rows, compile_assignments([stat], rows))
    assert parse_iteminfo_row(removed[row.key]).max_stack_count == 1
    assert parse_iteminfo_row(removed[row.key]).stat(0, DDD).value == 13000
    assert compose_assignments(rows, ()) == rows


def test_equal_assignments_coalesce_and_opposite_assignments_name_both_owners():
    raw = build_row()
    rows = {parse_iteminfo_row(raw).key: raw}
    first = ('first', [assignment(raw, value=7)])
    equal = ('second', [assignment(raw, value=7)])
    assert compose_assignments(rows, compile_assignments([first, equal], rows)) == compose_assignments(rows, compile_assignments([first], rows))
    with pytest.raises(ItemFieldConflict, match='opposing assignments') as error:
        compile_assignments([first, ('second', [assignment(raw, value=9)])], rows)
    assert error.value.owners == ('second/set-stack', 'first/set-stack')
    assert error.value.field == ('max_stack_count',)


@pytest.mark.parametrize('stat,value', [(False, 1), (False, 0xffffffff), (True, -0x80000000), (True, 0x7fffffff)])
def test_exact_integer_bounds_round_trip(stat, value):
    raw = build_row()
    source = parse_iteminfo_row(raw)
    rows = {source.key: raw}
    changed = compose_assignments(rows, compile_assignments([('owner', [assignment(raw, stat=stat, value=value)])], rows))
    row = parse_iteminfo_row(changed[source.key])
    assert (row.stat(0, DDD).value if stat else row.max_stack_count) == value


@pytest.mark.parametrize('stat,value', [(False, 0), (False, -1), (False, 0x100000000),
                                       (True, -0x80000001), (True, 0x80000000),
                                       (False, True), (True, 1.5), (False, '12')])
def test_invalid_integer_types_and_bounds_refuse(stat, value):
    raw = build_row()
    with pytest.raises(IndependentItemError, match='expected [ui]32 values'):
        decode_assignment('owner', assignment(raw, stat=stat, value=value))


def test_source_expectations_and_complete_legacy_record_requirements_refuse():
    raw = build_row()
    key = parse_iteminfo_row(raw).key
    with pytest.raises(IndependentItemError, match='expected 2, found 1'):
        compile_assignments([('owner', [assignment(raw, expect=2)])], {key: raw})
    with pytest.raises(IndependentItemError, match='source row changed'):
        compile_assignments([('owner', [assignment(raw)])], {key: raw[:-1] + b'\xff'})
    with pytest.raises(ItemFieldConflict, match='complete record unchanged') as error:
        compile_assignments([('owner', [assignment(raw)])], {key: raw}, protected={key: ('later-v1-package',)})
    assert 'later-v1-package' in error.value.owners[1]


def test_unsupported_selectors_layouts_and_ambiguous_fields_refuse():
    raw = build_row()
    key = parse_iteminfo_row(raw).key
    op = assignment(raw)
    op['field'] = {'offset': 12, 'length': 4}
    with pytest.raises(IndependentItemError, match='arbitrary offsets'):
        decode_assignment('owner', op)
    op = assignment(raw)
    op['precondition_base'] = 'composed'
    with pytest.raises(IndependentItemError, match='source-based'):
        decode_assignment('owner', op)
    op = assignment(raw, stat=True)
    op['field']['status_key'] = 42
    with pytest.raises(IndependentItemError, match='missing or ambiguous stat'):
        compile_assignments([('owner', [op])], {key: raw})
    duplicate = build_row(levels=[([(DDD, 1), (DDD, 2)], [])])
    with pytest.raises(IndependentItemError, match='missing or ambiguous stat'):
        compile_assignments([('owner', [assignment(duplicate, stat=True)])], {key: duplicate})
    row = parse_iteminfo_row(raw)
    marker = row.stat_block_offset + 8 + 4 * len(row.socket_items) + 12 * len(row.add_socket_materials)
    newer = raw[:marker] + b'\x12' + raw[marker + 1:]
    wrong_adapter = assignment(newer, stat=True)
    wrong_adapter['target']['adapter'] = ADAPTER
    with pytest.raises(IndependentItemError, match='unsupported stat-block'):
        compile_assignments([('owner', [wrong_adapter])], {key: newer})


def test_compiled_offsets_are_revalidated_and_writer_cannot_touch_unassigned_bytes(monkeypatch):
    import cdmw.domain.new_item.iteminfo_operations as owner
    raw = build_row()
    key = parse_iteminfo_row(raw).key
    rows = {key: raw}
    compiled = compile_assignments([('owner', [assignment(raw)])], rows)
    with pytest.raises(IndependentItemError, match='compiled layout changed'):
        compose_assignments(rows, [replace(compiled[0], offset=0)])
    real_write = owner.set_max_stack_count
    monkeypatch.setattr(owner, 'set_max_stack_count', lambda row, value: real_write(row, value)[:-1] + b'\xff')
    with pytest.raises(IndependentItemError, match='unassigned data'):
        compose_assignments(rows, compiled)


def test_unverified_table_directory_layout_refuses():
    from cdmw.domain.archives.iteminfo_composition import rows_of
    from cdmw.domain.archives.overlay_merge import OverlayConflict
    raw = build_row(key=1234)
    key = parse_iteminfo_row(raw).key
    header = struct.pack('<HHI', 1, key, 0)
    with pytest.raises(OverlayConflict, match='u32-key, u16-count'):
        rows_of(raw, header)


@pytest.mark.parametrize('marker', [0x11, 0x12])
def test_existing_field_adapters_accept_nonzero_secondary_description_and_level(marker):
    raw = build_row(item_type_code=56, desc2_key='second_description', equipable_level=12)
    parsed = parse_iteminfo_row(raw)
    marker_at = parsed.stat_block_offset + 8 + 4 * len(parsed.socket_items) + 12 * len(parsed.add_socket_materials)
    raw = raw[:marker_at] + bytes([marker]) + raw[marker_at + 1:]
    rows = {parsed.key: raw}
    operations = [assignment(raw, value=7), assignment(raw, identity='damage', stat=True, value=13000)]
    compiled = compile_assignments([('owner', operations)], rows)
    changed = compose_assignments(rows, compiled)[parsed.key]
    row = parse_iteminfo_row(changed)
    assert (row.item_type, row.category_info, row.max_stack_count, row.stat(0, DDD).value) == (56, 103, 7, 13000)
    offsets = {i for value in compiled for i in range(value.offset, value.offset + 4)}
    assert len(changed) == len(raw)
    assert all(a == b for i, (a, b) in enumerate(zip(raw, changed)) if i not in offsets)


@pytest.mark.parametrize('stat', [False, True])
def test_existing_field_adapters_still_refuse_a_nonzero_stack_high_word(stat):
    raw = build_row(max_stack=9_000_000_000_000_000_000)
    # The historical u32 operation is valid, but its source row is outside this adapter.
    operation = assignment(raw, stat=stat, expect=12000 if stat else 1)
    with pytest.raises(IndependentItemError, match='unsupported prefix layout'):
        compile_assignments([('owner', [operation])], {1001295: raw})


def test_field_adapter_refuses_an_unverified_category_even_with_a_known_item_type():
    from cdmw.core.iteminfo_row import DESC_TAG

    raw = bytearray(build_row(item_type_code=56))
    secondary_length = raw.index(DESC_TAG) + 13 + len('4300529278648433') + 9
    struct.pack_into('<I', raw, secondary_length, 0xffffffff)
    raw = bytes(raw)
    row = parse_iteminfo_row(raw)
    assert row.item_type == 56 and row.category_info is None
    with pytest.raises(IndependentItemError, match='unsupported prefix layout'):
        compile_assignments([('owner', [assignment(raw)])], {row.key: raw})
