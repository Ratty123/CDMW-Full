"""Typed reflection arrays must consume exactly their declared bytes."""
import struct

import pytest

from cdmw.core.prefab_binary import decode_prefab_binary


def text(value):
    data = value.encode()
    return struct.pack('<I', len(data)) + data


def payload(revision=14, *, count=1, tail=b'', component=1):
    def member(name, kind, size, attr=0, extra=0):
        return text(name) + text('float' if kind == 3 else 'string') + struct.pack('<HHHH', kind, size, attr, extra)
    members = [member('_empty', 3, 4, 0x1000), member('_files', 10, 1, 0x1000), member('_dimensions', 7, 8, 0x1000)]
    members += [member(f'_unused{i}', 0, 4) for i in range(13)]
    members += [member('_last', 0, 4)]
    types = text('ParameterizedMotionSpace') + struct.pack('<H', len(members)) + b''.join(members)
    types += text('ParameterDimension') + struct.pack('<H', 1) + member('_dimensionType', 2, 4, extra=4)
    header = struct.pack('<HHH', 0xffff, 4, 0) + bytes(8) + struct.pack('<IH', revision, 2) + types + bytes(4)
    base = len(header) + 28
    def array(n):
        return (b'\x01' if not n else b'\x00' + struct.pack('<I', n)) if revision >= 15 else struct.pack('<I', n)
    blob = bytearray(struct.pack('<H', 3) + (1 << 16).to_bytes(3, 'little') + bytes(4))
    blob += array(0)  # absent from mask but still serialized
    blob += array(1) + text('1_pc/1_phm/example.paa')
    blob += array(count) + bytes(13)
    blob += struct.pack('<HBBH', 1, 1, component, 0)
    owner = len(blob)
    blob += struct.pack('<QI', 0, base + owner + 12)
    contents = bytes(4) + text('LeftStickX')
    blob += contents + struct.pack('<I', len(contents)) + struct.pack('<f', 3.5) + tail
    return header + struct.pack('<IIIQII', 1, base + len(blob), 0, 0xffffffffffffffff, base, len(blob)) + blob


@pytest.mark.parametrize('revision', [14, 15])
def test_motion_arrays_named_enum_and_wide_mask(revision):
    doc = decode_prefab_binary(payload(revision))
    assert doc.walk_complete, doc.walk_note
    assert doc.root_numbers[0].raw == b''
    assert doc.root_values[0][1].text == '1_pc/1_phm/example.paa'
    assert doc.objects[0].values[0][1].text == 'LeftStickX'
    assert doc.objects[0].type_source == 'stated'
    assert struct.unpack('<f', doc.root_numbers[-1].raw) == (3.5,)


@pytest.mark.parametrize('options', [{'tail': bytes(5)}, {'count': 2}, {'component': 12}])
def test_motion_walk_rejects_tolerance_and_type_guessing(options):
    assert not decode_prefab_binary(payload(**options)).walk_complete
