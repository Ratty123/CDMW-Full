"""A tiled PAC layer baked straight onto the composite's canvas.

Baked at its own tile size, a layer repeated 14 times across a part kept 25 px per
repeat, and scaling that up to the canvas left the Mesh Editor's fallback fabric soft
(Demenissian Council Robes, 2026-11-23). Baked at the canvas size it keeps the
canvas's density, and the tile is reduced first so the denser sampling does not alias.
"""
from types import SimpleNamespace

import numpy
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage

from cdmw.rendering.material_combiner_images import _apply_pac_layer_sampling_transform


def _robe_detail_layer():
    """The robe's detail G layer: `_dyeingTransformProperty1` 4626, 14.17 repeats."""
    return SimpleNamespace(
        layer_channel="g",
        parameter_name="_detailDiffuseMaskG",
        material_parameters=(
            SimpleNamespace(parameter_name="_dyeingTransformProperty1", value="4626"),
            SimpleNamespace(parameter_name="_dyeingPropertyBlend", value="2136080128"),
        ),
    )


def _image(pixels: numpy.ndarray) -> QImage:
    height, width = pixels.shape[:2]
    rgba = numpy.ascontiguousarray(pixels.astype(numpy.uint8))
    return QImage(rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def _array(image: QImage) -> numpy.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    view = image.constBits()
    return numpy.frombuffer(view, dtype=numpy.uint8).reshape(image.height(), image.bytesPerLine())[
        :, : image.width() * 4].reshape(image.height(), image.width(), 4).astype(numpy.float64)


def _detail(image: QImage) -> float:
    """Mean neighbour difference: how much fine detail survives."""
    grey = _array(image)[:, :, :3].mean(axis=2)
    return float(numpy.abs(numpy.diff(grey, axis=1)).mean() + numpy.abs(numpy.diff(grey, axis=0)).mean())


def _blobs(size: int = 256) -> QImage:
    """A tile with features a few pixels wide, like a damask or lace pattern."""
    rng = numpy.random.default_rng(7)
    coarse = rng.integers(0, 256, (size // 8, size // 8, 1))
    grey = numpy.kron(coarse, numpy.ones((8, 8, 1)))
    return _image(numpy.concatenate([grey, grey, grey, numpy.full((size, size, 1), 255)], axis=2))


def test_without_an_output_size_the_bake_keeps_the_tile_size():
    tile = _blobs()
    baked = _apply_pac_layer_sampling_transform(tile, _robe_detail_layer())
    assert (baked.width(), baked.height()) == (256, 256)


def test_a_layer_baked_onto_the_canvas_keeps_far_more_detail_than_one_scaled_up():
    tile, layer, canvas = _blobs(), _robe_detail_layer(), QSize(1024, 1024)
    old = _apply_pac_layer_sampling_transform(tile, layer).scaled(
        1024, 1024, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    new = _apply_pac_layer_sampling_transform(tile, layer, output_size=canvas)
    assert (new.width(), new.height()) == (1024, 1024)
    assert _detail(new) > 2.0 * _detail(old)


def test_the_denser_bake_does_not_alias_a_pattern_finer_than_one_repeat_can_show():
    # A one-pixel checkerboard: one repeat on a 1024 canvas is 72 px, so the 256 px
    # pattern cannot be shown; it should average to grey, not turn into stripes.
    checker = (numpy.indices((256, 256)).sum(axis=0) % 2 * 255)[:, :, None]
    tile = _image(numpy.concatenate([checker, checker, checker, numpy.full((256, 256, 1), 255)], axis=2))
    new = _array(_apply_pac_layer_sampling_transform(tile, _robe_detail_layer(), output_size=QSize(1024, 1024)))
    grey = new[:, :, :3].mean(axis=2)
    assert abs(grey.mean() - 127.5) < 10.0 and grey.std() < 25.0


def test_the_bake_size_is_the_canvas_up_to_the_layers_own_density():
    from cdmw.rendering.material_combiner_images import _layer_bake_size

    tile, layer = _blobs(), _robe_detail_layer()  # 14.17 repeats of a 256 px tile: 3,627 px native
    assert _layer_bake_size(tile, layer, QSize(1024, 1024)) == QSize(1024, 1024)
    assert _layer_bake_size(tile, layer, QSize(8192, 8192)) == QSize(3627, 3627)
    # A canvas no larger than the tile, or a layer that does not repeat, keeps the tile size.
    assert _layer_bake_size(tile, layer, QSize(256, 256)) is None
    plain = SimpleNamespace(layer_channel="g", parameter_name="_detailDiffuseMaskG", material_parameters=())
    assert _layer_bake_size(tile, plain, QSize(1024, 1024)) is None
