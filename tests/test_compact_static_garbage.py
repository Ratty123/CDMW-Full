"""Reading a compact static row leaves nothing for the cyclic garbage collector.

Create New Item's snapshot reads tens of thousands of these rows on a worker. Each
read that left a reference cycle kept the row's spans, members and cursor alive
until a collection; the window thread's once-a-second young collection then freed
300,000 to 1,000,000 such objects at a time and held the GIL for 200 to 800 ms
(2026-11-17 review, Browse and Mesh Editor rows). Plain reference counting must
free a read as soon as it is dropped.
"""
import gc

import pytest

from cdmw.core.compact_static import field_bytes, field_payload, read_compact_layout
from cdmw.core.new_item_record import RecordError
from tests.test_gimmickinfo_patch_layout import gimmick


def _cyclic_garbage(action) -> int:
    """Objects that only a collection can free once ``action`` has run and been dropped."""

    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        action()
        return gc.collect()
    finally:
        if enabled:
            gc.enable()


def test_a_row_read_on_its_first_program_leaves_no_cycles():
    row = gimmick(7101, 'Gimmick_New')
    assert read_compact_layout(row, 'gimmickinfo').data('_stringKey')
    assert _cyclic_garbage(lambda: read_compact_layout(row, 'gimmickinfo')) == 0


def test_a_row_read_after_a_refused_program_leaves_no_cycles():
    # The older GimmickInfo layout is tried first and refused: its exception is kept.
    row = gimmick(7102, 'Gimmick_Old', new=None)
    assert read_compact_layout(row, 'gimmickinfo').data('_stringKey')
    assert _cyclic_garbage(lambda: read_compact_layout(row, 'gimmickinfo')) == 0


def test_a_refused_row_leaves_no_cycles():
    row = gimmick(7103, 'Gimmick_Broken')[:-3]

    def refused():
        with pytest.raises(RecordError):
            read_compact_layout(row, 'gimmickinfo')

    refused()
    assert _cyclic_garbage(refused) == 0


def test_reading_and_writing_a_field_leaves_no_cycles():
    layout = read_compact_layout(gimmick(7104, 'Gimmick_Field'), 'gimmickinfo')

    def touch():
        payload = field_payload(layout, '_stringKey')
        field_bytes(layout, '_stringKey', payload)

    touch()
    assert _cyclic_garbage(touch) == 0
