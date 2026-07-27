"""Guards for decoded numeric prefab values, above all the transform layout.

The layout was measured, not assumed: floats[3:7] is unit-length in 74,190 of
74,225 transforms sampled from the shipped archives. These lock in that reading
so a change that silently reorders the slots fails here.
"""

from __future__ import annotations

import math
import struct

import pytest

from cdmw.domain.archives.prefab_values import (
    describe_value,
    read_placement,
    rotation_degrees,
)


def _transform(scale, rotation, position, tile=None) -> bytes:
    raw = struct.pack("<10f", *scale, *rotation, *position)
    return raw + struct.pack("<i", tile) if tile is not None else raw


def test_reads_scale_rotation_and_position_in_that_order() -> None:
    raw = _transform((2.0, 3.0, 4.0), (0.0, 0.0, 0.0, 1.0), (10.0, 20.0, 30.0))
    placement = read_placement(raw)
    assert placement is not None
    assert placement.scale == (2.0, 3.0, 4.0)
    assert placement.rotation == (0.0, 0.0, 0.0, 1.0)
    assert placement.position == (10.0, 20.0, 30.0)
    assert placement.tile is None


def test_tiled_transform_carries_a_tile_index() -> None:
    raw = _transform((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0), tile=7)
    placement = read_placement(raw)
    assert placement is not None and placement.tile == 7


def test_quarter_turn_about_z_reads_back_as_ninety_degrees() -> None:
    """The real sample that confirmed the layout: (0, 0, sqrt2/2, sqrt2/2)."""
    half = math.sqrt(2.0) / 2.0
    raw = _transform((0.7, 0.7, 0.7), (0.0, 0.0, half, half), (0.0, 0.0, 0.0))
    placement = read_placement(raw)
    assert placement is not None
    assert abs(rotation_degrees(placement.rotation)[2] - 90.0) < 0.01
    assert placement.is_uniform_scale
    assert not placement.is_identity_rotation


def test_identity_rotation_is_recognised() -> None:
    placement = read_placement(_transform((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0)))
    assert placement is not None and placement.is_identity_rotation


@pytest.mark.parametrize("raw", [b"", b"\x00" * 12, b"\x00" * 41])
def test_non_transform_payloads_are_declined(raw: bytes) -> None:
    assert read_placement(raw) is None


def test_nan_transform_is_declined_rather_than_rendered() -> None:
    raw = struct.pack("<10f", *([float("nan")] * 10))
    assert read_placement(raw) is None
    # describe_value must not raise; it falls back to bytes.
    assert describe_value("Transform", raw)


def test_description_omits_defaults_and_keeps_what_matters() -> None:
    plain = describe_value(
        "Transform", _transform((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1.5, 2.5, 3.5))
    )
    assert plain == "position (1.5, 2.5, 3.5)"
    scaled = describe_value(
        "Transform", _transform((2.0, 2.0, 2.0), (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    )
    assert "scale 2" in scaled


@pytest.mark.parametrize(
    ("type_name", "raw", "expected"),
    [
        ("bool", b"\x01", "yes"),
        ("bool", b"\x00", "no"),
        ("float", struct.pack("<f", 0.2), "0.2"),
        ("uint8", b"\x07", "7"),
        ("uint32", struct.pack("<I", 4000), "4000"),
        ("int32", struct.pack("<i", -5), "-5"),
        ("float3", struct.pack("<3f", 1.0, 2.0, 3.0), "(1, 2, 3)"),
    ],
)
def test_scalar_rendering(type_name: str, raw: bytes, expected: str) -> None:
    assert describe_value(type_name, raw) == expected


def test_unknown_type_falls_back_to_bytes_not_silence() -> None:
    assert describe_value("SomethingElse", b"\xde\xad") == "de ad"
