from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

from cdmw.domain.cancellation import RunCancelled
from cdmw.rendering import (
    material_combiner,
    material_combiner_images,
    material_combiner_support_maps,
)
from cdmw.rendering.material_combiner_rules import MaterialPreviewCombinerSettings


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


def _solid(path: Path, width: int, height: int, color: QColor) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(color)
    assert image.save(str(path), "PNG")
    return path


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

    base = QImage(str(_pattern(tmp_path / "albedo_base.png", 37, 73, 3)))
    layers = [
        _texture_input(_pattern(tmp_path / "albedo_detail.png", 37, 73, 11), layer_role="detail", layer_channel="r"),
        _texture_input(_pattern(tmp_path / "albedo_grime.png", 37, 73, 23), layer_role="grime", layer_channel="g"),
    ]
    masks = {"color": _texture_input(_pattern(tmp_path / "albedo_mask.png", 37, 73, 31))}

    def run(folder: str) -> str:
        url, _note = material_combiner_images._generate_synthesized_albedo_map(
            base, layers, masks, tmp_path / folder, "surface",
            flip_vertical=False, max_dimension=512,
            color_blending_mask_input=masks["color"],
            color_blending_tints=((0.9, 0.2, 0.1), (0.1, 0.8, 0.3), (0.2, 0.3, 0.95)),
            preserve_base_alpha=True,
        )
        return url

    arrays = run("arrays")
    monkeypatch.setattr(material_combiner_pixels, "numpy_module", lambda: None)
    monkeypatch.setattr(material_combiner_images, "numpy_module", lambda: None)
    loops = run("loops")
    assert arrays and loops
    assert _image_bytes(arrays, "RGBA") == _image_bytes(loops, "RGBA")


def test_chunked_first_layer_seed_matches_scalar_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    layer = _texture_input(
        _pattern(tmp_path / "seed_layer.png", 45, 67, 47),
        layer_role="detail",
    )

    def run(folder: str) -> str:
        output, _note = material_combiner_images._generate_synthesized_albedo_map(
            QImage(),
            (layer,),
            {},
            tmp_path / folder,
            "surface",
            flip_vertical=False,
            max_dimension=2048,
            preserve_base_alpha=True,
        )
        return output

    tiled = run("tiled_seed")
    monkeypatch.setattr(material_combiner_images, "numpy_module", lambda: None)
    scalar = run("scalar_seed")

    assert tiled and scalar
    assert _image_bytes(tiled, "RGBA") == _image_bytes(scalar, "RGBA")


def test_2048_combiner_requests_largest_source_domain_without_changing_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layer_path = _solid(tmp_path / "detail.png", 64, 32, QColor(110, 90, 70, 255))
    layer = _texture_input(
        layer_path,
        slot_kind="base",
        parameter_name="_detailDiffuseMaskR",
        semantic_type="color",
        semantic_subtype="detail_diffuse",
        layer_role="detail",
        layer_channel="r",
        shader_family="SkinnedMeshStandard_Ver2",
        sidecar_kind="pac_xml",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
    )
    payload = SimpleNamespace(
        alpha_mode="opaque",
        material_texture_inputs=(layer,),
        tangents_usable=False,
        texture_flip_vertical=False,
    )
    observed: list[tuple[int, bool]] = []

    def record_albedo(*_args, **kwargs):
        observed.append(
            (
                int(kwargs["max_dimension"]),
                bool(kwargs["prefer_largest_source_domain"]),
            )
        )
        return "", ""

    monkeypatch.setattr(material_combiner, "_generate_synthesized_albedo_map", record_albedo)

    material_combiner.combine_preview_material(
        payload,
        tmp_path / "legacy",
        0,
        settings=MaterialPreviewCombinerSettings(),
    )
    material_combiner.combine_preview_material(
        payload,
        tmp_path / "rust",
        0,
        settings=MaterialPreviewCombinerSettings(support_map_max_dimension=2048),
    )

    assert observed == [(512, False), (2048, True)]


