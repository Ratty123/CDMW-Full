"""A PAC detail-layer transform baked into a vertically flipped copy.

The material combiner flips sources before it bakes the layer UV transform,
while the game shader samples in D3D order (v = 0 is the first DDS row). On a
flipped copy the Y offset and the rotation need the opposite sign, so that
flipping the result back gives what the shader would sample.
"""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.rendering.material_combiner_images import _apply_pac_layer_sampling_transform


def _layer(scale_x: int, scale_y: int, offset_x: int, offset_y: int, rotation: int):
    transform = scale_x | scale_y << 8 | offset_x << 16 | offset_y << 24
    return SimpleNamespace(
        layer_channel="r",
        parameter_name="_detailDiffuseMaskR",
        material_parameters=(
            SimpleNamespace(parameter_name="_dyeingTransformProperty0", value=str(transform)),
            SimpleNamespace(parameter_name="_dyeingPropertyBlend", value=str(rotation)),
        ),
    )


def _pattern(size: int = 8) -> QImage:
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    for y in range(size):
        for x in range(size):
            image.setPixelColor(x, y, QColor(x * 32, y * 32, (x * 7 + y * 13) % 256, 255))
    return image


def _pixels(image: QImage) -> list[tuple[int, int, int, int]]:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return [image.pixelColor(x, y).getRgb() for y in range(image.height()) for x in range(image.width())]


@pytest.mark.parametrize("layer", [
    _layer(255, 255, 0, 64, 128),     # a quarter-height Y offset, no rotation
    _layer(255, 255, 0, 0, 64),       # about a quarter turn
    _layer(128, 200, 32, 96, 40),     # scale, both offsets and a rotation
])
def test_a_flipped_copy_gives_the_shaders_sampling_once_flipped_back(layer):
    source = _pattern()
    expected = _apply_pac_layer_sampling_transform(source, layer)
    flipped = _apply_pac_layer_sampling_transform(
        source.flipped(Qt.Orientation.Vertical), layer, flip_vertical=True,
    )
    back = flipped.flipped(Qt.Orientation.Vertical)
    for got, want in zip(_pixels(back), _pixels(expected)):
        assert all(abs(a - b) <= 1 for a, b in zip(got, want))


def test_without_the_flip_sign_the_offset_case_differs():
    # Guards the test above: ignoring the flip moves the offset the wrong way.
    layer = _layer(255, 255, 0, 64, 128)
    source = _pattern()
    expected = _apply_pac_layer_sampling_transform(source, layer)
    wrong = _apply_pac_layer_sampling_transform(source.flipped(Qt.Orientation.Vertical), layer)
    assert _pixels(wrong.flipped(Qt.Orientation.Vertical)) != _pixels(expected)
