"""PAC cloth guides and skeletal weights use different shader buffers."""
import struct
import pytest
from cdmw.modding.mesh_parser import PacDescriptor, _decode_pac_skin_influences, _decode_pac_vertex_records_bulk
from cdmw.modding.pac_cloth import pac_cloth_binding


def _record(*, gate=63, weights=(60, 50, 40, 30, 104, 82, 42, 27), extra=(102., 103.), palette=(1, 2, 3, 4, 100, 101)):
    data = bytearray(40)
    struct.pack_into("<2e", data, 12, *extra)
    struct.pack_into("<II", data, 20, *(palette[i] | palette[i+1] << 10 | palette[i+2] << 20 for i in (0, 3)))
    data[28:36] = bytes(weights)
    data[39] = gate
    return bytes(data)


@pytest.mark.parametrize("gate", [0, 20, 62, 0xC0, 0xFE])
def test_cloth_rows_have_four_bones_and_four_separate_guides(gate):
    record = _record(gate=gate)
    bones, weights = _decode_pac_skin_influences(record, 0)
    assert bones == (1, 2, 3, 4)
    assert weights == pytest.approx(tuple(v / 180 for v in (60, 50, 40, 30)))
    assert pac_cloth_binding(record, 0) == (gate & 63, (100, 101, 102, 103), (104, 82, 42, 27))
