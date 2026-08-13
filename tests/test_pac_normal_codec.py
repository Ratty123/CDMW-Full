"""The PAC normal lane, against the arithmetic the game's own shaders use.

The layout is not three packed components. Bits 10-19 and 20-29 are the normal's
x and y, z is reconstructed on the unit sphere with its sign in bit 30, bits 0-9
are the tangent's y component, and bit 31 is the bitangent handedness. These
tests pin that, because the previous reading treated bits 0-9 as the normal's z
and produced vectors that were not unit length.
"""

from __future__ import annotations

import math
import struct

import pytest

from cdmw.modding.mesh_parser import _decode_pac_normal
from cdmw.modding.mesh_pac_builder import _pack_pac_normal


def _record(packed: int) -> bytes:
    data = bytearray(40)
    struct.pack_into("<I", data, 16, packed)
    return bytes(data)


def _encode_component(value: float) -> int:
    return max(0, min(1023, round((value + 1.0) * 511.5)))


def _packed(x: float, y: float, *, z_negative: bool = False, tangent_y: int = 0, handedness: bool = False) -> int:
    packed = (tangent_y & 0x3FF) | (_encode_component(x) << 10) | (_encode_component(y) << 20)
    if z_negative:
        packed |= 0x40000000
    if handedness:
        packed |= 0x80000000
    return packed


# ── Decode ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("x", "y"),
    [(0.0, 0.0), (0.5, 0.0), (0.0, -0.5), (0.3, 0.4), (-0.6, 0.2), (0.7, -0.7)],
)
def test_a_decoded_normal_is_unit_length(x: float, y: float) -> None:
    normal = _decode_pac_normal(_record(_packed(x, y)), 0)
    assert math.sqrt(sum(value * value for value in normal)) == pytest.approx(1.0, abs=2e-3)


def test_the_z_sign_comes_from_bit_30() -> None:
    positive = _decode_pac_normal(_record(_packed(0.0, 0.0)), 0)
    negative = _decode_pac_normal(_record(_packed(0.0, 0.0, z_negative=True)), 0)
    assert positive[2] == pytest.approx(1.0, abs=2e-3)
    assert negative[2] == pytest.approx(-1.0, abs=2e-3)
    assert positive[0] == pytest.approx(negative[0])
    assert positive[1] == pytest.approx(negative[1])


def test_the_tangent_lane_does_not_move_the_normal() -> None:
    # Bits 0-9 used to be read as the normal's z. Sweeping them must now change
    # nothing at all about the decoded normal.
    baseline = _decode_pac_normal(_record(_packed(0.25, -0.5, tangent_y=0)), 0)
    for tangent_y in (1, 300, 512, 1023):
        assert _decode_pac_normal(_record(_packed(0.25, -0.5, tangent_y=tangent_y)), 0) == baseline


def test_the_handedness_bit_does_not_move_the_normal() -> None:
    plain = _decode_pac_normal(_record(_packed(0.25, -0.5)), 0)
    handed = _decode_pac_normal(_record(_packed(0.25, -0.5, handedness=True)), 0)
    assert plain == handed


def test_quantization_overshoot_clamps_instead_of_raising() -> None:
    # x and y both at the extreme make 1 - x^2 - y^2 negative; the shader clamps
    # at zero and so must this.
    normal = _decode_pac_normal(_record(_packed(1.0, 1.0)), 0)
    assert all(math.isfinite(value) for value in normal)
    assert normal[2] == pytest.approx(0.0)


def test_a_truncated_record_falls_back_rather_than_raising() -> None:
    assert _decode_pac_normal(b"\x00" * 8, 0) == (0.0, 1.0, 0.0)


# ── Encode ───────────────────────────────────────────────────────────

def test_encoding_preserves_the_tangent_y_component() -> None:
    existing = _packed(0.0, 0.0, tangent_y=0x2AB)
    assert _pack_pac_normal((0.1, 0.2, 0.9), existing) & 0x3FF == 0x2AB


def test_encoding_preserves_the_handedness_bit() -> None:
    existing = _packed(0.0, 0.0, handedness=True)
    assert _pack_pac_normal((0.1, 0.2, 0.9), existing) & 0x80000000 == 0x80000000
    assert _pack_pac_normal((0.1, 0.2, 0.9), 0) & 0x80000000 == 0


def test_encoding_authors_the_z_sign_from_the_normal() -> None:
    assert _pack_pac_normal((0.0, 0.0, 1.0), 0x40000000) & 0x40000000 == 0
    assert _pack_pac_normal((0.0, 0.0, -1.0), 0) & 0x40000000 == 0x40000000


def test_a_zero_z_keeps_whatever_sign_the_source_had() -> None:
    # The sign of zero is not information this function has, so it must not
    # invent one.
    assert _pack_pac_normal((1.0, 0.0, 0.0), 0x40000000) & 0x40000000 == 0x40000000
    assert _pack_pac_normal((1.0, 0.0, 0.0), 0) & 0x40000000 == 0


@pytest.mark.parametrize(
    "normal",
    [
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
        (0.5, 0.5, 0.7071),
        (-0.3, 0.4, -0.8660),
        (0.6, -0.6, 0.5291),
    ],
)
def test_a_normal_survives_the_round_trip_within_quantization(normal: tuple[float, float, float]) -> None:
    packed = _pack_pac_normal(normal, 0)
    decoded = _decode_pac_normal(_record(packed), 0)
    # One 10-bit step is 2/1023 on each of x and y; z carries their error through
    # the reconstruction, so it is checked by direction rather than per axis.
    assert decoded[0] == pytest.approx(normal[0], abs=2.0 / 1023.0)
    assert decoded[1] == pytest.approx(normal[1], abs=2.0 / 1023.0)
    assert math.copysign(1.0, decoded[2]) == math.copysign(1.0, normal[2])
    dot = sum(a * b for a, b in zip(decoded, normal))
    assert dot > 0.999


def test_the_round_trip_leaves_a_foreign_lane_byte_identical() -> None:
    existing = _packed(0.9, -0.2, tangent_y=0x155, handedness=True)
    packed = _pack_pac_normal((0.1, 0.2, 0.9), existing)
    assert packed & 0x800003FF == existing & 0x800003FF


# ── The topology serializer's protected bits still hold ──────────────

def test_authoring_a_derived_normal_leaves_the_protected_bits_alone() -> None:
    """The exact serializer may only write owned lanes.

    Bit 30 is now authored rather than copied, which would break that contract if
    a derived vertex could ever flip it. It cannot: the serializer refuses unless
    every parent agrees on the protected mask, so all parents share a z sign, and
    a convex combination of vectors that share a z sign keeps it. This pins that
    argument so a future change to the blend cannot quietly invalidate it.
    """
    from cdmw.modding.mesh_pac_topology_builder import protected_byte_mask

    mask = protected_byte_mask(skinned=True)
    assert mask[19] == 0xC0

    for z_negative in (False, True):
        template = _packed(0.2, 0.3, z_negative=z_negative, tangent_y=0x123, handedness=True)
        parent_z = -1.0 if z_negative else 1.0
        # Any convex blend of two same-signed parents, including the endpoints.
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            blended_z = parent_z * (1.0 - weight) + parent_z * weight
            packed = _pack_pac_normal((0.2, 0.3, blended_z), template)
            assert packed & 0xC0000000 == template & 0xC0000000
