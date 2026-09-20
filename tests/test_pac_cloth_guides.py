"""Synthetic PAC guide records; no game assets or external tools required."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
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
    assert "physical-pin" in first["limitations"]
    assert second["status"] == "unavailable"
    assert pac.read_bytes() == data
