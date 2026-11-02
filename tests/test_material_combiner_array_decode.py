from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering import material_combiner_images
from cdmw.rendering.material_combiner_decode import (
    _AFFINE_DECODE_MODES,
    decode_material_arrays,
    decode_material_sample,
)

# Every branch of the scalar decoder, the affine table, an empty mode (which the
# scalar decoder reads as "generic") and an unknown mode (its default branch).
_DECODE_MODES = tuple(sorted(set(_AFFINE_DECODE_MODES) | {
    "", "unknown_mode", "specular_glossiness", "glossiness", "clearcoat", "sheen", "ao",
    "roughness", "metallic", "metallic_roughness", "material_mask", "material_response",
    "skin_detail_mask", "standard_v2_mask", "standard_v2_detail",
    "static_multitextured_material", "orm", "arm", "rma", "mra",
}))


def _random_bytes(count: int, seed: int) -> np.ndarray:
    rng = random.Random(seed)
    values = [rng.randrange(256) for _ in range(count * 4)]
    values[:8] = [0, 0, 0, 0, 255, 255, 255, 255]
    return np.array(values, dtype=np.uint8).reshape(count, 4)


@pytest.mark.parametrize("mode", _DECODE_MODES)
def test_array_decode_matches_the_scalar_decoder_bit_for_bit(mode: str) -> None:
    pixels = _random_bytes(2048, seed=len(mode))
    channels = pixels.astype(np.float64) / 255.0
    arrays = decode_material_arrays(np, *(channels[:, index] for index in range(4)), mode)
    expected = np.array([
        decode_material_sample(*(float(value) / 255.0 for value in row), mode) for row in pixels
    ])
    for slot, values in enumerate(arrays):
        assert values.shape == (len(pixels),)
        assert values.dtype == np.float64
        assert np.array_equal(values, expected[:, slot]), (mode, slot)


def _image(width: int, height: int, seed: int) -> QImage:
    rng = random.Random(seed)
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        for x in range(width):
            image.setPixelColor(x, y, QColor(*(rng.randrange(256) for _ in range(4))))
    return image


def _pixels(url: str) -> bytes:
    if not url:
        return b""
    image = QImage(QUrl(url).toLocalFile()).convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull()
    return bytes(image.constBits())[: image.sizeInBytes()]


@pytest.mark.parametrize(
    "mode",
    ("material_mask", "static_multitextured_material", "material_response", "metallic_roughness", "orm",
     "clearcoat", ""),
)
def test_formula_modes_write_the_same_maps_as_the_scalar_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    # 45 rows cross the 32-row array tile; the mask and layer weight exercise coverage.
    source = _image(23, 45, seed=1)
    mask = _image(23, 45, seed=2)
    item = PreviewMaterialTextureInput(
        material_name="parity",
        shader_family="SkinnedMeshStandard_Ver2",
        source_texture_path="character/armor/parity_ma.dds",
    )

    def generate(output: Path):
        return material_combiner_images._generate_material_maps(
            source, output, "layer", decode_mode=mode, input_item=item,
            surface_category="cloth", layer_mask=mask, layer_mask_channel="g",
            layer_weight=0.7, flip_vertical=False, max_dimension=64,
        )

    arrays = generate(tmp_path / "arrays")
    monkeypatch.setattr(material_combiner_images, "_vectorised_material_maps", lambda **_: None)
    scalar = generate(tmp_path / "scalar")

    assert arrays[0] == scalar[0]
    assert any(arrays[1])
    for array_url, scalar_url in zip(arrays[1], scalar[1]):
        assert _pixels(array_url) == _pixels(scalar_url)
