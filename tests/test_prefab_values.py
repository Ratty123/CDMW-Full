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
    degrees_to_rotation,
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


def test_placement_round_trips_through_bytes() -> None:
    from cdmw.domain.archives.prefab_values import write_placement

    raw = _transform((1.5, 2.5, 3.5), (0.0, 0.0, 0.0, 1.0), (10.0, -20.0, 30.0), tile=4)
    placement = read_placement(raw)
    assert placement is not None
    assert write_placement(placement) == raw


def test_degrees_convert_back_to_the_same_angles() -> None:
    from cdmw.domain.archives.prefab_values import degrees_to_rotation

    for angles in [(0.0, 0.0, 90.0), (45.0, 0.0, 0.0), (0.0, 30.0, 0.0), (10.0, 20.0, 30.0)]:
        quaternion = degrees_to_rotation(*angles)
        assert abs(math.sqrt(sum(v * v for v in quaternion)) - 1.0) < 1e-6
        recovered = rotation_degrees(quaternion)
        for original, value in zip(angles, recovered):
            assert abs(original - value) < 0.01


def test_rotation_degrees_takes_a_precision() -> None:
    """Two decimals reads well; an editor seeding boxes needs more than that."""
    quaternion = degrees_to_rotation(12.3456789, 5.0, -7.5)
    assert rotation_degrees(quaternion)[0] == round(rotation_degrees(quaternion)[0], 2)
    fine = rotation_degrees(quaternion, digits=6)
    assert abs(fine[0] - 12.3456789) < 1e-4


def test_pole_orientations_are_flagged() -> None:
    """Weapon child sockets sit at pitch 90, where yaw and roll collapse."""
    from cdmw.domain.archives.prefab_values import is_near_pole

    assert is_near_pole((0.5, 0.5, -0.5, 0.5))
    assert not is_near_pole((0.0, 0.0, 0.0, 1.0))


def test_euler_round_trip_is_lossy_at_the_pole() -> None:
    """The reason an untouched rotation must never be reconverted.

    This is not a defect being locked in -- it is why the placement editor
    reuses the decoded quaternion for any group the user did not edit.
    """
    from cdmw.domain.archives.prefab_values import write_placement

    pole = (0.5, 0.5, -0.5, 0.5)
    rebuilt = degrees_to_rotation(*rotation_degrees(pole))
    dot = min(1.0, abs(sum(a * b for a, b in zip(pole, rebuilt))))
    assert math.degrees(2 * math.acos(dot)) > 45.0
    assert write_placement(
        read_placement(struct.pack("<10f", 1, 1, 1, *pole, 0, 0, 0))
    ) != write_placement(
        read_placement(struct.pack("<10f", 1, 1, 1, *rebuilt, 0, 0, 0))
    )
