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


def test_external_material_factors_keep_vector_and_scalar_bytes_equal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput

    image = QImage(str(_pattern(tmp_path / "material.png", 39, 31, 13)))
    texture_input = PreviewMaterialTextureInput(
        slot_kind="material",
        parameter_name="_metallicRoughnessTexture",
        semantic_type="material",
        semantic_subtype="metallic_roughness",
        packed_channels=("roughness", "metallic"),
        material_parameters=(
            PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_roughnessFactor", numeric_value=0.55),
            PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_metallicFactor", numeric_value=0.35),
            PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_gltfTextureStrength_occlusion", numeric_value=0.4),
        ),
    )

    def run(folder: str):
        slots, urls = material_combiner_images._generate_material_maps(
            image,
            tmp_path / folder,
            "surface",
            decode_mode="metallic_roughness",
            input_item=texture_input,
            flip_vertical=False,
            max_dimension=128,
        )
        return slots, tuple(_image_bytes(url, "RGBA") if url else b"" for url in urls)

    vector = run("vector_factors")
    monkeypatch.setattr(material_combiner_images, "_numpy_module", lambda: None)
    scalar = run("scalar_factors")
    assert vector == scalar


def _texture_input(path: Path, **fields):
    from cdmw.models import PreviewMaterialTextureInput

    values = {"texture_name": path.stem, "preview_texture_path": str(path)}
    values.update(fields)
    known = {name for name in PreviewMaterialTextureInput.__dataclass_fields__}
    return PreviewMaterialTextureInput(**{name: value for name, value in values.items() if name in known})


def test_synthesized_albedo_arrays_match_the_per_pixel_loops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The whole-image albedo pass replaced six million pixelColor calls per import; it
    has to land on the same bytes, including the single-precision channel conversion Qt
    does in QColor.redF()."""

    pytest.importorskip("numpy")
    from cdmw.rendering import material_combiner_pixels

    base = QImage(str(_pattern(tmp_path / "albedo_base.png", 37, 29, 3)))
    layers = [
        _texture_input(_pattern(tmp_path / "albedo_detail.png", 37, 29, 11), layer_role="detail", layer_channel="r"),
        _texture_input(_pattern(tmp_path / "albedo_grime.png", 37, 29, 23), layer_role="grime", layer_channel="g"),
    ]
    masks = {"color": _texture_input(_pattern(tmp_path / "albedo_mask.png", 37, 29, 31))}

    def run(folder: str) -> str:
        url, _note = material_combiner_images._generate_synthesized_albedo_map(
            base, layers, masks, tmp_path / folder, "surface",
            flip_vertical=False, max_dimension=512,
            color_blending_mask_input=masks["color"],
            color_blending_tints=((0.9, 0.2, 0.1), (0.1, 0.8, 0.3), (0.2, 0.3, 0.95)),
        )
        return url

    arrays = run("arrays")
    monkeypatch.setattr(material_combiner_pixels, "numpy_module", lambda: None)
    loops = run("loops")
    assert arrays and loops
    assert _image_bytes(arrays, "RGB") == _image_bytes(loops, "RGB")


def test_synthesized_normal_arrays_match_the_per_pixel_loops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    from cdmw.rendering import material_combiner_pixels

    normals = [
        _texture_input(_pattern(tmp_path / "normal_base.png", 33, 27, 7)),
        _texture_input(_pattern(tmp_path / "normal_detail.png", 33, 27, 19), layer_role="detail", layer_channel="r"),
    ]
    masks = {"color": _texture_input(_pattern(tmp_path / "normal_mask.png", 33, 27, 13))}

    def run(folder: str):
        url, strength, roles, _unreadable = material_combiner_support_maps._generate_synthesized_normal_map(
            normals, masks, tmp_path / folder, "surface", flip_vertical=False, max_dimension=512,
        )
        return url, strength, roles

    array_url, array_strength, array_roles = run("arrays")
    monkeypatch.setattr(material_combiner_pixels, "numpy_module", lambda: None)
    loop_url, loop_strength, loop_roles = run("loops")
    assert array_roles == loop_roles
    if not array_url and not loop_url:
        pytest.skip("this pattern carries no layer normal the pass keeps")
    assert _image_bytes(array_url, "RGB") == _image_bytes(loop_url, "RGB")
    assert array_strength == pytest.approx(loop_strength, abs=1e-9)
