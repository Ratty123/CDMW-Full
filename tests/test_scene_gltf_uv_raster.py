from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_parser import SubMesh
from cdmw.modding.scene_gltf_uv import GLTF_IDENTITY_UV_TRANSFORM
from cdmw.modding import scene_gltf_uv_raster as raster_module
from cdmw.modding.scene_gltf_uv_raster import (
    GltfRasterSource,
    GltfRasterResult,
    _build_mip_pyramid,
    _dilate_pixels,
    _encode_raster_pixels,
    _file_sha256,
    _slot_mode,
    load_gltf_raster_source,
    publish_gltf_raster_png,
    rasterize_gltf_slot,
    sample_gltf_texture,
)


class _CancelAfter:
    def __init__(self, checks: int) -> None:
        self.checks = checks
        self.calls = 0

    def is_set(self) -> bool:
        self.calls += 1
        return self.calls >= self.checks


def _quad(*, tangent_sign: float = 1.0) -> tuple[SubMesh, list[tuple[float, float]]]:
    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        tangents=[(1.0, 0.0, 0.0)] * 4,
        uvs=[(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)],
        faces=[(0, 1, 2), (0, 2, 3)],
        vertex_count=4,
        face_count=2,
    )
    setattr(submesh, "tangent_signs", [tangent_sign] * 4)
    return submesh, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_raster_preserves_nearest_source_with_glTF_to_internal_v_order(tmp_path: Path) -> None:
    source_path = tmp_path / "base.png"
    source_pixels = np.array(
        [
            [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)],
            [(0, 255, 255, 255), (255, 0, 255, 255), (32, 64, 96, 255), (128, 96, 64, 255)],
        ],
        dtype=np.uint8,
    )
    Image.fromarray(source_pixels, mode="RGBA").save(source_path)
    source = load_gltf_raster_source(source_path, "base")
    submesh, source_uvs = _quad()

    result = rasterize_gltf_slot(
        submesh,
        source_uvs,
        GLTF_IDENTITY_UV_TRANSFORM,
        source,
        wrap_s=33071,
        wrap_t=33071,
        min_filter=9728,
        mag_filter=9728,
    )
    actual = np.asarray(result.image)
    result.image.close()

    assert np.max(np.abs(actual.astype(int) - source_pixels.astype(int))) <= 1
    assert result.filter_mode == "nearest"


@pytest.mark.parametrize(("slot_kind", "expected"), [("base", 188), ("material", 128)])
def test_bilinear_interpolation_uses_slot_color_space(
    tmp_path: Path,
    slot_kind: str,
    expected: int,
) -> None:
    source_path = tmp_path / f"{slot_kind}.png"
    Image.fromarray(np.array([[(0, 0, 0, 255), (255, 255, 255, 255)]], dtype=np.uint8), mode="RGBA").save(source_path)
    source = load_gltf_raster_source(source_path, slot_kind)
    submesh, _source_uvs = _quad()

    result = rasterize_gltf_slot(
        submesh,
        [(0.5, 0.5)] * 4,
        GLTF_IDENTITY_UV_TRANSFORM,
        source,
        wrap_s=33071,
        wrap_t=33071,
        min_filter=9729,
        mag_filter=9729,
    )
    actual = np.asarray(result.image)
    result.image.close()

    assert np.max(np.abs(actual[..., :3].astype(int) - expected)) <= 1


def test_specular_color_interpolates_srgb_rgb_with_linear_alpha(tmp_path: Path) -> None:
    source_path = tmp_path / "specular_color.png"
    Image.fromarray(
        np.array([[(0, 0, 0, 0), (255, 255, 255, 255)]], dtype=np.uint8),
        mode="RGBA",
    ).save(source_path)
    source = load_gltf_raster_source(source_path, "specular_color")
    submesh, _source_uvs = _quad()

    result = rasterize_gltf_slot(
        submesh,
        [(0.5, 0.5)] * 4,
        GLTF_IDENTITY_UV_TRANSFORM,
        source,
        wrap_s=33071,
        wrap_t=33071,
        min_filter=9729,
        mag_filter=9729,
    )
    actual = np.asarray(result.image)[0, 0]
    result.image.close()

    assert actual[:3] == pytest.approx((188, 188, 188), abs=1)
    assert int(actual[3]) == pytest.approx(128, abs=1)


