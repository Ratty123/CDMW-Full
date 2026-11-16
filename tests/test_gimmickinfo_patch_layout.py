"""Owned GimmickInfo and ConditionData records for game 1.0.0.3663.

Rows are written field by field in the older wire order, and the 1.0.0.3663 bytes are
inserted at established older boundaries, independently of the new reader. No extracted
game bytes or executable addresses are used.
"""
import struct

import pytest

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.compact_static import field_payload, read_compact_layout
from cdmw.core.item_layout import replace_layout_fields
from cdmw.core.new_item_record import RecordError
from cdmw.core.static_table_records import decode_static_table
from tests.compact_item_fixtures import table, text
from tests.test_static_table_records import _minimal

NEW_FIELDS = ('_autoTargetingConstraintDataList', '_gimmickConstraintDataList')


def record(kind, given, after=None, extra=b''):
    """Encode `kind` in the older order, with `extra` bytes after the field named `after`."""
    out = bytearray()
    for op in READERS[TABLE_READERS[kind]][1:]:
        _minimal(op, out, given)
        if op[2] == after:
            out += extra
    return bytes(out)


def gimmick(key, name, *, new=b'\0\0', fields=None):
    """A GimmickInfo row. `new` holds the two 1.0.0.3663 presence bytes; None is the older layout."""
    given = {'_stringKey': text(name), '_key': struct.pack('<I', key), **(fields or {})}
    return record('gimmickinfo', given, '_lookAtDataList', b'' if new is None else new)


def condition(tag, payload=b''):
    """A present condition tree holding one primitive (u8 case 3) of u16 type `tag`, then the
    type's payload, an absent target and the three trailing bytes."""
    return b'\1' + b'\3' + struct.pack('<H', tag) + payload + b'\0' + bytes(3)


def interaction_override(gate):
    """_gimmickInteractionOverrideDataList with one override that carries one condition."""
    element = (struct.pack('<I', 1000004)                      # _originInteractionInfo
               + b'\0' + bytes(8) + text('')                   # _interactionOverrideName
               + struct.pack('<f', -1.0)                       # _interactionOverrideDistance
               + bytes(4) + bytes(4)                           # action and pivot override lists
               + struct.pack('<I', 1)                          # one condition override:
               + b'\0' + b'\1' + gate                          #   no first condition, then the gate
               + b'\0' + bytes(4) + bytes(4) + b'\0\0'         #   its five trailing values
               + bytes(4) + bytes(4)                           # pop item and sub-interaction lists
               + bytes(4) + bytes(4)                           # dialog set and drop set
               + bytes(5))                                     # five flags
    return b'\1' + struct.pack('<I', 1) + b'\1' + element


# Type 238 of 1.0.0.3663 is type 237 of the older enum, which reads a u32 before its target.
NEW_238 = condition(238, struct.pack('<I', 0x5F8DF033))
OLD_238 = condition(238)


def test_the_3663_layout_reads_both_new_fields_and_the_older_layout_still_reads():
    new = read_compact_layout(gimmick(7001, 'Gimmick_New'), 'gimmickinfo')
    old = read_compact_layout(gimmick(7002, 'Gimmick_Old', new=None), 'gimmickinfo')

    look, auto, constraint, faction = (new.fields[name] for name in ('_lookAtDataList', *NEW_FIELDS, '_factionStructure'))
    assert (look.end, auto.end, constraint.end) == (auto.start, constraint.start, faction.start)
    assert [new.data(name) for name in NEW_FIELDS] == [b'\0', b'\0']
    assert [field_payload(new, name) for name in NEW_FIELDS] == [None, None]
    assert not set(NEW_FIELDS) & set(old.fields)
    assert len(new.raw) == len(old.raw) + 2


def test_a_table_of_both_layouts_decodes_with_matching_keys():
    body, header = table([(7001, gimmick(7001, 'Gimmick_New')), (7002, gimmick(7002, 'Gimmick_Old', new=None))])

    decoded = decode_static_table('gimmickinfo', header, body)

    assert decoded.refused == ()
    assert [(r.key, r.name) for r in decoded.records] == [(7001, 'Gimmick_New'), (7002, 'Gimmick_Old')]
    assert decoded.records[0].field('_gimmickConstraintDataList').end == decoded.records[0].field('_factionStructure').start


