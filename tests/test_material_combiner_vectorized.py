from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

from cdmw.domain.cancellation import RunCancelled
from cdmw.rendering import material_combiner_images, material_combiner_support_maps


def _pattern(path: Path, width: int, height: int, seed: int) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        for x in range(width):
            image.setPixelColor(
                x,
                y,
                QColor(
                    (x * 19 + y * 7 + seed) % 256,
                    (x * 3 + y * 23 + seed * 2) % 256,
                    (x * 13 + y * 11 + seed * 5) % 256,
                    (x * 29 + y * 17 + seed * 3) % 256,
                ),
            )
    assert image.save(str(path), "PNG")
    return path


def _image_bytes(source_url: str, mode: str) -> bytes:
    path = Path(QUrl(source_url).toLocalFile())
    with Image.open(path) as image:
        return image.convert(mode).tobytes()


@pytest.mark.parametrize("slot", ["roughness", "occlusion"])
def test_vectorized_slot_compositor_matches_scalar_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slot: str,
) -> None:
    pytest.importorskip("numpy")
    layers = (
        (0, "base", str(_pattern(tmp_path / "base.png", 41, 37, 5))),
        (10, "detail", str(_pattern(tmp_path / "detail.png", 41, 37, 17))),
    )

    vector_url, vector_mode = material_combiner_images._combine_material_slot_maps(
        slot,
        layers,
        tmp_path / "vector",
        "surface",
    )
    monkeypatch.setattr(material_combiner_images, "_numpy_module", lambda: None)
    scalar_url, scalar_mode = material_combiner_images._combine_material_slot_maps(
        slot,
        layers,
        tmp_path / "scalar",
        "surface",
    )

    assert vector_mode == scalar_mode
    assert _image_bytes(vector_url, "RGB") == _image_bytes(scalar_url, "RGB")


def test_vectorized_legacy_pbr_packer_matches_scalar_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    occlusion = _pattern(tmp_path / "occlusion.png", 43, 35, 3)
    roughness = _pattern(tmp_path / "roughness.png", 43, 35, 11)
    specular = _pattern(tmp_path / "specular.png", 43, 35, 29)

    vector_url = material_combiner_support_maps._generate_legacy_pbr_response_map(
        tmp_path / "vector",
        "surface",
        occlusion_source=str(occlusion),
        roughness_source=str(roughness),
        specular_source=str(specular),
    )
    monkeypatch.setattr(material_combiner_support_maps, "_numpy_module", lambda: None)
    scalar_url = material_combiner_support_maps._generate_legacy_pbr_response_map(
        tmp_path / "scalar",
        "surface",
        occlusion_source=str(occlusion),
        roughness_source=str(roughness),
        specular_source=str(specular),
    )

    assert _image_bytes(vector_url, "RGBA") == _image_bytes(scalar_url, "RGBA")


def test_vectorized_slot_compositor_remains_cancellable_between_row_chunks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    numpy = pytest.importorskip("numpy")
    layers = ((0, "base", str(_pattern(tmp_path / "base.png", 40, 65, 7))),)
    state = {"armed": False, "polls": 0}

    def arm_vector_path():
        state["armed"] = True
        return numpy

    def cancelled() -> bool:
        if not state["armed"]:
            return False
        state["polls"] += 1
        return state["polls"] >= 2

    monkeypatch.setattr(material_combiner_images, "_numpy_module", arm_vector_path)

    with pytest.raises(RunCancelled):
        material_combiner_images._combine_material_slot_maps(
            "roughness",
            layers,
            tmp_path / "cancelled",
            "surface",
            cancelled=cancelled,
        )

    assert state == {"armed": True, "polls": 2}
    assert not (tmp_path / "cancelled").exists()
