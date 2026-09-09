"""PAC channel ownership through Python and the actual native rebuild command."""

from __future__ import annotations

import copy
import json
import math
import struct
import subprocess

import pytest

from cdmw.modding.mesh_pac_builder import _build_pac_in_place, _pack_pac_normal
from cdmw.modding.mesh_parser import (
    _find_pac_descriptors, _parse_pac_geometry_section, _parse_par_sections, parse_pac,
)
from tests.test_mesh_pac_topology_serializer import _pac_fixture


def _fixture():
    raw = bytearray(_pac_fixture(skinned=True))
    mesh = parse_pac(bytes(raw), "owned.pac")
    for offset in mesh.submeshes[0].source_vertex_offsets:
        struct.pack_into("<I", raw, offset + 16, _pack_pac_normal((0., 0., 1.), 0x800002AB))
    return bytes(raw), parse_pac(bytes(raw), "owned.pac")


def _lods(raw):
    sections = _parse_par_sections(raw)
    sec0 = sections[0]
    descriptors = _find_pac_descriptors(raw, sec0["offset"], sec0["size"], 4)
    return [_parse_pac_geometry_section(raw, "owned.pac", descriptors, section, 4 - section["index"])
            for section in sections if section["index"] in (1, 2, 3)]


@pytest.mark.parametrize("channel", [None, "uvs", "normals"])
def test_python_channel_edit_keeps_positions_bounds_and_lower_lods(channel):
    raw, original = _fixture()
    edited = copy.deepcopy(original)
    part = edited.submeshes[0]
    if channel == "uvs":
        part.uvs[0] = (0.007812, 0.125)
    elif channel == "normals":
        part.normals[0] = (0., 0., -1.)
    result = _build_pac_in_place(original, edited, raw)
    allowed = set()
    if channel:
        start, count = (8, 4) if channel == "uvs" else (16, 4)
        offset = part.source_vertex_offsets[0]
        allowed.update(range(offset + start, offset + start + count))
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(raw, result, strict=True)))
    parsed = parse_pac(result)
    if channel == "normals":
        assert parsed.submeshes[0].normals[0][2] < -.999
        offset = part.source_vertex_offsets[0] + 16
        assert (struct.unpack_from("<I", raw, offset)[0] ^ struct.unpack_from("<I", result, offset)[0]) & 0x800003FF == 0
    if channel == "uvs":
        assert parsed.submeshes[0].uvs[0] == (0.0078125, 0.125)


def test_expanded_bounds_compensate_lower_lods_with_position_only_writes():
    raw, original = _fixture()
    edited = copy.deepcopy(original)
    edited.submeshes[0].vertices = [(x + .01, y, z) for x, y, z in edited.submeshes[0].vertices]
    result = _build_pac_in_place(original, edited, raw)
    for before, after in zip(_lods(raw), _lods(result), strict=True):
        for a, b in zip(before.submeshes, after.submeshes, strict=True):
            assert a.faces == b.faces
            assert a.bone_indices == b.bone_indices and a.bone_weights == b.bone_weights
            for position, actual, offset in zip(a.vertices, b.vertices, a.source_vertex_offsets, strict=True):
                assert math.dist(position, actual) < 3e-5
                assert raw[offset + 6:offset + 40] == result[offset + 6:offset + 40]
    for actual, expected in zip(parse_pac(result).submeshes[0].vertices, edited.submeshes[0].vertices):
        assert actual == pytest.approx(expected, abs=3e-5)


def _native_rebuild(tmp_path, raw, edited):
    from cdmw.core.mesh_native import _write_pac_patch_tables
    from cdmw.core.common import hidden_subprocess_kwargs
    from cdmw.rendering.native_preview_core import find_native_preview_core_binary

    binary = find_native_preview_core_binary()
    if binary is None:
        pytest.skip("native preview core must be built for executable PAC codec coverage")
    original = tmp_path / "source.pac"
    original.write_bytes(raw)
    job, output, report = (tmp_path / name for name in ("job.json", "rebuilt.pac", "report.json"))
    job.write_text(json.dumps({
        "schema": "cdmw_mesh_rebuild_job_v1", "target_format": "pac", "layout": "native_pac",
        "rebuild_mode": "in_place", "original_binary_path": str(original),
        **_write_pac_patch_tables(edited, tmp_path),
    }))
    completed = subprocess.run([str(binary), "mesh-rebuild-job", str(job), str(output), str(report)],
                               capture_output=True, timeout=30, **hidden_subprocess_kwargs())
    return completed, json.loads(report.read_text()), output


@pytest.mark.parametrize("uv", [0.007812, -0.007812, 1.9999, 0.00006102, 2**-25, 1 + 2**-11, 1 + 3 * 2**-11,
                               1 + 2**-11 + 1e-10, 1 + 3 * 2**-11 - 1e-10])
def test_native_normal_sign_tangent_bits_and_half_float_rounding(tmp_path, uv):
    raw, original = _fixture()
    edited = copy.deepcopy(original)
    edited.submeshes[0].normals[0] = (0., 0., -1.)
    edited.submeshes[0].uvs[0] = (uv, uv)
    completed, report, output = _native_rebuild(tmp_path, raw, edited)
    assert completed.returncode == 0, report
    assert report["status"] == "ok"
    result = output.read_bytes()
    assert result == _build_pac_in_place(original, edited, raw)
    offset = original.submeshes[0].source_vertex_offsets[0]
    assert result[offset + 8:offset + 12] == struct.pack("<2e", uv, uv)
    assert (struct.unpack_from("<I", raw, offset + 16)[0] ^ struct.unpack_from("<I", result, offset + 16)[0]) & 0x800003FF == 0
    assert parse_pac(result).submeshes[0].normals[0][2] < -.999


@pytest.mark.parametrize('collapsed_extent', [False, True])
def test_native_no_edit_is_byte_identical(tmp_path, collapsed_extent):
    raw, original = _fixture()
    if collapsed_extent:
        data = bytearray(raw)
        part = original.submeshes[0]
        struct.pack_into('<f', data, part.source_descriptor_offset + 31, 1e-10)
        struct.pack_into('<H', data, part.source_vertex_offsets[0] + 4, 1234)
        raw = bytes(data)
        original = parse_pac(raw, original.path)
    completed, report, output = _native_rebuild(tmp_path, raw, original)
    assert completed.returncode == 0, report
    assert output.read_bytes() == raw


def test_native_refuses_uncompensated_shared_bounds_expansion(tmp_path):
    raw, original = _fixture()
    original.submeshes[0].vertices[1] = (2., 0., 0.)
    completed, report, output = _native_rebuild(tmp_path, raw, original)
    assert completed.returncode != 0
    assert "shared LOD preservation" in report["fallback_reason"]
    assert not output.exists()
