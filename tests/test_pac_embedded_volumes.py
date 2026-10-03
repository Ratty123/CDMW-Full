"""Synthetic PAC model volumes, independent of guide geometry and PAB tails."""

from dataclasses import FrozenInstanceError
import struct

import pytest

from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
from tests.test_pabv_parser import record
from tests.test_pac_cloth_guides import guide_fixture, pack_pac


def fixture(*records, layout=0, auxiliary=False, secondary_bounds=False, trailing=b"later-metadata"):
    source, guide_offsets = guide_fixture(layout=layout or 3)
    stop = guide_offsets["count"] if layout == 0 else guide_offsets["bbox"] + 24
    metadata = bytearray(source[80:stop])
    flags = (layout << 8) | (0x2000 if auxiliary else 0) | (4 if secondary_bounds else 0)
    struct.pack_into('<I', metadata, 0, flags)
    offsets = {"after_guides": 80 + len(metadata)}
    if auxiliary:
        metadata += struct.pack('<6f', -1, -2, -3, 1, 2, 3)
        metadata += struct.pack('<H', 2) + bytes(range(32))
        metadata += struct.pack('<H', 1) + bytes(range(24))
    offsets["palette"] = 80 + len(metadata)
    metadata += struct.pack('<H2I', 2, 0x12345678, 0x87654321)
    offsets["bounds"] = 80 + len(metadata)
    metadata += struct.pack('<6f', -3, -4, -5, 3, 4, 5)
    if secondary_bounds:
        metadata += struct.pack('<6f', -6, -7, -8, 6, 7, 8)
    offsets["volumes"] = 80 + len(metadata)
    metadata += struct.pack('<H', len(records)) + b''.join(records)
    offsets["end"] = 80 + len(metadata)
    metadata += trailing
    return pack_pac(metadata), offsets


@pytest.mark.parametrize('layout', [0, 3, 7])
@pytest.mark.parametrize('auxiliary,secondary', [(False, False), (True, True)])
def test_exact_layout_boundaries_flags_and_raw_keys(layout, auxiliary, secondary):
    first = record(key=0, flags=0x80000001)
    second = record(tag=4, parameters=(.5,), key=0x87654321, flags=0)
    data, offsets = fixture(first, second, layout=layout, auxiliary=auxiliary, secondary_bounds=secondary)
    original = bytes(data)
    result = decode_pac_embedded_volumes(data)
    assert result.metadata_flags == (layout << 8) | (0x2000 if auxiliary else 0) | (4 if secondary else 0)
    assert result.bone_palette == (0x12345678, 0x87654321)
    assert result.bounds == (-3., -4., -5., 3., 4., 5.)
    assert (result.file_offset, result.file_end) == (offsets['volumes'], offsets['end'])
    a, b = result.volumes
    assert (a.bone_key, b.bone_key) == (0, 0x87654321)  # No guessed index conversion.
    assert (a.flags, b.flags) == (0x80000001, 0)
    assert (a.serialized_shape, b.serialized_shape) == (5, 4)
    assert a.parameters == (.25, 2.) and b.parameters == (.5,)
    assert (a.file_offset, a.file_end) == (offsets['volumes'] + 2, offsets['volumes'] + 2 + len(first))
    assert (b.file_offset, b.file_end) == (a.file_end, result.file_end)
    assert data[result.file_end:result.file_end + 14] == b'later-metadata'
    assert data == original
    with pytest.raises(FrozenInstanceError):
        a.flags = 0
