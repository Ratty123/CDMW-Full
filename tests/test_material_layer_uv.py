"""PAC sampling parity at the Python/package boundary."""

import hashlib
import math

import pytest

from cdmw.domain.material_layer_uv import IDENTITY_UV_TRANSFORM, pac_layer_uv_transform


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
