"""Whole-image pixel maths for the material combiner.

The synthesis passes used to walk every pixel in Python: `pixelColor` / `setPixelColor`
per texel, with a `_clamp` call per channel. On one imported sword that was 6.2 million
`pixelColor` calls and about 24 of the 29 seconds a model import spent building its
viewport package. The maths is per-pixel and independent, so it belongs in whole-array
form; these helpers move an image in and out of NumPy and leave the passes to express
themselves as array arithmetic.

Every helper returns None when NumPy is missing or the image will not convert, and each
caller keeps its original loop for that case, so the combiner still works without NumPy.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QImage

__all__ = [
    "image_to_rgba_array",
    "mask_alpha_array",
    "numpy_module",
    "rgba_array_to_image",
    "to_byte_array",
]

_NUMPY: object | None = None
_NUMPY_TRIED = False



def numpy_module():
    """NumPy, or None when this build has none."""

    global _NUMPY, _NUMPY_TRIED
    if not _NUMPY_TRIED:
        _NUMPY_TRIED = True
        try:
            import numpy  # noqa: PLC0415 - optional, resolved once

            _NUMPY = numpy
        except Exception:  # noqa: BLE001 - no NumPy means the loops stay
            _NUMPY = None
    return _NUMPY


def image_to_rgba_array(image: QImage, *, dtype=None):
    """`(height, width, 4)` float in 0..1, RGBA, or None.

    The rows of a QImage can carry padding, so the buffer is read at its own stride and
    then cut back to the visible width.
    """

    numpy = numpy_module()
    if numpy is None or image is None or image.isNull():
        return None
    rgba = image if image.format() == QImage.Format.Format_RGBA8888 else image.convertToFormat(QImage.Format.Format_RGBA8888)
    if rgba.isNull():
        return None
    width, height, stride = int(rgba.width()), int(rgba.height()), int(rgba.bytesPerLine())
    if width <= 0 or height <= 0 or stride < width * 4:
        return None
    try:
        buffer = numpy.frombuffer(memoryview(rgba.constBits())[: stride * height], dtype=numpy.uint8)
    except (TypeError, ValueError):
        return None
    if buffer.size < stride * height:
        return None
    rows = buffer.reshape(height, stride)[:, : width * 4].reshape(height, width, 4)
    # QColor.redF() and its siblings divide by 255 in single precision and hand the
    # result to Python as a double; dividing in float64 here lands a few dozen texels
    # per texture the other side of a rounding boundary, so the same two steps are made
    # here: divide as float32, then widen for the arithmetic the passes do in doubles.
    kind = numpy.float64 if dtype is None else dtype
    return (rows.astype(numpy.float32) / numpy.float32(255.0)).astype(kind)


def to_byte_array(values):
    """The array twin of `_byte`: clamp to 0..1, scale, round half to even, to uint8."""

    numpy = numpy_module()
    return numpy.rint(numpy.clip(values, 0.0, 1.0) * 255.0).astype(numpy.uint8)


def rgba_array_to_image(red, green, blue, alpha, *, target_format: QImage.Format) -> Optional[QImage]:
    """A QImage in `target_format` from four 0..1 channel arrays, or None."""

    numpy = numpy_module()
    if numpy is None:
        return None
    height, width = red.shape[:2]
    packed = numpy.empty((height, width, 4), dtype=numpy.uint8)
    packed[:, :, 0] = to_byte_array(red)
    packed[:, :, 1] = to_byte_array(green)
    packed[:, :, 2] = to_byte_array(blue)
    packed[:, :, 3] = alpha if alpha.dtype == numpy.uint8 else to_byte_array(alpha)
    data = packed.tobytes()
    image = QImage(data, int(width), int(height), int(width) * 4, QImage.Format.Format_RGBA8888).copy()
    if image.isNull():
        return None
    return image if image.format() == target_format else image.convertToFormat(target_format)


def mask_alpha_array(mask_image: QImage, *, channel: str, width: int, height: int):
    """The mask's chosen channel as `(height, width)` float32 in 0..1; ones when there is
    no mask (what `_mask_alpha` returns for a null image), None when it will not convert."""

    numpy = numpy_module()
    if numpy is None:
        return None
    if mask_image is None or mask_image.isNull():
        return numpy.ones((height, width), dtype=numpy.float64)
    array = image_to_rgba_array(mask_image)
    if array is None or array.shape[0] != height or array.shape[1] != width:
        return None
    from cdmw.rendering.material_combiner_rules import _LAYER_CHANNEL_INDEX

    index = _LAYER_CHANNEL_INDEX.get(channel, 0)  # the same lookup `_mask_alpha` makes
    return numpy.clip(array[:, :, index if index < 4 else 0], 0.0, 1.0)
