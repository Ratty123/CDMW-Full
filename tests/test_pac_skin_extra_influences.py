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


@pytest.mark.parametrize("gate", [63, 127, 255])
def test_ordinary_rows_have_six_bones_and_ignore_half_float_fields(gate):
    bones, weights = _decode_pac_skin_influences(_record(gate=gate), 0)
    assert bones == (1, 2, 3, 4, 100, 101)
    assert weights == pytest.approx(tuple(v / 366 for v in (60, 50, 40, 30, 104, 82)))
    assert pac_cloth_binding(_record(gate=gate), 0) is None


def test_invalid_guide_numbers_cannot_contaminate_skeletal_decode():
    record = _record(gate=0, extra=(-5., float("nan")))
    assert _decode_pac_skin_influences(record, 0)[0] == (1, 2, 3, 4)
    with pytest.raises(ValueError, match="guide"):
        pac_cloth_binding(record, 0)


def test_empty_and_truncated_rows_decode_without_inventing_bones():
    assert _decode_pac_skin_influences(_record(weights=(0,) * 8), 0) == ((), ())
    assert _decode_pac_skin_influences(bytes(39), 0) == ((), ())


def test_bulk_decoder_agrees_with_scalar_for_both_shader_branches():
    records = [_record(gate=gate) for gate in (0, 62, 63, 0xC0, 0xFF)]
    descriptor = PacDescriptor(name="part", material="part", bbox_min=(0., 0., 0.),
        bbox_extent=(1., 1., 1.), vertex_counts=[len(records)], index_counts=[0])
    bulk = _decode_pac_vertex_records_bulk(b"".join(records), 0, len(records), descriptor,
        include_uv=True, include_skin=True)
    for i, record in enumerate(records):
        indices, weights = _decode_pac_skin_influences(record, 0)
        assert tuple(bulk[4][i]) == indices
        assert tuple(bulk[5][i]) == pytest.approx(weights)