def test_high_resolution_albedo_uses_2h_selector_domain_and_aspect(tmp_path: Path) -> None:
    base = QImage(4, 4, QImage.Format.Format_RGBA8888)
    base.fill(QColor(150, 150, 150, 255))
    layer = _texture_input(
        _solid(tmp_path / "layer.png", 512, 512, QColor(120, 100, 80, 255)),
        layer_role="detail",
        layer_channel="r",
    )
    selector = _texture_input(
        _solid(tmp_path / "selector.png", 512, 1024, QColor(255, 0, 0, 255)),
    )

    output, _note = material_combiner_images._generate_synthesized_albedo_map(
        base,
        (layer,),
        {"detail": selector},
        tmp_path / "albedo",
        "blade",
        flip_vertical=False,
        max_dimension=2048,
        prefer_largest_source_domain=True,
    )

    synthesized = QImage(QUrl(output).toLocalFile())
    assert (synthesized.width(), synthesized.height()) == (512, 1024)


def test_high_resolution_spec_gloss_albedo_uses_largest_real_domain(tmp_path: Path) -> None:
    base = QImage(
        str(_solid(tmp_path / "base.png", 1024, 512, QColor(80, 60, 40, 255)))
    )
    spec_gloss = QImage(
        str(_solid(tmp_path / "spec_gloss.png", 256, 128, QColor(190, 150, 90, 220)))
    )

    output, _note = material_combiner_images._generate_spec_gloss_preview_albedo_map(
        base,
        spec_gloss,
        tmp_path / "spec_gloss_albedo",
        "blade",
        flip_vertical=False,
        max_dimension=2048,
        prefer_largest_source_domain=True,
    )

    synthesized = QImage(QUrl(output).toLocalFile())
    assert (synthesized.width(), synthesized.height()) == (1024, 512)


def test_vectorized_spec_gloss_albedo_matches_scalar_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    base = QImage(str(_pattern(tmp_path / "base.png", 43, 31, 7)))
    spec_gloss = QImage(str(_pattern(tmp_path / "spec_gloss.png", 43, 31, 19)))

    def run(folder: str) -> str:
        output, _note = material_combiner_images._generate_spec_gloss_preview_albedo_map(
            base,
            spec_gloss,
            tmp_path / folder,
            "blade",
            flip_vertical=False,
            max_dimension=2048,
            prefer_largest_source_domain=True,
            preserve_base_alpha=True,
        )
        return output

    vectorized = run("vectorized_spec_gloss")
    monkeypatch.setattr(material_combiner_images, "numpy_module", lambda: None)
    scalar = run("scalar_spec_gloss")

    assert vectorized and scalar
    assert _image_bytes(vectorized, "RGBA") == _image_bytes(scalar, "RGBA")