def test_sampler_wrap_modes_and_min_mag_selection(tmp_path: Path) -> None:
    pixels = np.array([[(10, 0, 0, 255), (20, 0, 0, 255), (30, 0, 0, 255), (40, 0, 0, 255)]], dtype=np.float32) / 255.0
    coordinates = np.array([1.125, -0.125])

    repeat = sample_gltf_texture(pixels, coordinates, [0.5, 0.5], wrap_s=10497, wrap_t=33071, filter_mode="nearest")
    clamp = sample_gltf_texture(pixels, coordinates, [0.5, 0.5], wrap_s=33071, wrap_t=33071, filter_mode="nearest")
    mirror = sample_gltf_texture(pixels, coordinates, [0.5, 0.5], wrap_s=33648, wrap_t=33071, filter_mode="nearest")

    assert np.rint(repeat[:, 0] * 255).astype(int).tolist() == [10, 40]
    assert np.rint(clamp[:, 0] * 255).astype(int).tolist() == [40, 10]
    assert np.rint(mirror[:, 0] * 255).astype(int).tolist() == [40, 10]

    source_path = tmp_path / "filter.png"
    Image.fromarray((pixels * 255).astype(np.uint8), mode="RGBA").save(source_path)
    source = load_gltf_raster_source(source_path, "material")
    submesh, source_uvs = _quad()
    minified = rasterize_gltf_slot(
        submesh,
        source_uvs,
        (0.0, 0.0, 2.0, 2.0, 0.0),
        source,
        wrap_s=10497,
        wrap_t=10497,
        min_filter=9728,
        mag_filter=9729,
    )
    magnified = rasterize_gltf_slot(
        submesh,
        source_uvs,
        (0.25, 0.25, 0.5, 0.5, 0.0),
        source,
        wrap_s=10497,
        wrap_t=10497,
        min_filter=9728,
        mag_filter=9729,
    )
    minified.image.close()
    magnified.image.close()
    assert minified.filter_mode == "nearest"
    assert magnified.filter_mode == "linear"


def _reference_level_sample(level: np.ndarray, u: float, v: float, linear: bool) -> np.ndarray:
    height, width = level.shape[:2]
    if not linear:
        return level[int(math.floor(v * height)) % height, int(math.floor(u * width)) % width]
    x, y = u * width - 0.5, v * height - 0.5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    top = level[y0 % height, x0 % width] * (1.0 - fx) + level[y0 % height, (x0 + 1) % width] * fx
    bottom = level[(y0 + 1) % height, x0 % width] * (1.0 - fx) + level[(y0 + 1) % height, (x0 + 1) % width] * fx
    return top * (1.0 - fy) + bottom * fy


@pytest.mark.parametrize(
    ("min_filter", "filter_mode", "linear_texel", "linear_mip"),
    [
        (9984, "nearest_mipmap_nearest", False, False),
        (9985, "linear_mipmap_nearest", True, False),
        (9986, "nearest_mipmap_linear", False, True),
        (9987, "linear_mipmap_linear", True, True),
    ],
)
@pytest.mark.parametrize("semantic_mode", ["linear", "srgb"])
def test_all_gltf_mip_filters_match_reference_within_one_lsb(
    min_filter: int,
    filter_mode: str,
    linear_texel: bool,
    linear_mip: bool,
    semantic_mode: str,
) -> None:
    assert raster_module._filter_mode(min_filter, 9729, minifying=True) == filter_mode
    values = np.arange(16, dtype=np.float32).reshape(4, 4) / 15.0
    if semantic_mode == "srgb":
        values = np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    base = np.repeat(values[..., None], 4, axis=-1)
    mips = _build_mip_pyramid(base, semantic_mode)
    u, v, lod = 0.31, 0.63, 0.5
    actual = sample_gltf_texture(
        base,
        u,
        v,
        wrap_s=10497,
        wrap_t=10497,
        filter_mode=filter_mode,
        mipmaps=mips,
        lod=lod,
    )
    if linear_mip:
        expected = (
            _reference_level_sample(mips[0], u, v, linear_texel) * 0.5
            + _reference_level_sample(mips[1], u, v, linear_texel) * 0.5
        )
    else:
        expected = _reference_level_sample(mips[1], u, v, linear_texel)
    actual_encoded = _encode_raster_pixels(np.asarray(actual).reshape(1, 1, 4), semantic_mode)
    expected_encoded = _encode_raster_pixels(np.asarray(expected).reshape(1, 1, 4), semantic_mode)
    assert np.max(np.abs(actual_encoded.astype(int) - expected_encoded.astype(int))) <= 1


