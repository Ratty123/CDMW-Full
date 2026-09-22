from __future__ import annotations

import copy
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PREVIEW_MESH_IMAGE_FIELD_NAMES
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


@pytest.fixture(params=("worker", "cache"))
def clone_preview(request):
    if request.param == "worker":
        return ArchivePreviewWorker._clone_preview_model_for_worker
    return ArchivePreviewCacheMixin()._clone_archive_preview_model


@pytest.mark.parametrize("strip_images", (False, True))
def test_clone_entry_points_preserve_fields_and_share_only_payloads(clone_preview, strip_images):
    # Distinct opaque markers expose omitted fields even when a dataclass later
    # grows a field with a default. The clone must not interpret payload values.
    mesh_values = {field.name: object() for field in dataclasses.fields(ModelPreviewMesh)}
    mesh_values.update(
        material_name="blade",
        positions=[(1.0, 2.0, 3.0)],
        texture_coordinates=[(0.25, 0.75)],
        normals=[(0.0, 1.0, 0.0)],
        indices=[0, 0, 0],
        positions_binary={"bytes": b"geometry"},
    )
    source_mesh = ModelPreviewMesh(**mesh_values)
    foreign_mesh = object()
    model_values = {field.name: object() for field in dataclasses.fields(ModelPreviewData)}
    model_values.update(path="model.pac", meshes=[source_mesh, foreign_mesh])
    source = ModelPreviewData(**model_values)

    cloned = clone_preview(source, strip_images=strip_images)

    assert isinstance(cloned, ModelPreviewData)
    assert cloned is not source
    assert cloned.meshes is not source.meshes
    assert cloned.meshes[0] is not source_mesh
    assert cloned.meshes[1] is foreign_mesh
    for field in dataclasses.fields(ModelPreviewData):
        if field.name != "meshes":
            assert getattr(cloned, field.name) is model_values[field.name], field.name
    for field in dataclasses.fields(ModelPreviewMesh):
        expected = None if strip_images and field.name in PREVIEW_MESH_IMAGE_FIELD_NAMES else mesh_values[field.name]
        assert getattr(cloned.meshes[0], field.name) is expected, field.name
        assert getattr(source_mesh, field.name) is mesh_values[field.name], field.name

    cloned.meshes[0].material_name = "edited"
    cloned.meshes.pop()
    assert source_mesh.material_name == "blade"
    assert len(source.meshes) == 2


@pytest.mark.parametrize("strip_images", (False, True))
def test_clone_entry_points_preserve_none_and_foreign_models(clone_preview, strip_images):
    foreign_model = object()
    assert clone_preview(None, strip_images=strip_images) is None
    assert clone_preview(foreign_model, strip_images=strip_images) is foreign_model


@pytest.mark.parametrize(
    "first_module",
    ("material_source_driven", "material_texture_routing", "material_sidecar_patching", "material_replacer"),
)
def test_shared_material_aliases_work_in_clean_import_orders(first_module):
    script = f"""
import importlib
importlib.import_module('cdmw.modding.{first_module}')
from cdmw.modding import material_source_driven as source
from cdmw.modding import material_texture_routing as routing
from cdmw.modding import material_sidecar_patching as sidecar
from cdmw.modding import material_replacer as facade
for name in ('_best_source_material_for_target', '_material_tokens',
             '_normalized_source_part_material_role', '_solid_material_factor_png_path'):
    assert getattr(routing, name) is getattr(source, name), name
assert source._material_tokens is sidecar._material_tokens
assert facade._material_tokens('CD_Blade02_material.dds') == {{'blade'}}
assert facade._best_source_material_for_target('Sword', {{'blade': 'Steel'}}) == 'Steel'
assert facade._normalized_source_part_material_role('leather-grip') == 'handle'
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_shared_material_matching_keeps_exact_semantic_and_unmatched_results():
    from cdmw.modding import material_source_driven as source
    from cdmw.modding import material_texture_routing as routing

    mapping = {"blade": "PolishedSteel", "handle": "BrownLeather", "guard": "Brass"}
    for module in (source, routing):
        assert module._best_source_material_for_target(" BLADE ", mapping) == "PolishedSteel"
        assert module._best_source_material_for_target("sword", mapping) == "PolishedSteel"
        assert module._best_source_material_for_target("weapon_handle02", mapping) == "BrownLeather"
        assert module._best_source_material_for_target("unrelated", mapping) == ""
        assert module._best_source_material_for_target("blade", {}) == ""
        assert module._material_tokens("CD_Blade02-material.dds 123 A mesh") == {"blade"}
        assert module._normalized_source_part_material_role("emissive-blade") == "glow"
        assert module._normalized_source_part_material_role("leather_grip") == "handle"
        assert module._normalized_source_part_material_role("unknown finish") == "unknown/finish"


def test_shared_material_factor_image_keeps_pixels_and_cache_identity(tmp_path, monkeypatch):
    from PIL import Image

    from cdmw.modding import material_source_driven as source
    from cdmw.modding import material_texture_routing as routing

    monkeypatch.setattr(source.tempfile, "gettempdir", lambda: str(tmp_path))
    path = routing._solid_material_factor_png_path("Blade Material", "base", (-0.2, 0.5, 2.0))
    assert source._solid_material_factor_png_path("Blade Material", "base", (-0.2, 0.5, 2.0)) == path
    assert path.is_relative_to(tmp_path)
    with Image.open(path) as image:
        assert image.size == (16, 16)
        assert image.getpixel((0, 0)) == (0, 128, 255, 255)


def test_importer_shared_channel_comparison_preserves_changed_scope():
    from cdmw.domain.mesh.operations import _changed_submesh_channels
    from cdmw.modding import mesh_importer
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

    before = SubMesh(
        name="blade", material="steel", texture="steel.dds",
        vertices=[(0.0, 0.0, 0.0)], normals=[(0.0, 1.0, 0.0)],
        tangents=[(1.0, 0.0, 0.0, 1.0)], uvs=[(0.0, 0.0)], faces=[(0, 0, 0)],
        bone_indices=[(1,)], bone_weights=[(1.0,)], vertex_count=1, face_count=1,
    )
    after = copy.deepcopy(before)
    after.vertices = [(1.0, 0.0, 0.0)]
    after.uvs = [(0.5, 0.5)]
    after.bone_indices = [(2,)]
    after.bone_weights = [(0.5,)]
    after.material = "leather"
    after.texture = "leather.dds"
    assert mesh_importer._changed_submesh_channels is _changed_submesh_channels
    assert _changed_submesh_channels(before, copy.deepcopy(before)) == ()
    assert _changed_submesh_channels(None, after) == ("topology",)
    assert _changed_submesh_channels(before, None) == ("topology",)
    expected = ("positions", "uv0", "bone_indices", "bone_weights", "material", "texture")
    assert _changed_submesh_channels(before, after) == expected
    original = ParsedMesh(path="blade.pac", format="pac", submeshes=[before])
    edited = ParsedMesh(path="blade.pac", format="pac", submeshes=[after])
    lods, submeshes, channels = mesh_importer._changed_mesh_scope(original, edited)
    assert lods == (0,)
    assert len(submeshes) == 1
    assert channels == tuple(sorted(expected))
