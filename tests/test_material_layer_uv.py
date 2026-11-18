"""PAC sampling parity at the Python/package boundary."""

import hashlib
import math

import pytest

from cdmw.domain.material_layer_uv import (
    IDENTITY_UV_TRANSFORM,
    pac_blend_layer_uv_transform,
    pac_color_bytes,
    pac_grime_blend_bytes,
    pac_grime_uv_transform,
    pac_layer_uv_transform,
    pac_scratch_bytes,
)


PARAMETERS = (
    ("_dyeingTransformProperty0", 13 | (13 << 8)),
    ("_dyeingTransformProperty1", 26 | (26 << 8)),
    ("_dyeingTransformProperty3", 18 | (18 << 8)),
    ("_dyeingPropertyBlend", 92 | (127 << 16) | (127 << 24)),
)


@pytest.mark.parametrize("channel,scale,rotation", (("r", 13, 92), ("g", 26, 0), ("b", 18, 127)))
def test_honor_guard_affine_matches_authored_sampling(channel, scale, rotation):
    affine = pac_layer_uv_transform(PARAMETERS, channel)
    angle = rotation / 255 * 2 * math.pi - math.pi
    for u, v in ((0, 0), (0.5, 0.5), (0.13, 0.89), (1, 1)):
        x, y = (u - 0.5) / (scale / 255), (v - 0.5) / (scale / 255)
        expected = (x * math.cos(angle) - y * math.sin(angle) + 0.5,
                    x * math.sin(angle) + y * math.cos(angle) + 0.5)
        assert (affine[0] * u + affine[2] * v + affine[4],
                affine[1] * u + affine[3] * v + affine[5]) == pytest.approx(expected)


def test_absence_and_authored_zero_are_distinct():
    assert pac_layer_uv_transform((), "r") == IDENTITY_UV_TRANSFORM
    assert pac_layer_uv_transform((("_dyeingTransformProperty1", 0),), "r") == IDENTITY_UV_TRANSFORM
    assert pac_layer_uv_transform((("_dyeingTransformProperty0", 0),), "r") == pytest.approx(
        (100000, 0, 0, 100000, -49999.5, -49999.5)
    )
    assert pac_layer_uv_transform((("_dyeingTransformProperty0", "invalid"),), "r") == IDENTITY_UV_TRANSFORM


@pytest.mark.parametrize("numpy_enabled", (True, False))
@pytest.mark.parametrize("channel,expected", (
    ("r", "7448d5493301411ed3ffc17f9bda9dc991225afed033ae9c51420f9ab890453f"),
    ("g", "4f02fd167f9b7fe569a3535f0415e177f52ebe39e9cb618e4d70c6e0c3cd10f7"),
    ("b", "998a2cb6910d961b1556c57e7f6b44eb98580d1821a39fcf159992cd05f5e85f"),
))
def test_existing_combiner_bytes_are_unchanged(monkeypatch, numpy_enabled, channel, expected):
    from PySide6.QtGui import QColor, QImage
    from cdmw.domain.model_preview_materials import PreviewMaterialParameterInput, PreviewMaterialTextureInput
    from cdmw.rendering import material_combiner_images as images

    if not numpy_enabled:
        monkeypatch.setattr(images, "_numpy_module", lambda: None)
    source = QImage(8, 6, QImage.Format.Format_RGBA8888)
    for y in range(6):
        for x in range(8):
            source.setPixelColor(x, y, QColor(x * 31, y * 47, (x * 17 + y * 29) % 256, 255 - x * 13))
    item = PreviewMaterialTextureInput(layer_channel=channel, material_parameters=tuple(
        PreviewMaterialParameterInput(parameter_name=name, value=str(value)) for name, value in PARAMETERS
    ))
    output = images._apply_pac_layer_sampling_transform(source, item)
    # Recorded from the pre-extraction compositor, including alpha and repeat seams.
    assert hashlib.sha256(bytes(output.constBits())).hexdigest() == expected


# The plate of cd_phm_00_vest_0047_04, as the game's Ver2 shader reads its bytes.
PLATE_GRIME = (
    ("_grimeBlendingParameterR", 0x8E003333),
    ("_grimeBlendingParameterG", 0x41001010),
    ("_grimeBlendingParameterB", 0x1B003333),
    ("_grimeBlendingOpacityParameter", 0xA7E0FF93),
    ("_grimeBlendingOpacityParameter1", 0xFF7E),
)


@pytest.mark.parametrize("channel,expected", (
    ("r", (0x93, 0xFF, 0x8E)),  # ramp 0.576 to 1.0, intensity 1.114
    ("g", (0xE0, 0xA7, 0x41)),  # ramp 0.878 to 0.655 (the shader lifts the high edge)
    ("b", (0x7E, 0xFF, 0x1B)),  # blue reads the second range parameter
))
def test_plate_grime_ramp_and_intensity_bytes(channel, expected):
    assert pac_grime_blend_bytes(PLATE_GRIME, channel) == expected