@pytest.mark.parametrize(
    ("slot_kind", "mode", "expected"),
    [
        ("base_color", "srgb", 188),
        ("specular_color", "srgb", 188),
        ("specular_glossiness", "srgb", 188),
        ("sheen_color", "srgb", 188),
        ("clearcoat", "linear", 128),
    ],
)
def test_semantic_downscale_covers_gltf_color_and_data_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slot_kind: str,
    mode: str,
    expected: int,
) -> None:
    monkeypatch.setattr(raster_module, "GLTF_UV_BAKE_MAX_DIMENSION", 1)
    path = tmp_path / f"{slot_kind}.png"
    Image.fromarray(np.array([[(0, 0, 0, 255), (255, 255, 255, 255)]], dtype=np.uint8), mode="RGBA").save(path)
    source = load_gltf_raster_source(path, slot_kind)
    encoded = _encode_raster_pixels(source.pixels, source.mode)
    assert source.downscaled is True
    assert _slot_mode(slot_kind) == mode
    assert int(encoded[0, 0, 0]) == pytest.approx(expected, abs=1)


def test_normal_raster_reorients_with_less_than_one_degree_error(tmp_path: Path) -> None:
    source_path = tmp_path / "normal.png"
    Image.new("RGBA", (8, 8), (255, 128, 128, 255)).save(source_path)
    source = load_gltf_raster_source(source_path, "normal")
    submesh, source_uvs = _quad(tangent_sign=-1.0)

    result = rasterize_gltf_slot(
        submesh,
        source_uvs,
        GLTF_IDENTITY_UV_TRANSFORM,
        source,
        wrap_s=33071,
        wrap_t=33071,
        min_filter=9729,
        mag_filter=9729,
    )
    encoded = np.asarray(result.image)[4, 4, :3].astype(np.float64) / 255.0
    result.image.close()
    decoded = encoded * 2.0 - 1.0
    decoded /= np.linalg.norm(decoded)
    error_degrees = math.degrees(math.acos(float(np.clip(decoded[0], -1.0, 1.0))))
    assert error_degrees <= 1.0


@pytest.mark.parametrize("tangent_sign", [1.0, -1.0])
def test_normal_raster_keeps_custom_source_tbn_when_lookup_rotates(
    tmp_path: Path,
    tangent_sign: float,
) -> None:
    source_path = tmp_path / f"custom_{tangent_sign}.png"
    tangent_normal = np.array((0.6, -0.3, math.sqrt(1.0 - 0.6**2 - 0.3**2)))
    encoded_source = tuple(np.rint((tangent_normal * 0.5 + 0.5) * 255.0).astype(int))
    Image.new("RGBA", (8, 8), (*encoded_source, 255)).save(source_path)
    source = load_gltf_raster_source(source_path, "clearcoat_normal")
    submesh, source_uvs = _quad(tangent_sign=tangent_sign)
    custom_tangents = [(0.0, 1.0, 0.0)] * 4
    submesh.tangents = custom_tangents

    result = rasterize_gltf_slot(
        submesh,
        source_uvs,
        (0.15, -0.2, 0.75, 1.25, math.pi / 2.0),
        source,
        wrap_s=10497,
        wrap_t=10497,
        min_filter=9729,
        mag_filter=9729,
        source_tangents=custom_tangents,
        source_tangent_signs=[tangent_sign] * 4,
    )
    actual = np.asarray(result.image)[4, 4, :3].astype(np.float64) / 255.0 * 2.0 - 1.0
    result.image.close()
    actual /= np.linalg.norm(actual)
    expected = (np.asarray(encoded_source, dtype=np.float64) / 255.0 * 2.0 - 1.0)
    expected /= np.linalg.norm(expected)
    assert math.degrees(math.acos(float(np.clip(np.dot(actual, expected), -1.0, 1.0)))) <= 1.0


def test_eight_pixel_dilation_and_atomic_output_are_deterministic(tmp_path: Path) -> None:
    pixels = np.zeros((20, 20, 4), dtype=np.float32)
    coverage = np.zeros((20, 20), dtype=bool)
    pixels[10, 10] = (1.0, 0.25, 0.5, 1.0)
    coverage[10, 10] = True

    dilated, mask = _dilate_pixels(pixels, coverage, 8)
    assert mask[2, 2] is np.True_
    assert not mask[1, 1]
    assert dilated[2, 2] == pytest.approx((1.0, 0.25, 0.5, 1.0))

    source_path = tmp_path / "mesh.gltf"
    source_path.write_text("{}", encoding="utf-8")
    publication_rows = []
    for _index in range(2):
        image = Image.new("RGBA", (2, 2), (1, 2, 3, 255))
        path, report = publish_gltf_raster_png(
            GltfRasterResult(image=image, covered_pixels=4, dilation_pixels=8, filter_mode="nearest"),
            source_path,
            "base",
            {"source": "same", "version": 1},
        )
        publication_rows.append((path, report))
    assert publication_rows[0][0] == publication_rows[1][0]
    assert publication_rows[0][1]["output_sha256"] == publication_rows[1][1]["output_sha256"]


