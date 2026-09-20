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


def test_empty_is_distinct_from_unsupported_and_does_not_consume_later_metadata():
    data, offsets = fixture(trailing=b'\xff' * 200)
    result = decode_pac_embedded_volumes(data)
    assert result.volumes == ()
    assert result.file_end == result.file_offset + 2 == offsets['end']


@pytest.mark.parametrize('layout', [0, 3, 7])
def test_every_truncated_tail_is_rejected_with_geometry_still_present(layout):
    data, offsets = fixture(record(flags=1), layout=layout, auxiliary=True, secondary_bounds=True)
    for end in range(offsets['after_guides'], offsets['end']):
        # Keep valid LOD sections after section 0: they must never fill a short table/record.
        truncated = pack_pac(data[80:end])
        with pytest.raises(ValueError):
            decode_pac_embedded_volumes(truncated)
    assert len(decode_pac_embedded_volumes(pack_pac(data[80:offsets['end']])).volumes) == 1


@pytest.mark.parametrize('offset,value,reason', [
    (4, 4, 'header'),
    (16, 1, 'decompressed'),
    (80, 0x20, 'bone-group'),
    (81, 2, 'guide layout'),
    (84, 5, 'descriptor layout'),
    (117, 2, 'every descriptor'),
])
def test_unknown_header_compression_and_metadata_fail_explicitly(offset, value, reason):
    data, _ = fixture(record(flags=0))
    data = bytearray(data)
    data[offset] = value
    with pytest.raises(ValueError, match=reason):
        decode_pac_embedded_volumes(bytes(data))


def test_record_flags_are_mandatory_and_invalid_geometry_is_rejected():
    data, _ = fixture(record(), trailing=b'')
    with pytest.raises(ValueError, match='truncated'):
        decode_pac_embedded_volumes(data)
    for payload in (record(tag=3, parameters=(), flags=0), record(parameters=(-1., 2.), flags=0)):
        data, _ = fixture(payload)
        with pytest.raises(ValueError, match='shape tag|nonnegative'):
            decode_pac_embedded_volumes(data)


def test_nonfinite_bounds_are_rejected():
    data, offsets = fixture()
    data = bytearray(data)
    struct.pack_into('<f', data, offsets['bounds'], float('nan'))
    with pytest.raises(ValueError, match='bounds must contain finite'):
        decode_pac_embedded_volumes(bytes(data))