def test_grime_ramp_needs_both_authored_parameters():
    assert pac_grime_blend_bytes(PLATE_GRIME[:3], "r") is None
    assert pac_grime_blend_bytes(PLATE_GRIME[3:], "r") is None
    assert pac_grime_blend_bytes(PLATE_GRIME, "a") is None
    assert pac_grime_blend_bytes((*PLATE_GRIME[:4],), "b") is None


def test_grime_samples_with_its_own_tiling_not_the_colour_layer_transform():
    # 0x8E003333: scale 0x33/255 = 0.2 (five tiles), angle byte 0 = -pi, no offset.
    affine = pac_grime_uv_transform(0x8E003333)
    for u, v in ((0, 0), (0.5, 0.5), (0.13, 0.89), (1, 1)):
        x, y = (u - 0.5) / 0.2, (v - 0.5) / 0.2
        expected = (x * math.cos(-math.pi) - y * math.sin(-math.pi) + 0.5,
                    x * math.sin(-math.pi) + y * math.cos(-math.pi) + 0.5)
        assert (affine[0] * u + affine[2] * v + affine[4],
                affine[1] * u + affine[3] * v + affine[5]) == pytest.approx(expected)
    assert pac_grime_uv_transform("invalid") is None
    assert pac_grime_uv_transform(None) is None


def test_pac_colour_text_is_red_green_blue_alpha():
    assert pac_color_bytes("#b2a4a4ff") == pytest.approx((0xB2 / 255, 0xA4 / 255, 0xA4 / 255, 1.0))
    assert pac_color_bytes("#c8b9b42d")[3] == pytest.approx(0x2D / 255)
    assert pac_color_bytes("") is None
    assert pac_color_bytes("#fff") is None


@pytest.mark.parametrize("channel,expected", (
    ("r", (0x9B, 0xFF)),  # roughness +0.216 of the remaining range, metal +1.0
    ("g", (0x7F, 0x7F)),  # no change
    ("b", (0x59, 0x7F)),  # roughness -0.302
))
def test_plate_scratch_bytes_are_one_per_layer(channel, expected):
    parameters = (("_scratchRoughness", 0x597F9B), ("_scratchMetallic", 0x7F7FFF))
    assert pac_scratch_bytes(parameters, channel) == expected


def test_scratch_needs_an_authored_parameter_and_fills_the_other_with_no_change():
    assert pac_scratch_bytes((), "r") is None
    assert pac_scratch_bytes((("_scratchRoughness", "invalid"),), "r") is None
    assert pac_scratch_bytes((("_scratchRoughness", 0x9B),), "r") == (0x9B, 127)
    assert pac_scratch_bytes((("_scratchMetallic", 0xFF),), "r") == (127, 0xFF)
    assert pac_scratch_bytes((("_scratchRoughness", 0x9B),), "a") is None


@pytest.mark.parametrize("mirror", (0, 2, 4, 6, 32))
def test_blend_layer_placement_follows_the_games_symbol_transform(mirror):
    """The Ver2 blend layer (`_detailDiffuseBlend`, the game's symbol), placed once.

    The game (permutation d4ae32939fa23e46, %1540 to %1623): scale from bytes 0 and 1
    of `_dyeingTransformProperty4`, the angle from byte 3 of `_dyeingPropertyBlend`,
    the translation from the half floats of `_dyeingBlendTextureTranslation`; bits 2
    and 4 of `_colorBlendingOptionBitFlag` negate U and V, which a repeating sampler
    reads as a mirror.
    """
    import struct

    translation = struct.unpack("<2e", struct.pack("<I", 3075252249))
    assert translation == pytest.approx((-0.008003, -0.456055), abs=1e-5)
    affine = pac_blend_layer_uv_transform((
        ("_dyeingTransformProperty4", 0x7FA9B0C8), ("_dyeingPropertyBlend", 0x60B97F00),
        ("_dyeingBlendTextureTranslation", 3075252249), ("_colorBlendingOptionBitFlag", mirror),
    ))
    sx, sy = 0xC8 / 255, 0xB0 / 255
    angle = 0x60 / 255 * 2 * math.pi - math.pi
    for u, v in ((0, 0), (0.5, 0.5), (0.13, 0.89), (1, 1)):
        x, y = (u - 0.5 - translation[0]) / sx, (v - 0.5 + translation[1]) / sy
        expected = [x * math.cos(angle) - y * math.sin(angle) + 0.5,
                    x * math.sin(angle) + y * math.cos(angle) + 0.5]
        if mirror & 2:
            expected[0] = 1 - expected[0]
        if mirror & 4:
            expected[1] = 1 - expected[1]
        assert (affine[0] * u + affine[2] * v + affine[4],
                affine[1] * u + affine[3] * v + affine[5]) == pytest.approx(expected)


def test_blend_layer_placement_defaults_to_the_whole_uv_square():
    assert pac_blend_layer_uv_transform(()) == pytest.approx((1, 0, 0, 1, 0, 0), abs=1e-6)
