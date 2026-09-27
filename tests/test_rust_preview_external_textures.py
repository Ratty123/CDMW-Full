"""External image channels must survive the final Rust renderer package."""

import copy
import json
from dataclasses import replace

import pytest
from PIL import Image

from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package,
    validate_rust_preview_package,
)
from tests.test_fbx_import_materials import _import_source
from tests.test_rust_preview_production_cutover import _triangle


@pytest.fixture
def image_encoder(monkeypatch):
    """Exercise image selection/publication without requiring the native encoder."""
    jobs_seen = []

    def encode(jobs, stop_event, synthesis):
        jobs_seen.extend(jobs)
        for source, target, _role in jobs:
            with Image.open(source) as image:
                image.convert("RGBA").save(target, format="DDS")
        return ()

    monkeypatch.setattr(
        "cdmw.services.mesh_rust_authoring._encode_rust_preview_dds_batch", encode
    )
    return jobs_seen


def _input(tmp_path, role, value=73, **kwargs):
    path = tmp_path / f"{role}.png"
    Image.new("RGB", (4, 4), (value, value, value)).save(path)
    return PreviewMaterialTextureInput(
        slot_kind=role, semantic_type=role, packed_channels=(role,),
        source_texture_path=str(path), preview_texture_path=str(path),
        confidence="scene", **kwargs,
    )


def _package(mesh, tmp_path, **kwargs):
    package = build_rust_preview_package(mesh, output_root=tmp_path, **kwargs)
    assert validate_rust_preview_package(package.package_dir) == ()
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    return package, {row["role"]: row for row in manifest["textures"]}


@pytest.mark.parametrize("scene_format", ("obj", "dae", "gltf", "glb"))
def test_separate_scalar_images_reach_renderer_for_external_formats(
    tmp_path, image_encoder, scene_format,
):
    mesh = _triangle()
    mesh.format = scene_format
    mesh.path = f"fixture://model.{scene_format}"
    inputs = tuple(_input(tmp_path, role) for role in (
        "roughness", "metallic", "occlusion", "specular",
    ))
    mesh.submeshes[0].preview_material_texture_inputs = inputs
    mesh.submeshes.append(copy.deepcopy(mesh.submeshes[0]))
    package, textures = _package(mesh, tmp_path / "packages")

    expected = {"roughness", "metalness", "occlusion", "specular"}
    assert textures.keys() == expected
    assert len(image_encoder) == 4, "shared images should be encoded once per role"
    for row in textures.values():
        assert row["material_indices_by_lod"] == [[0, 1]]
        with Image.open(package.package_dir / row["file"]["path"]) as image:
            assert image.convert("RGB").getpixel((0, 0)) == (73, 73, 73)
    assert mesh.submeshes[0].preview_material_texture_inputs == inputs


@pytest.mark.parametrize("quality", ("direct", "full"))
def test_fbx_zip_recovered_maps_survive_preview_publication(
    tmp_path, monkeypatch, image_encoder, quality,
):
    source = _import_source(tmp_path, monkeypatch)
    _, textures = _package(
        source.scene.mesh, tmp_path / "packages", material_quality=quality,
    )
    assert textures.keys() == {"base_color", "normal", "roughness", "metalness"}
    assert all(row["material_indices_by_lod"] == [[0]] for row in textures.values())


def test_packed_surface_is_not_published_as_red_channel_scalars(tmp_path, image_encoder):
    mesh = _triangle()
    mesh.format = "gltf"
    packed = _input(tmp_path, "material")
    mesh.submeshes[0].preview_material_texture_path = packed.preview_texture_path
    mesh.submeshes[0].preview_material_texture_inputs = (
        replace(packed, semantic_type="roughness", packed_channels=("roughness", "metallic")),
        _input(tmp_path, "metallic"),
    )
    _, textures = _package(mesh, tmp_path / "packages")
    assert textures.keys() == {"material"}
    assert [job[2] for job in image_encoder] == ["material"]