@pytest.mark.parametrize(
    ("response_size", "selector_size", "expected_size"),
    (
        ((512, 512), (128, 512), (512, 512)),
        ((256, 256), (512, 1024), (512, 1024)),
        ((256, 256), (256, 256), (256, 256)),
    ),
    ids=("1h-response-domain", "2h-selector-domain", "no-upscale-to-request-cap"),
)
def test_high_resolution_scalar_uses_largest_1h_or_2h_domain(
    tmp_path: Path,
    response_size: tuple[int, int],
    selector_size: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    response = QImage(
        str(
            _solid(
                tmp_path / "response.png",
                *response_size,
                QColor(220, 72, 190, 255),
            )
        )
    )
    selector = QImage(
        str(
            _solid(
                tmp_path / "selector.png",
                *selector_size,
                QColor(255, 0, 0, 255),
            )
        )
    )
    texture_input = _texture_input(
        tmp_path / "response.png",
        slot_kind="material",
        parameter_name="_grimeMaterialTextureR",
        shader_family="SkinnedMeshStandard_Ver2",
        layer_role="grime",
        layer_channel="r",
        binding_authority="authoritative",
        binding_disposition="layer_material_response",
        source_kind="crimson_layer_material_response",
    )

    slots, urls = material_combiner_images._generate_material_maps(
        response,
        tmp_path / "response_maps",
        "blade",
        decode_mode="standard_v2_material",
        input_item=texture_input,
        layer_mask=selector,
        layer_mask_channel="r",
        flip_vertical=False,
        max_dimension=2048,
        prefer_largest_source_domain=True,
    )

    roughness = QImage(QUrl(urls[1]).toLocalFile())
    assert "roughness" in slots
    assert (roughness.width(), roughness.height()) == expected_size


def test_high_resolution_scalar_compositor_uses_largest_layer_domain(
    tmp_path: Path,
) -> None:
    small = _solid(tmp_path / "small.png", 128, 128, QColor(80, 80, 80, 255))
    large = _solid(tmp_path / "large.png", 512, 1024, QColor(160, 160, 160, 255))

    output, _mode = material_combiner_images._combine_material_slot_maps(
        "roughness",
        ((0, "small", str(small)), (10, "large", str(large))),
        tmp_path / "combined",
        "blade",
        max_dimension=2048,
        prefer_largest_source_domain=True,
    )

    combined = QImage(QUrl(output).toLocalFile())
    assert (combined.width(), combined.height()) == (512, 1024)


def test_rgb_selector_palette_preserves_source_value_detail_without_clipping() -> None:
    base = QImage(6, 1, QImage.Format.Format_RGBA8888)
    selector = QImage(6, 1, QImage.Format.Format_RGBA8888)
    for x in range(6):
        value = 48 if x % 2 == 0 else 96
        base.setPixelColor(x, 0, QColor(value, value, value, 255))
    selector_colors = (
        QColor("red"), QColor("red"),
        QColor("green"), QColor("green"),
        QColor("blue"), QColor("blue"),
    )
    for x, color in enumerate(selector_colors):
        selector.setPixelColor(x, 0, color)

    result = material_combiner_images._blend_selector_tints(
        base,
        selector,
        ((0.18, 0.40, 0.25), (0.76, 0.58, 0.40), (0.79, 0.79, 0.79)),
        target_format=QImage.Format.Format_RGB888,
        preserve_base_alpha=False,
    )

    assert result is not None
    for dark_index in (0, 2, 4):
        dark = result.pixelColor(dark_index, 0)
        light = result.pixelColor(dark_index + 1, 0)
        assert light.value() >= dark.value() + 30
        assert max(light.red(), light.green(), light.blue()) < 254
    assert result.pixelColor(0, 0).green() > result.pixelColor(0, 0).red()
    assert result.pixelColor(2, 0).red() > result.pixelColor(2, 0).blue()
    gray = result.pixelColor(4, 0)
    assert max(gray.red(), gray.green(), gray.blue()) - min(gray.red(), gray.green(), gray.blue()) <= 1


def test_0350_sparse_green_dye_preserves_undeclared_red_and_blue_regions() -> None:
    """The 0350 neck cloth authors only ``_dyeingColorMaskG``.

    The shader treats the missing R/B dyes as transparent overlays; it does not
    paint those selector regions from ``_tintColorR/B``.
    """

    base = QImage(3, 1, QImage.Format.Format_RGBA8888)
    selector = QImage(3, 1, QImage.Format.Format_RGBA8888)
    for x, color in enumerate(
        (QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255))
    ):
        base.setPixelColor(x, 0, QColor(72, 96, 120, 255))
        selector.setPixelColor(x, 0, color)

    result = material_combiner_images._blend_selector_tints(
        base,
        selector,
        ((), (0.933, 0.373, 0.373), ()),
        target_format=QImage.Format.Format_RGB888,
        preserve_base_alpha=False,
    )

    assert result is not None
    assert result.pixelColor(0, 0).getRgb()[:3] == (72, 96, 120)
    assert result.pixelColor(2, 0).getRgb()[:3] == (72, 96, 120)
    dyed = result.pixelColor(1, 0)
    assert dyed.red() >= 230
    assert 88 <= dyed.green() <= 102
    assert 88 <= dyed.blue() <= 102


def test_0350_sparse_dye_vector_and_scalar_compositors_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    base = QImage(3, 1, QImage.Format.Format_RGBA8888)
    base.fill(QColor(72, 96, 120, 255))
    selector_path = _solid(
        tmp_path / "0350_selector.png",
        3,
        1,
        QColor(0, 0, 0, 255),
    )
    selector = QImage(str(selector_path))
    for x, color in enumerate(
        (QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255))
    ):
        selector.setPixelColor(x, 0, color)
    assert selector.save(str(selector_path), "PNG")
    selector_input = _texture_input(selector_path)

    def run(folder: str) -> str:
        output, _note = material_combiner_images._generate_synthesized_albedo_map(
            base,
            (),
            {},
            tmp_path / folder,
            "0350_cloth",
            flip_vertical=False,
            max_dimension=512,
            color_blending_mask_input=selector_input,
            color_blending_tints=((), (0.933, 0.373, 0.373, 1.0), ()),
        )
        return output

    vector = run("vector_sparse")
    monkeypatch.setattr(material_combiner_images, "numpy_module", lambda: None)
    scalar = run("scalar_sparse")

    assert vector and scalar
    assert _image_bytes(vector, "RGB") == _image_bytes(scalar, "RGB")


