"""Synthetic PAC guide records; no game assets or external tools required."""

from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from cdmw.modding.pac_cloth_guides import (
    decode_pac_cloth_guides, inspect_guide_constraint_geometry,
    inspect_guide_particle_initialization, inspect_guide_topology,
)
from tools.pac_cloth_guide_study import inspect_pac


def guide_fixture(layout=3, *, count=3):
    metadata = bytearray(struct.pack("<IB", layout << 8, 4) + bytes(32) + struct.pack("<H", 1))
    metadata += b"\x04mesh\x04mesh"
    descriptor = bytearray(64)
    descriptor[:3] = b"\x01\x00\x01"
    struct.pack_into("<8f", descriptor, 3, 1, 1, -1, 0, -1, 2, 2, 2)
    descriptor[35:40] = bytes((4, 0, 1, 2, 3))
    struct.pack_into("<4H4I", descriptor, 40, 3, 3, 3, 3, 3, 3, 3, 3)
    metadata += descriptor
    offsets = {"count": 80 + len(metadata)}
    metadata += struct.pack("<H", count)
    offsets["vertices"] = 80 + len(metadata)
    for i in range(count):
        # High bits are not part of positions or the fourth 10-bit palette slot.
        metadata += struct.pack("<4HI4B", 0x8000, 16384, 32767, 0xFC07,
                                9 | (513 << 10) | (1023 << 20) | (3 << 30),
                                100, 80, 60, 14 + (i % 3))
    offsets["channel_a"] = 80 + len(metadata)
    metadata += bytes([19] * count)
    offsets["channel_b"] = 80 + len(metadata)
    metadata += bytes([255] * count)
    offsets["triangle_count"] = 80 + len(metadata)
    metadata += struct.pack("<4H", 3, 0, 1, 2)
    offsets["alpha_bits"] = 80 + len(metadata)
    metadata += struct.pack(f"<{(count + 31) // 32}I", *([5] * ((count + 31) // 32)))
    offsets["groups_a"] = 80 + len(metadata)
    metadata += struct.pack("<H", 2)
    metadata += struct.pack("<3H", 2, 1, 2)
    if layout == 7:
        metadata += b"\xa5"
    metadata += struct.pack("<H", 0)
    if layout == 7:
        metadata += b"\x5a"
    offsets["records_10"] = 80 + len(metadata)
    metadata += struct.pack("<H", 1) + bytes(range(10))
    metadata += struct.pack("<3H", 2, 0, 1)  # indices_a
    metadata += struct.pack("<HI", 1, 0x12345678)  # records_4
    metadata += struct.pack("<5H", 2, 1, 2, 1, 0)  # two groups_b
    metadata += struct.pack("<2H", 1, 2)  # indices_b
    offsets["bbox"] = 80 + len(metadata)
    metadata += struct.pack("<6f", -2, 3, 5, 4, 8, 12)
    # Opaque metadata after the guide section must not be consumed as guides.
    metadata += b"remaining-palette-and-physics-data"
    return pack_pac(metadata), offsets


def pack_pac(metadata):
    header = bytearray(80)
    header[:8] = b"PAR \x03\x09\x00\x01"
    struct.pack_into("<II", header, 16, len(metadata), len(metadata))
    geometry = bytes(3 * 40) + struct.pack("<3H", 0, 1, 2)
    for section in range(1, 5):
        struct.pack_into("<II", header, 16 + section * 8, len(geometry), len(geometry))
    return bytes(header) + bytes(metadata) + geometry * 4


@pytest.mark.parametrize("layout", [3, 7])
def test_guide_geometry_uses_its_own_bounds_and_preserves_packed_weights(layout):
    data, offsets = guide_fixture(layout)
    original_hash = hashlib.sha256(data).hexdigest()
    guides = decode_pac_cloth_guides(data)
    assert guides.layout == layout
    assert guides.vertices[0] == pytest.approx((-2, 3 + 16384 / 32767 * 8, 17))
    assert guides.cpu_unskinned_vertices[0] == pytest.approx((-2 + 32768 / 32767 * 4, 3 + 16384 / 32767 * 8, 17))
    assert guides.bone_indices == ((9, 513, 1023, 7),) * 3
    assert [sum(row) for row in guides.bone_weight_bytes] == [254, 255, 256]
    assert guides.triangles == ((0, 1, 2),)
    assert guides.channel_a == bytes([19] * 3)
    assert guides.channel_b == bytes([255] * 3)
    assert guides.alpha_words == (5,)
    assert guides.ranges[-1].offset == offsets["bbox"]
    assert guides.ranges[-1].stride * guides.ranges[-1].count == 24
    assert len([r for r in guides.ranges if r.name.endswith("_tag")]) == (2 if layout == 7 else 0)
    assert hashlib.sha256(data).hexdigest() == original_hash


def test_alpha_bitset_rounds_up_at_a_word_boundary():
    data, offsets = guide_fixture(count=33)
    guides = decode_pac_cloth_guides(data)
    assert len(guides.vertices) == 33
    assert guides.alpha_words == (5, 5)
    assert guides.ranges[-1].offset == offsets["bbox"]


def test_particle_initialization_uses_channels_not_topology_or_alpha_bitset():
    data, offsets = guide_fixture(count=6)
    data = bytearray(data)
    data[offsets["channel_a"]:offsets["channel_a"] + 6] = bytes((0, 1, 31, 32, 128, 255))
    data[offsets["channel_b"]:offsets["channel_b"] + 6] = bytes((0, 1, 127, 128, 254, 255))
    original = bytes(data)
    guides = decode_pac_cloth_guides(original)
    result = inspect_guide_particle_initialization(guides)
    # The fixture's alpha bits and group starts deliberately select other vertices.
    assert result["fixed_vertex_indices"] == [5]
    assert result["inverse_mass_factors"] == [1, 1, 1, 1, 1, 0]
    assert result["position_blend_without_vertex_alpha"] == [0, 0, 0, 0, 0, 1]
    assert result["position_blend_with_vertex_alpha"] == [
        0, 0.0039215087890625, 0.498046875, 0.501953125, 0.99609375, 1,
    ]
    assert result["group_ids"] == [0, 1, 31, 32, 128, 255]
    assert result["dynamic_fix_group_ids"] == [None, 1, 31, None, None, None]
    assert inspect_pac(original)["particle_initialization"] == result
    assert bytes(data) == original
    assert guides.channel_a == bytes((0, 1, 31, 32, 128, 255))
    assert guides.channel_b == bytes((0, 1, 127, 128, 254, 255))


def test_all_byte_values_keep_partial_blend_distinct_from_fixed_mass():
    data, offsets = guide_fixture(count=256)
    data = bytearray(data)
    data[offsets["channel_b"]:offsets["channel_b"] + 256] = bytes(range(256))
    result = inspect_pac(bytes(data))["particle_initialization"]
    assert result["fixed_vertex_indices"] == [255]
    assert result["inverse_mass_factors"] == [1] * 255 + [0]
    blends = result["position_blend_with_vertex_alpha"]
    assert blends[0] == 0 and blends[-1] == 1
    assert all(a < b for a, b in zip(blends, blends[1:]))
    assert sum(result["position_blend_without_vertex_alpha"]) == 1


def topology_fixture(layout):
    data, offsets = guide_fixture(layout, count=4)
    metadata = bytearray(data[80:offsets["triangle_count"]])
    metadata += struct.pack("<7H", 6, 0, 1, 2, 1, 0, 3)
    metadata += struct.pack("<I", 3)  # Alpha set on vertices 0 and 1.
    metadata += struct.pack("<H", 2)
    for group in ((0, 2), (1, 3)):
        metadata += struct.pack("<3H", 2, *group)
        if layout == 7:
            metadata += b"\xa5"
    records = ((1, 2, 0, 0, 0xE300), (2, 0, 0, 0, 0x100),
               (0, 3, 0, 0, 0), (3, 1, 0, 0, 0), (0, 1, 2, 3, 1),
               (0, 1, 2, 65535, 0x5C00), (1, 0, 3, 65535, 0))
    metadata += struct.pack("<H", len(records))
    metadata += b"".join(struct.pack("<5H", *row) for row in records)
    per_vertex = ((1, 2, 4, 5, 6), (0, 3, 4, 5, 6), (0, 1, 4, 5), (2, 3, 4, 6))
    metadata += struct.pack("<19H", 18, *(i for row in per_vertex for i in row))
    metadata += struct.pack("<9H", 4, 0, 0x203, 5, 0x203, 10, 0x103, 14, 0x103)
    metadata += struct.pack("<H", 4)
    for row in per_vertex:
        metadata += struct.pack("<4H", 3, *row[:3])
    metadata += struct.pack("<11H", 10, 0, 1, 1, 2, 2, 0, 0, 3, 3, 1)
    metadata += data[offsets["bbox"]:offsets["bbox"] + 24]
    metadata[offsets["channel_b"] - 80:offsets["channel_b"] - 76] = bytes((255, 255, 128, 0))
    return pack_pac(metadata)


@pytest.mark.parametrize("supplied", [False, True])
def test_authored_constraint_rest_geometry_uses_cpu_or_supplied_particle_positions(supplied):
    guides = decode_pac_cloth_guides(topology_fixture(3))
    positions = ((0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2))
    kwargs = {"particle_positions": positions} if supplied else {}
    if not supplied:
        guides = replace(guides, cpu_unskinned_vertices=positions)
    result = inspect_guide_constraint_geometry(guides, **kwargs)
    assert result["position_basis"] == ("caller_supplied" if supplied else "cpu_unskinned")
    rows = result["constraints"]
    assert [row["source_index"] for row in rows] == list(range(7))
    assert [row["rest_length"] for row in rows[:4]] == pytest.approx([math.sqrt(8), 2, 2, math.sqrt(8)])
    assert [row["rest_area"] for row in rows[5:]] == [2, 2]
    hinge = rows[4]
    assert hinge["vertices"] == (0, 1, 2, 3)
    assert hinge["rest_angle_radians"] == pytest.approx(math.pi / 2)
    assert hinge["bending_coefficients"] == pytest.approx((math.sqrt(3), 0, -math.sqrt(3) / 2, -math.sqrt(3) / 2))
    assert hinge["degenerate"] is False
    assert hinge["cotangent_limit_passed"] is True
    assert guides.constraint_records[0][-1] == 0xE300


def test_flat_adjacent_faces_use_pi_rest_angle_and_translation_preserves_rest_geometry():
    guides = decode_pac_cloth_guides(topology_fixture(3))
    points = ((0, 0, 0), (2, 0, 0), (0, 2, 0), (0, -2, 0))
    baseline = inspect_guide_constraint_geometry(guides, particle_positions=points)
    assert baseline["constraints"][4]["rest_angle_radians"] == pytest.approx(math.pi)
    shifted = tuple(tuple(v + offset for v, offset in zip(point, (7, -3, 9))) for point in points)
    assert inspect_guide_constraint_geometry(guides, particle_positions=shifted) == baseline


def test_degenerate_and_unrecognized_constraints_remain_explicit_and_json_safe():
    guides = decode_pac_cloth_guides(topology_fixture(3))
    guides = replace(guides, constraint_records=guides.constraint_records + ((0, 1, 2, 4, 1),))
    result = inspect_guide_constraint_geometry(guides)
    hinge = result["constraints"][4]
    assert hinge["degenerate"] is True
    assert hinge["rest_angle_radians"] == pytest.approx(math.pi / 2)
    assert hinge["bending_coefficients"] is None
    assert result["constraints"][-1] == {"source_index": 7, "kind": "unrecognized", "vertices": ()}
    json.dumps(result, allow_nan=False)


def test_narrow_triangle_reports_the_bending_cotangent_limit_without_selecting_a_solver():
    guides = decode_pac_cloth_guides(topology_fixture(3))
    result = inspect_guide_constraint_geometry(
        guides, particle_positions=((0, 0, 0), (2, 0, 0), (0, 0.1, 0), (0, -2, 0)),
    )
    hinge = result["constraints"][4]
    assert hinge["degenerate"] is False
    assert hinge["cotangent_limit_passed"] is False
    assert hinge["bending_coefficients"] is not None


@pytest.mark.parametrize("positions", [(), ((0, 0, 0),) * 3, ((0, 0),) * 4, ((float("nan"), 0, 0),) * 4])
def test_constraint_geometry_rejects_incomplete_or_nonfinite_particle_positions(positions):
    guides = decode_pac_cloth_guides(topology_fixture(3))
    with pytest.raises(ValueError, match="one finite 3D position per guide vertex"):
        inspect_guide_constraint_geometry(guides, particle_positions=positions)


@pytest.mark.parametrize("layout", [3, 7])
def test_constraint_storage_retains_high_bytes_and_matches_authored_topology(layout):
    data = topology_fixture(layout)
    guides = decode_pac_cloth_guides(data)
    assert guides.groups_a == ((0, 2), (1, 3))
    assert guides.group_a_tags == ((165, 165) if layout == 7 else ())
    assert guides.constraint_records[0] == (1, 2, 0, 0, 0xE300)
    assert guides.constraint_records[5] == (0, 1, 2, 65535, 0x5C00)
    assert guides.vertex_constraint_spans == ((0, 0x203), (5, 0x203), (10, 0x103), (14, 0x103))
    result = inspect_pac(data)
    evidence = result["topology_evidence"]
    assert evidence["record_counts"] == {"pair": 4, "hinge": 1, "triangle": 2, "unrecognized": 0}
    assert evidence["record_high_bytes"] == [0, 1, 92, 227]
    assert evidence["guide_edge_count"] == 5
    assert evidence["pair_records_missing_edges"] == 1
    assert evidence["pair_records_extra_edges"] == 0
    assert evidence["alpha_vertex_count"] == 2
    assert all(value for value in evidence.values() if isinstance(value, bool))
    assert result["guides"]["constraint_records"][0][-1] == 0xE300


@pytest.mark.parametrize("fault", ["unknown_kind", "hinge", "reference", "span", "empty_spans", "groups", "duplicate_edge", "alpha", "group_start"])
def test_topology_evidence_reports_mismatches_without_guessing_solver_data(fault):
    guides = decode_pac_cloth_guides(topology_fixture(3))
    expected_false = "vertex_constraint_spans_match_records"
    if fault == "unknown_kind":
        records = ((1, 2, 0, 0, 0xE302),) + guides.constraint_records[1:]
        guides = replace(guides, constraint_records=records)
    elif fault == "hinge":
        records = guides.constraint_records[:4] + ((0, 2, 1, 3, 1),) + guides.constraint_records[5:]
        guides = replace(guides, constraint_records=records)
        expected_false = "hinge_records_match_adjacent_triangles"
    elif fault == "reference":
        guides = replace(guides, constraint_indices=(65535,) + guides.constraint_indices[1:])
    elif fault == "span":
        guides = replace(guides, vertex_constraint_spans=((0, 65535),) + guides.vertex_constraint_spans[1:])
    elif fault == "empty_spans":
        guides = replace(guides, vertex_constraint_spans=())
        expected_false = "groups_b_match_first_span"
    elif fault == "groups":
        guides = replace(guides, groups_b=((0, 2, 4),) + guides.groups_b[1:])
        expected_false = "groups_b_match_first_span"
    elif fault == "duplicate_edge":
        guides = replace(guides, edge_indices=guides.edge_indices + (0, 1))
        expected_false = "edge_table_matches_triangles"
    elif fault == "alpha":
        guides = replace(guides, alpha_words=(1,))
        expected_false = "alpha_bits_match_channel_b_255"
    else:
        guides = replace(guides, groups_a=((2, 0), (1, 3)))
        expected_false = "group_starts_match_alpha_bits"
    evidence = inspect_guide_topology(guides)
    assert evidence[expected_false] is False
    if fault == "unknown_kind":
        assert evidence["record_counts"]["unrecognized"] == 1
        assert guides.constraint_records[0][-1] == 0xE302


def test_absent_flag_does_not_misread_bone_palette_count_as_guides():
    data, _ = guide_fixture()
    data = bytearray(data)
    struct.pack_into("<I", data, 80, 0x01000082)
    assert decode_pac_cloth_guides(data) is None
    result = inspect_pac(bytes(data))
    assert result["status"] == "absent"
    assert "other physics" in result["reason"]


@pytest.mark.parametrize("field", ["vertices", "channel_a", "channel_b", "triangle_count", "alpha_bits", "groups_a", "records_10", "bbox"])
def test_declared_metadata_boundary_cannot_borrow_geometry_bytes(field):
    data, offsets = guide_fixture()
    # Leave complete render geometry present after a shorter metadata section.
    truncated = pack_pac(data[80:offsets[field] + 1])
    with pytest.raises(ValueError, match="truncated"):
        decode_pac_cloth_guides(truncated)


@pytest.mark.parametrize("fault", ["header", "compressed", "layout", "part_count", "vertex_count", "triangle_index", "triangle_count", "bbox_nan", "bbox_extent"])
def test_unsupported_or_invalid_guides_are_not_guessed(fault):
    data, offsets = guide_fixture()
    data = bytearray(data)
    if fault == "header":
        data[5] = 8
    elif fault == "compressed":
        struct.pack_into("<I", data, 16, struct.unpack_from("<I", data, 16)[0] - 1)
    elif fault == "layout":
        data[81] = 2
    elif fault == "part_count":
        struct.pack_into("<H", data, 80 + 37, 2)
    elif fault == "vertex_count":
        struct.pack_into("<H", data, offsets["count"], 1025)
    elif fault == "triangle_index":
        struct.pack_into("<H", data, offsets["triangle_count"] + 2, 3)
    elif fault == "triangle_count":
        struct.pack_into("<H", data, offsets["triangle_count"], 4)
    elif fault == "bbox_nan":
        struct.pack_into("<f", data, offsets["bbox"], float("nan"))
    else:
        struct.pack_into("<f", data, offsets["bbox"] + 12, -1)
    with pytest.raises(ValueError):
        decode_pac_cloth_guides(data)
    result = inspect_pac(bytes(data))
    assert result["status"] == "unavailable"
    assert "guides" not in result


def test_read_only_study_cli_emits_decoded_and_unavailable_results(tmp_path):
    data, _ = guide_fixture(7)
    pac = tmp_path / "guide.pac"
    pac.write_bytes(data)
    missing = tmp_path / "missing.pac"
    result = subprocess.run([sys.executable, "tools/pac_cloth_guide_study.py", str(pac), str(missing)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    first, second = report["assets"]
    assert first["status"] == "decoded"
    assert first["vertex_count"] == 3 and first["triangle_count"] == 1
    assert first["guides"]["channel_a"] == [19, 19, 19]
    assert first["particle_initialization"]["fixed_vertex_indices"] == [0, 1, 2]
    assert first["constraint_geometry"]["position_basis"] == "cpu_unskinned"
    assert "initialization, not final runtime motion" in first["limitations"]
    assert second["status"] == "unavailable"
    assert pac.read_bytes() == data