def test_existing_scalar_dds_precedes_preview_image(tmp_path, image_encoder):
    mesh = _triangle()
    mesh.format = "gltf"
    item = _input(tmp_path, "roughness")
    dds = tmp_path / "roughness.dds"
    Image.new("RGB", (4, 4), (191, 191, 191)).save(dds, format="DDS")
    original = dds.read_bytes()
    mesh.submeshes[0].preview_material_texture_inputs = (
        replace(item, source_dds_path=str(dds)),
    )
    package, textures = _package(mesh, tmp_path / "packages")
    assert not image_encoder
    assert textures.keys() == {"roughness"}
    assert (package.package_dir / textures["roughness"]["file"]["path"]).read_bytes() == original


def test_layer_scalar_images_do_not_become_global_surface_maps(tmp_path, image_encoder):
    mesh = _triangle()
    mesh.format = "gltf"
    mesh.submeshes[0].preview_material_texture_inputs = (
        _input(tmp_path, "roughness", binding_disposition="layer_only"),
    )
    _, textures = _package(mesh, tmp_path / "packages")
    assert not textures
    assert not image_encoder


def test_direct_and_full_viewports_reuse_exact_native_textures(tmp_path, monkeypatch):
    from collections import OrderedDict
    from cdmw.core import texture_encode_cache, texture_native

    monkeypatch.setattr(texture_encode_cache, "_CACHE", OrderedDict())
    source = tmp_path / "colour.png"
    Image.new("RGBA", (16, 16), (71, 93, 117, 128)).save(source)
    mesh = _triangle()
    mesh.format = "gltf"
    mesh.submeshes[0].preview_texture_path = str(source)
    original_run = texture_native.run_process_with_cancellation
    calls = []

    def run(command, **kwargs):
        if command[1] == "batch-encode-json":
            calls.append(command)
        return original_run(command, **kwargs)

    monkeypatch.setattr(texture_native, "run_process_with_cancellation", run)
    packages = []
    for quality in ("direct", "full"):
        package, textures = _package(mesh, tmp_path / quality, material_quality=quality)
        packages.append((package, textures))
    assert len(calls) == 1, "the full viewport must reuse the direct tier's unchanged DDS"
    first, second = packages
    assert first[1].keys() == second[1].keys() == {"base_color"}
    for role in first[1]:
        before = (first[0].package_dir / first[1][role]["file"]["path"]).read_bytes()
        after = (second[0].package_dir / second[1][role]["file"]["path"]).read_bytes()
        assert before == after
    assert not getattr(mesh.submeshes[0], "preview_texture_dds_path", "")
    Image.new("RGBA", (16, 16), (117, 93, 71, 64)).save(source)
    changed, textures = _package(mesh, tmp_path / "changed", material_quality="direct")
    assert len(calls) == 2
    assert (changed.package_dir / textures["base_color"]["file"]["path"]).read_bytes() != before


def test_imported_preview_rebuilds_the_previous_material_cache(
    tmp_path, monkeypatch, image_encoder,
):
    from cdmw.services import mesh_rust_preview_cache as cache

    source = _import_source(tmp_path, monkeypatch)
    options = dict(
        cache_root=tmp_path / "cache", archive_identity="same-import",
        cache_mode="balanced", max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    with monkeypatch.context() as previous:
        previous.setitem(cache._PYTHON_MODEL_PREVIEW_SOURCE_MANIFEST, "material_semantics_version", 1)
        old = cache.build_or_lookup_rust_preview_package_from_model(source.preview_model, **options)
    current = cache.build_or_lookup_rust_preview_package_from_model(source.preview_model, **options)
    assert current.package_dir != old.package_dir
    manifest = json.loads(current.manifest_path.read_text(encoding="utf-8"))
    assert {row["role"] for row in manifest["textures"]} == {
        "base_color", "normal", "roughness", "metalness",
    }