def test_0350_detail_without_authored_detail_dye_preserves_sampled_rgb() -> None:
    pytest.importorskip("numpy")
    base = QImage(1, 1, QImage.Format.Format_RGBA8888)
    base.fill(QColor(40, 60, 80, 255))
    detail = QImage(1, 1, QImage.Format.Format_RGBA8888)
    detail.fill(QColor(186, 34, 18, 255))
    mask = QImage(1, 1, QImage.Format.Format_RGBA8888)
    mask.fill(QColor(255, 0, 0, 255))

    composed = material_combiner_images._compose_albedo_layer(
        base,
        detail,
        mask,
        channel="r",
        weight=1.0,
        tint=(),
        role="detail",
        color_blending_seed_applied=True,
        target_format=QImage.Format.Format_RGB888,
        preserve_base_alpha=False,
    )

    assert composed is not None
    result, tinted_detail = composed
    assert tinted_detail is False
    assert result.pixelColor(0, 0).getRgb()[:3] == (186, 34, 18)


def test_synthesized_normal_arrays_match_the_per_pixel_loops(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    from cdmw.rendering import material_combiner_pixels

    normals = [
        _texture_input(_pattern(tmp_path / "normal_base.png", 33, 67, 7)),
        _texture_input(_pattern(tmp_path / "normal_detail.png", 33, 67, 19), layer_role="detail", layer_channel="r"),
    ]
    masks = {"color": _texture_input(_pattern(tmp_path / "normal_mask.png", 33, 67, 13))}

    def run(folder: str):
        url, strength, roles, _unreadable = material_combiner_support_maps._generate_synthesized_normal_map(
            normals, masks, tmp_path / folder, "surface", flip_vertical=False, max_dimension=512,
        )
        return url, strength, roles

    array_url, array_strength, array_roles = run("arrays")
    monkeypatch.setattr(material_combiner_pixels, "numpy_module", lambda: None)
    monkeypatch.setattr(material_combiner_support_maps, "_numpy_module", lambda: None)
    loop_url, loop_strength, loop_roles = run("loops")
    assert array_roles == loop_roles
    if not array_url and not loop_url:
        pytest.skip("this pattern carries no layer normal the pass keeps")
    assert _image_bytes(array_url, "RGB") == _image_bytes(loop_url, "RGB")
    assert array_strength == pytest.approx(loop_strength, abs=1e-9)


def test_chunked_normal_height_and_derived_normal_match_scalar_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    source = QImage(str(_pattern(tmp_path / "support.png", 47, 69, 37)))

    vector_normal, vector_strength = material_combiner_support_maps._generate_normal_map(
        source,
        tmp_path / "vector_normal",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )
    vector_height, vector_contrast = material_combiner_support_maps._generate_height_map(
        source,
        tmp_path / "vector_height",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )
    vector_derived, vector_derived_contrast = material_combiner_support_maps._derive_normal_from_height(
        source,
        tmp_path / "vector_derived",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )

    monkeypatch.setattr(material_combiner_support_maps, "_numpy_module", lambda: None)
    scalar_normal, scalar_strength = material_combiner_support_maps._generate_normal_map(
        source,
        tmp_path / "scalar_normal",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )
    scalar_height, scalar_contrast = material_combiner_support_maps._generate_height_map(
        source,
        tmp_path / "scalar_height",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )
    scalar_derived, scalar_derived_contrast = material_combiner_support_maps._derive_normal_from_height(
        source,
        tmp_path / "scalar_derived",
        "surface",
        flip_vertical=False,
        max_dimension=2048,
    )

    assert _image_bytes(vector_normal, "RGBA") == _image_bytes(scalar_normal, "RGBA")
    assert vector_strength == pytest.approx(scalar_strength, abs=1e-9)
    assert _image_bytes(vector_height, "RGB") == _image_bytes(scalar_height, "RGB")
    assert vector_contrast == scalar_contrast
    assert _image_bytes(vector_derived, "RGBA") == _image_bytes(scalar_derived, "RGBA")
    assert vector_derived_contrast == scalar_derived_contrast


def test_high_resolution_material_decode_uses_bounded_row_tiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    source = QImage(str(_pattern(tmp_path / "wide_material.png", 2048, 65, 41)))
    original = material_combiner_images._numpy_rgba_row_chunk
    observed_rows: list[int] = []

    def record_rows(*args, **kwargs):
        row_count = int(args[5])
        observed_rows.append(row_count)
        return original(*args, **kwargs)

    monkeypatch.setattr(material_combiner_images, "_numpy_rgba_row_chunk", record_rows)
    slots, urls = material_combiner_images._generate_material_maps(
        source,
        tmp_path / "wide_output",
        "surface",
        decode_mode="standard_v2_material",
        flip_vertical=False,
        max_dimension=2048,
    )

    assert slots
    assert any(urls)
    assert observed_rows == [32, 32, 1]
    assert max(observed_rows) <= 32


def test_requested_material_outputs_match_full_decode_without_discarded_maps(
    tmp_path: Path,
) -> None:
    source = QImage(str(_pattern(tmp_path / "requested_material.png", 63, 47, 59)))

    full_slots, full_urls = material_combiner_images._generate_material_maps(
        source,
        tmp_path / "full_material",
        "surface",
        decode_mode="standard_v2_material",
        flip_vertical=False,
        max_dimension=2048,
    )
    requested_slots, requested_urls = material_combiner_images._generate_material_maps(
        source,
        tmp_path / "requested_material",
        "surface",
        decode_mode="standard_v2_material",
        flip_vertical=False,
        max_dimension=2048,
        requested_slots=frozenset({"occlusion", "specular"}),
    )

    assert set(full_slots) == {"occlusion", "roughness", "metalness", "specular"}
    assert set(requested_slots) == {"occlusion", "specular"}
    assert requested_urls[1:3] == ("", "")
    assert _image_bytes(requested_urls[0], "RGBA") == _image_bytes(
        full_urls[0], "RGBA"
    )
    assert _image_bytes(requested_urls[3], "RGBA") == _image_bytes(
        full_urls[3], "RGBA"
    )


def test_chunked_material_decode_remains_cancellable_between_tiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    numpy = pytest.importorskip("numpy")
    source = QImage(str(_pattern(tmp_path / "cancel_material.png", 64, 65, 43)))
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
        material_combiner_images._generate_material_maps(
            source,
            tmp_path / "cancelled_material",
            "surface",
            decode_mode="standard_v2_material",
            flip_vertical=False,
            max_dimension=2048,
            cancelled=cancelled,
        )

    assert state == {"armed": True, "polls": 2}
    assert not (tmp_path / "cancelled_material").exists()


def _byte4_value(*channels: int) -> str:
    packed = sum((int(value) & 0xFF) << (index * 8) for index, value in enumerate(channels))
    return str(packed)


def _layer_transform_parameters(
    *,
    property_suffix: str,
    transform: tuple[int, int, int, int],
    rotations: tuple[int, int, int, int] = (127, 127, 127, 127),
):
    from cdmw.models import PreviewMaterialParameterInput

    return (
        PreviewMaterialParameterInput(
            parameter_kind="byte4",
            parameter_name=f"_dyeingTransformProperty{property_suffix}",
            value=_byte4_value(*transform),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="byte4",
            parameter_name="_dyeingPropertyBlend",
            value=_byte4_value(*rotations),
        ),
    )


def test_pac_layer_sampling_transform_decodes_shader_formula_and_identity(
    tmp_path: Path,
) -> None:
    source = QImage(str(_pattern(tmp_path / "layer_transform.png", 19, 13, 71)))
    transformed_item = _texture_input(
        tmp_path / "layer_transform.png",
        layer_role="detail",
        layer_channel="g",
        material_parameters=_layer_transform_parameters(
            property_suffix="1",
            transform=(4, 195, 218, 22),
            rotations=(0, 64, 0, 0),
        ),
    )

    decoded = material_combiner_images._pac_layer_sampling_transform(transformed_item)
    assert decoded is not None
    assert decoded[:4] == pytest.approx((4 / 255, 195 / 255, 218 / 255, 22 / 255))
    assert decoded[4] == pytest.approx((64 / 255 * 2.0 * 3.141592653589793) - 3.141592653589793)

    identity_item = _texture_input(
        tmp_path / "layer_transform.png",
        layer_role="detail",
        layer_channel="r",
        material_parameters=_layer_transform_parameters(
            property_suffix="0",
            transform=(255, 255, 0, 0),
        ),
    )
    unchanged = material_combiner_images._apply_pac_layer_sampling_transform(
        source,
        identity_item,
    )
    assert unchanged.cacheKey() == source.cacheKey()
    assert unchanged.constBits().tobytes() == source.constBits().tobytes()


def test_pac_layer_sampling_transform_vector_and_scalar_repeat_sampling_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pytest.importorskip("numpy")
    source = QImage(str(_pattern(tmp_path / "repeat_layer.png", 23, 17, 83)))
    item = _texture_input(
        tmp_path / "repeat_layer.png",
        layer_role="detail",
        layer_channel="b",
        material_parameters=_layer_transform_parameters(
            property_suffix="3",
            transform=(33, 33, 165, 55),
            rotations=(0, 0, 52, 0),
        ),
    )

    vector = material_combiner_images._apply_pac_layer_sampling_transform(source, item)
    monkeypatch.setattr(material_combiner_images, "_numpy_module", lambda: None)
    scalar = material_combiner_images._apply_pac_layer_sampling_transform(source, item)

    assert vector.constBits().tobytes() == scalar.constBits().tobytes()
    assert vector.constBits().tobytes() != source.convertToFormat(
        QImage.Format.Format_RGBA8888
    ).constBits().tobytes()


def test_shared_pac_layer_transform_is_used_for_albedo_normal_and_material_maps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = _pattern(tmp_path / "shared_layer.png", 17, 13, 97)
    mask_path = _solid(tmp_path / "shared_mask.png", 17, 13, QColor(255, 0, 0, 255))
    parameters = _layer_transform_parameters(
        property_suffix="0",
        transform=(128, 128, 0, 0),
    )
    layer = _texture_input(
        source_path,
        layer_role="detail",
        layer_channel="r",
        material_parameters=parameters,
    )
    mask = _texture_input(mask_path)
    calls: list[tuple[str, str]] = []

    original = material_combiner_images._apply_pac_layer_sampling_transform

    def record_transform(image, item, **kwargs):
        calls.append((str(getattr(item, "layer_role", "")), str(getattr(item, "layer_channel", ""))))
        return original(image, item, **kwargs)

    monkeypatch.setattr(material_combiner_images, "_apply_pac_layer_sampling_transform", record_transform)
    monkeypatch.setattr(material_combiner_support_maps, "_apply_pac_layer_sampling_transform", record_transform)

    material_combiner_images._generate_synthesized_albedo_map(
        QImage(str(_solid(tmp_path / "base.png", 17, 13, QColor(60, 70, 80, 255)))),
        (layer,),
        {"detail": mask},
        tmp_path / "albedo_transform",
        "surface",
        flip_vertical=False,
        max_dimension=64,
    )
    material_combiner_support_maps._generate_synthesized_normal_map(
        (
            _texture_input(_solid(tmp_path / "base_normal.png", 17, 13, QColor(128, 127, 255, 255))),
            layer,
        ),
        {"detail": mask},
        tmp_path / "normal_transform",
        "surface",
        flip_vertical=False,
        max_dimension=64,
    )
    material_combiner_images._generate_material_maps(
        QImage(str(source_path)),
        tmp_path / "material_transform",
        "surface",
        decode_mode="standard_v2_material",
        input_item=layer,
        layer_mask=QImage(str(mask_path)),
        layer_mask_channel="r",
        flip_vertical=False,
        max_dimension=64,
    )

    assert calls == [("detail", "r"), ("detail", "r"), ("detail", "r")]
