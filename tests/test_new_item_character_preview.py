"""Character references survive the real New Item shader/package handoff."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from cdmw.domain.mesh.shader_controls import NEW_ITEM_FAMILIES, ShaderControls
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package, validate_rust_preview_package
from cdmw.ui.new_item.controller_preview_mixin import _placement_progressive_source
from cdmw.ui.new_item.item_preview import PlacementScene, build_item_preview_package
from cdmw.ui.new_item.model_import import ModelPlacement


def _mesh(*names):
    return ParsedMesh(
        path=f"{names[0]}.pac", format="pac", bbox_min=(0.0, 0.0, 0.0), bbox_max=(1.0, 1.0, 0.0),
        submeshes=[SubMesh(
            name=name, material=name,
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)], normals=[(0.0, 0.0, 1.0)] * 3,
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        ) for name in names],
    )


def _read_package(path):
    path = Path(getattr(path, "package_dir", path))
    assert validate_rust_preview_package(path) == ()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    document = json.loads((path / manifest["document"]["path"]).read_text(encoding="utf-8"))
    return manifest, document


@pytest.mark.parametrize("family", [None, *NEW_ITEM_FAMILIES], ids=lambda family: family.shader if family else "source")
@pytest.mark.parametrize("show_character", [True, False])
def test_shader_preview_keeps_reference_geometry_and_placement(tmp_path, family, show_character):
    from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
    from cdmw.services.mesh_rust_authoring import _mesh_document_payload
    from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture

    native, *_ = _write_schema8_preview_core_fixture(tmp_path)
    template = decode_dotnet_native_preview_package(native)
    model = _mesh("lambert1", "gem")
    body = _mesh("character_hand", "character_body")
    if family is not None and family.mask:
        mask = tmp_path / "mask.dds"
        Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(mask)
        model.submeshes[0].preview_material_texture_inputs = (SimpleNamespace(
            parameter_name=family.mask, source_texture_path=str(mask), source_dds_path=str(mask),
            preview_texture_path=str(mask), shader_family=family.shader, confidence="scene",
            owner_slot_index=-1,
        ),)
    shader = family.shader if family is not None else ""
    values = (("_extinctionCoefficient", (0.0,)),) if shader == "SkinnedMeshTranslucent" else ()
    choices = (("lambert1", ShaderControls(shader, values)),) if family is not None else ()
    placement = ModelPlacement(offset=(2.0, 3.0, 4.0), rotation=(15.0, 30.0, 45.0), scale=(1.5, 2.0, 0.5))
    imported = SimpleNamespace(
        baked_scene_mesh=lambda: model, baked_preview_mesh=lambda: model,
        baked_bounds=lambda: (model.bbox_min, model.bbox_max), baked_origin=lambda: (0.5, 0.5, 0.0),
        acquire_usage=lambda: None,
    )
    original_model = _mesh_document_payload(model)
    original_body = _mesh_document_payload(body)
    token = ("placement", shader, show_character)
    source = _placement_progressive_source(
        imported, lambda _stop: template, lambda _stop: template, placement,
        lambda _stop: body if show_character else None, token, choices,
    )
    stop = threading.Event()
    geometry = build_item_preview_package(
        source.geometry, token=token, output_root=tmp_path, stop_event=stop, include_material_resources=False,
    )
    fast = []
    materials = build_item_preview_package(
        source.materials, token=token, output_root=tmp_path, stop_event=stop, fast_package_ready=fast.append,
    )
    assert len(fast) == 1, "The native template must exercise both texture tiers."
    expected = [part.name for part in model.submeshes]
    references = [part.name for part in template.submeshes] + (['character_hand', 'character_body'] if show_character else [])
    expected += [f"original_reference_{index}_{name}" for index, name in enumerate(references)]
    geometry_scene = _read_package(geometry)[0]["state"]["preview_scene"]
    for package in (geometry, *fast, materials):
        manifest, document = _read_package(package)
        scene = manifest["state"]["preview_scene"]
        parts = document["lods"][0]["submeshes"]
        assert [part["name"] for part in parts] == expected
        assert scene["roles"]["editable"]["submesh_indices"] == [0, 1]
        assert scene["roles"]["reference"]["submesh_indices"] == list(range(2, len(expected)))
        assert scene["roles"] == geometry_scene["roles"]
        assert scene["placement"] == geometry_scene["placement"]
        assert scene["placement_pivot"] == geometry_scene["placement_pivot"]
        assert scene["comparison_mode"] == "overlay"
        assert scene["interaction_mode"] == "placement"
        assert [part["positions"] for part in parts[:2]] == [
            part["positions"] for part in original_model["lods"][0]["submeshes"]
        ]
    assert _mesh_document_payload(model) == original_model
    assert _mesh_document_payload(body) == original_body


def test_placement_rebuilds_legacy_cache_without_losing_character(tmp_path):
    from cdmw.services.mesh_rust_preview_cache import build_or_lookup_rust_preview_package_with_builder
    from cdmw.services.shader_controls_preview import shader_preview_mesh

    token = ("placement", "cached-glass-character")
    model = shader_preview_mesh(_mesh("lambert1"), (("lambert1", ShaderControls("SkinnedMeshTranslucent")),))
    scene = PlacementScene(template=_mesh("template"), model=model, character=_mesh("character_hand"))
    # An older, structurally valid cache entry contains just the weapon. It must
    # not win over the newly composed reference scene after updating CDMW.
    old = build_or_lookup_rust_preview_package_with_builder(
        cache_root=tmp_path, cache_mode="balanced", max_bytes=1024 * 1024, target_bytes=512 * 1024,
        archive_identity=(f"new_item_preview:v3:{token!r}:placement:direct:materials=True:"
                          f"placement={scene.placement!r}:origin={scene.model_origin!r}"),
        builder=lambda target: build_rust_preview_package(
            model, output_package_dir=target, material_quality="direct",
            comparison_mode="overlay", interaction_profile="static_replacement", interaction_mode="placement",
        ),
    )
    args = dict(token=token, output_root=tmp_path, stop_event=threading.Event(), cache_mode="balanced")
    current = build_item_preview_package(scene, **args)
    assert current != old.package_dir
    _, document = _read_package(current)
    assert [part["name"] for part in document["lods"][0]["submeshes"]] == [
        "lambert1", "original_reference_0_template", "original_reference_1_character_hand",
    ]
    with patch("cdmw.services.mesh_rust_preview_package.build_rust_preview_package", side_effect=AssertionError("cache miss")):
        assert build_item_preview_package(scene, **args) == current


def test_reference_composition_preserves_other_lods_and_source(tmp_path):
    from cdmw.services.mesh_rust_authoring import _mesh_document_payload

    model = _mesh("lod0")
    model.lod_levels = [model.submeshes, _mesh("lod1").submeshes]
    original = _mesh_document_payload(model)
    package = build_rust_preview_package(
        model, reference_mesh=_mesh("reference"), output_package_dir=tmp_path / "comparison",
        include_material_resources=False,
    )
    _, document = _read_package(package)
    assert [part["name"] for part in document["lods"][0]["submeshes"]] == ["lod0", "original_reference_0_reference"]
    assert document["lods"][1:] == original["lods"][1:]
    assert _mesh_document_payload(model) == original
    standalone = build_rust_preview_package(model, output_package_dir=tmp_path / "standalone", include_material_resources=False)
    assert _read_package(standalone)[1] == original