def test_a_dlc_painting_shape_with_one_management_stat_is_twelve_bytes_longer():
    stat = b'\1' + struct.pack('<III', 1, 1000079, 2)
    base = read_compact_layout(gimmick(7003, 'Collection_Prop_Picture'), 'gimmickinfo')
    dlc = read_compact_layout(gimmick(7003, 'Collection_Prop_Picture', fields={'_managementStatDataList': stat}),
                              'gimmickinfo')

    assert len(dlc.raw) - len(base.raw) == 12
    assert [name for name in base.fields if base.data(name) != dlc.data(name)] == ['_managementStatDataList']
    assert [(m.name, dlc.raw[m.span.start:m.span.end]) for m in dlc.members
            if m.owner == 'GimmickInfo_FactionManagementStatData'] == [
        ('_statusInfo', struct.pack('<I', 1000079)), ('_statValue', struct.pack('<I', 2))]


@pytest.mark.parametrize('kind', ['gimmickinfo', 'conditioninfo'])
def test_condition_types_after_the_new_3663_type_read_the_moved_shape(kind):
    if kind == 'gimmickinfo':
        new = gimmick(7004, 'Gimmick_Gate', fields={'_gimmickInteractionOverrideDataList': interaction_override(NEW_238)})
        old = gimmick(7004, 'Gimmick_Gate', new=None,
                      fields={'_gimmickInteractionOverrideDataList': interaction_override(OLD_238)})
        field = '_gimmickInteractionOverrideDataList'
    else:
        base = {'_stringKey': text('Condition_Gate'), '_key': struct.pack('<I', 7005)}
        new = record(kind, {**base, '_gameCondition': NEW_238})
        old = record(kind, {**base, '_gameCondition': OLD_238})
        field = '_gameCondition'

    assert len(read_compact_layout(new, kind).data(field)) == len(read_compact_layout(old, kind).data(field)) + 4


def test_the_new_condition_type_and_present_new_fields_are_refused_as_unqualified():
    unqualified = 'has not been qualified'
    tag_144 = gimmick(7006, 'Gimmick_New_Type', fields={'_gimmickInteractionOverrideDataList': interaction_override(condition(144))})
    with pytest.raises(RecordError, match=unqualified):
        read_compact_layout(tag_144, 'gimmickinfo')
    for flags in (b'\1\0', b'\0\1'):
        with pytest.raises(RecordError, match=unqualified):
            read_compact_layout(gimmick(7007, 'Gimmick_Present', new=flags), 'gimmickinfo')


@pytest.mark.parametrize('damage', ['flag', 'truncated', 'trailer'])
def test_malformed_3663_rows_are_refused(damage):
    good = gimmick(7008, 'Gimmick_Good')
    assert read_compact_layout(good, 'gimmickinfo').data('_key') == struct.pack('<I', 7008)
    if damage == 'flag':
        raw, message = gimmick(7008, 'Gimmick_Bad', new=b'\2\0'), 'Invalid compact static presence flag'
    elif damage == 'truncated':
        raw, message = good[:-1], 'Truncated static record'
    else:
        raw, message = good + b'\0', 'boundary'
    with pytest.raises(RecordError, match=message):
        read_compact_layout(raw, 'gimmickinfo')


def test_a_3663_row_round_trips_and_clones_through_the_layout_writer():
    source = gimmick(7009, 'Collection_Prop_Picture_0001', fields={
        '_prefabPath': text('object/cd_gimmick/picture_01.prefab'),
        '_gimmickName': b'\0' + struct.pack('<Q', 7009 << 32 | 0x200) + text(str(7009 << 32 | 0x200)),
    })
    layout = read_compact_layout(source, 'gimmickinfo')
    spans = sorted(layout.fields.values(), key=lambda span: span.start)
    assert spans[0].start == 0 and spans[-1].end == len(source)
    assert all(a.end == b.start for a, b in zip(spans, spans[1:]))
    assert replace_layout_fields(layout, {name: layout.data(name) for name in layout.fields}).raw == source

    new_key = 7999
    edits = {
        '_stringKey': text('Collection_Prop_Picture_Custom'),
        '_key': struct.pack('<I', new_key),
        '_prefabPath': text('object/cd_gimmick/picture_custom.prefab'),
        '_gimmickName': b'\0' + struct.pack('<Q', new_key << 32 | 0x200) + text(str(new_key << 32 | 0x200)),
    }
    clone = replace_layout_fields(layout, edits)
    again = read_compact_layout(clone.raw, 'gimmickinfo')
    assert {name for name in layout.fields if again.data(name) != layout.data(name)} == set(edits)
    assert all(again.data(name) == value for name, value in edits.items())
    assert [again.data(name) for name in NEW_FIELDS] == [b'\0', b'\0']
