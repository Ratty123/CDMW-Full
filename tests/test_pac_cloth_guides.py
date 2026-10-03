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
    inspect_guide_particle_initialization, inspect_guide_profile_admission, inspect_guide_topology,
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


@pytest.mark.parametrize('count,admitted', [(0, False), (1, True), (1024, True), (1025, False), (65535, False)])
@pytest.mark.parametrize('spline', [False, True])
def test_guide_profile_admission_uses_loader_count_limit_and_independent_mode_bit(count, admitted, spline):
    flags = (3 << 8) | (0x8000 if spline else 0)
    result = inspect_guide_profile_admission(flags, count)
    assert result == {'passes_resource_checks': admitted, 'guide_count_limit': 1024,
                      'default_profile_mode': 'spline' if spline else 'cloth'}
    assert not inspect_guide_profile_admission(flags & ~0xF00, 0)['passes_resource_checks']


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