def test_downscale_limit_is_reportable_and_cancellation_is_preserved(tmp_path: Path) -> None:
    source_path = tmp_path / "wide.png"
    Image.new("RGBA", (4097, 1), (12, 34, 56, 255)).save(source_path)

    source = load_gltf_raster_source(source_path, "base")
    assert (source.source_width, source.source_height) == (4097, 1)
    assert (source.width, source.height) == (4096, 1)
    assert source.downscaled is True

    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled, match="cancelled before texture decode"):
        load_gltf_raster_source(source_path, "base", stop_event=stop_event)


def test_normal_semantic_downscale_renormalizes_clearcoat_normal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(raster_module, "GLTF_UV_BAKE_MAX_DIMENSION", 1)
    path = tmp_path / "clearcoat_normal.png"
    Image.fromarray(
        np.array([[(255, 128, 128, 255), (128, 255, 128, 255)]], dtype=np.uint8),
        mode="RGBA",
    ).save(path)
    source = load_gltf_raster_source(path, "clearcoat_normal")
    encoded = _encode_raster_pixels(source.pixels, source.mode)[0, 0, :3].astype(np.float64)
    decoded = encoded / 255.0 * 2.0 - 1.0
    decoded /= np.linalg.norm(decoded)
    expected = np.array((1.0, 1.0, 0.0)) / math.sqrt(2.0)
    assert _slot_mode("clearcoat_normal") == "normal"
    assert math.degrees(math.acos(float(np.clip(np.dot(decoded, expected), -1.0, 1.0)))) <= 1.0


def test_active_hash_raster_dilation_and_publication_cancellation_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hash_path = tmp_path / "large.bin"
    hash_path.write_bytes(b"x" * (3 * 1024 * 1024))
    with pytest.raises(RunCancelled, match="during file hashing"):
        _file_sha256(hash_path, stop_event=_CancelAfter(2))
    with pytest.raises(ValueError, match="refuses to hash"):
        _file_sha256(hash_path, max_bytes=1024)

    source_path = tmp_path / "raster.png"
    Image.new("RGBA", (128, 128), (50, 100, 150, 255)).save(source_path)
    source = load_gltf_raster_source(source_path, "base")
    submesh, source_uvs = _quad()
    with pytest.raises(RunCancelled, match="during rasterization"):
        rasterize_gltf_slot(
            submesh,
            source_uvs,
            GLTF_IDENTITY_UV_TRANSFORM,
            source,
            wrap_s=33071,
            wrap_t=33071,
            min_filter=9729,
            mag_filter=9729,
            stop_event=_CancelAfter(2),
        )

    pixels = np.zeros((128, 128, 4), dtype=np.float32)
    coverage = np.zeros((128, 128), dtype=bool)
    pixels[64, 64] = 1.0
    coverage[64, 64] = True
    with pytest.raises(RunCancelled, match="during gutter dilation"):
        _dilate_pixels(pixels, coverage, 8, stop_event=_CancelAfter(3))

    mesh_path = tmp_path / "mesh.gltf"
    mesh_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(raster_module.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(RunCancelled, match="during PNG encoding"):
        publish_gltf_raster_png(
            GltfRasterResult(
                image=Image.new("RGBA", (32, 32), (1, 2, 3, 255)),
                covered_pixels=1024,
                dilation_pixels=8,
                filter_mode="linear",
            ),
            mesh_path,
            "base",
            {"version": 2},
            stop_event=_CancelAfter(6),
        )
    assert not list((tmp_path / "cdmw_gltf_uv_bakes").rglob("*.tmp"))


def test_raster_dimension_ceiling_is_checked_before_output_allocation() -> None:
    submesh, source_uvs = _quad()
    unsafe = GltfRasterSource(
        pixels=np.zeros((1, 1, 4), dtype=np.float32),
        width=4097,
        height=1,
        source_width=4097,
        source_height=1,
        source_sha256="0" * 64,
        mode="linear",
        downscaled=False,
    )
    with pytest.raises(ValueError, match="unsafe raster source dimensions"):
        rasterize_gltf_slot(
            submesh,
            source_uvs,
            GLTF_IDENTITY_UV_TRANSFORM,
            unsafe,
            wrap_s=33071,
            wrap_t=33071,
            min_filter=9729,
            mag_filter=9729,
        )
