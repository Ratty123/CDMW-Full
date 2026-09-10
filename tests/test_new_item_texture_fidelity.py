"""Source import -> generated DDS -> plain-PBR bindings, using owned tiny assets."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from cdmw.core.dds_native import inspect_dds_native
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.models import ArchiveModelTextureReference
from cdmw.modding.full_import_model_replacement import FULL_IMPORT_MODEL_REPLACEMENT_PROFILE
from cdmw.modding.material_replacer import TextureReplacementReport, group_replacement_texture_sets
from cdmw.modding.material_source_driven import _build_source_driven_pac_material_payloads
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from cdmw.services.new_item_materials import route_model_files
from cdmw.services.new_item_planning import ModelFiles
from tests.test_new_item_materials import dds
from tests.test_pac_xml_standard_material import HEAD, TAIL, texture, wrapper
from tests.test_scene_importer_gltf import _triangle_payload


def write_gltf(root, materials, images):
    binary, document = _triangle_payload()
    (root / "source.bin").write_bytes(binary)
    document["buffers"][0]["uri"] = "source.bin"
    document["images"] = [{"uri": name} for name in images]
    document["textures"] = [{"source": index} for index in range(len(images))]
    document["materials"] = materials
    primitive = document["meshes"][0]["primitives"][0]
    document["meshes"][0]["primitives"] = [dict(deepcopy(primitive), material=index) for index in range(len(materials))]
    path = root / "source.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def export_materials(path, root):
    scene = import_scene_mesh_with_report(path)
    sets = group_replacement_texture_sets(scene.discovered_texture_files, obj_mesh=scene.mesh)
    targets = {f"part_{index}": part.material for index, part in enumerate(scene.mesh.submeshes)}
    sections = tuple(SimpleNamespace(target_submesh_name=name, source_material_name=source) for name, source in targets.items())
    xml_path = "character/modelproperty/sword.pac_xml"
    template_paths = {"base": "character/texture/sword_common.dds", "normal": "character/texture/sword_normal_n.dds"}
    template_files = {}
    references = []
    for role, name in template_paths.items():
        local = root / f"template_{role}.dds"
        local.write_bytes(dds(b"DXT1" if role == "base" else b"BC5U"))
        entry = SimpleNamespace(path=name)
        template_files[name] = local
        references.append(ArchiveModelTextureReference(
            reference_name=name, material_name="part_0", resolved_archive_path=name,
            sidecar_parameter_name="_baseColorTexture" if role == "base" else "_normalTexture", resolved_entry=entry,
        ))
    params = texture("_baseColorTexture", "1", template_paths["base"], 0) + texture("_normalTexture", "0", template_paths["normal"], 1)
    xml = HEAD + "".join(wrapper(name, "SkinnedMeshStandard_Ver2", params, 400 + index) for index, name in enumerate(targets)) + TAIL
    report = TextureReplacementReport()
    payloads = _build_source_driven_pac_material_payloads(
        texture_sets=sets, original_texture_refs=references,
        original_sidecars=((SimpleNamespace(path=xml_path), xml),), active_target_names=tuple(targets),
        target_to_source_material=targets,
        read_original_texture_bytes=lambda entry: template_files[entry.path].read_bytes(),
        original_texture_source_path=lambda entry: template_files[entry.path],
        report=report, on_log=None, texture_output_size_mode="source",
        complete_external_material_reset=True, neutralize_inherited_material_layers=True,
        complete_swap_material_profile=FULL_IMPORT_MODEL_REPLACEMENT_PROFILE,
    )
    assert not report.errors, report.errors
    files = route_model_files(
        ModelFiles(pac_data=b"owned synthetic geometry", side_files={payload.target_path: payload.payload_data for payload in payloads}),
        MaterialRoute.PLAIN_PBR, result=SimpleNamespace(source_owned_output_draw_sections=sections), scene=scene,
    )
    wrappers = {targets[item.submesh_name]: item for item in find_material_wrappers(files.side_files[xml_path].decode("utf-8-sig"))}
    assert len(wrappers) == len(scene.mesh.submeshes)
    return scene, files, wrappers


def pixels(files, material, role="_baseColorTexture"):
    data = files.side_files[material.textures[role]]
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("RGBA"))


def test_shared_images_and_factor_only_materials_keep_their_own_colour(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    materials = [
        {"name": "Tinted", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [0.5, 0.5, 0.5, 1]}},
        {"name": "White", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
        {"name": "Solid", "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, 1]}},
        {"name": "SameTint", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [0.5, 0.5, 0.5, 1]}},
    ]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["white.png"]), tmp_path)
    assert pixels(files, materials["White"])[0, 0, :3].tolist() == [255, 255, 255]
    np.testing.assert_array_equal(pixels(files, materials["Tinted"]), pixels(files, materials["Solid"]))
    assert materials["Tinted"].textures["_baseColorTexture"] == materials["SameTint"].textures["_baseColorTexture"]
    assert materials["White"].textures["_baseColorTexture"] != materials["Tinted"].textures["_baseColorTexture"]


@pytest.mark.parametrize("alpha", [0.0, 0.5])
def test_authored_opacity_reaches_dds_including_zero(tmp_path, alpha):
    Image.new("RGBA", (16, 16), (200, 100, 50, 128)).save(tmp_path / "alpha.png")
    material = {"name": "Alpha", "alphaMode": "BLEND", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [1, 1, 1, alpha]}}
    _, files, materials = export_materials(write_gltf(tmp_path, [material], ["alpha.png"]), tmp_path)
    assert abs(int(pixels(files, materials["Alpha"])[0, 0, 3]) - round(128 * alpha)) <= 1


def test_smooth_alpha_keeps_precision_and_reports_unsupported_shader_settings(tmp_path):
    image = Image.new("RGBA", (16, 16))
    image.putdata([(128, 64, 32, (x // 4) * 64) for y in range(16) for x in range(16)])
    image.save(tmp_path / "alpha.png")
    materials = [{"name": "Blend", "alphaMode": "BLEND", "doubleSided": True, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["alpha.png"]), tmp_path)
    np.testing.assert_array_equal(pixels(files, materials["Blend"])[:, :, 3], np.asarray(image)[:, :, 3])
    assert any("BLEND" in warning and "does not support" in warning for warning in files.warnings)
    assert any("double-sided" in warning for warning in files.warnings)
    info = inspect_dds_native(files.side_files[materials["Blend"].textures["_baseColorTexture"]])
    assert info.format_name == "BC3_UNORM"


@pytest.mark.parametrize("scale", [0.0, 0.5, 2.0, -1.0])
def test_normal_scale_is_baked_and_unrelated_parts_have_no_normal(tmp_path, scale):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    Image.new("RGB", (16, 16), (210, 180, 220)).save(tmp_path / "normal.png")
    materials = [
        {"name": "Normal", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "normalTexture": {"index": 1, "scale": scale}},
        {"name": "Flat", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
    ]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["white.png", "normal.png"]), tmp_path)
    assert "_normalTexture" not in materials["Flat"].textures
    expected = np.array([210, 180, 220]) / 127.5 - 1.0
    expected[:2] *= scale
    expected /= np.linalg.norm(expected)
    expected = np.rint((expected + 1.0) * 127.5).astype(int)
    actual = pixels(files, materials["Normal"], "_normalTexture")[0, 0, :2]
    np.testing.assert_allclose(actual, expected[:2], atol=2)


def test_obj_separate_pbr_maps_survive_import_and_plain_route(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "colour.png")
    Image.new("L", (16, 16), 51).save(tmp_path / "roughness.png")
    Image.new("L", (16, 16), 102).save(tmp_path / "metalness.png")
    (tmp_path / "source.mtl").write_text("newmtl SeparatePbr\nKd 1 1 1\nPr 1\nPm 1\nmap_Kd colour.png\nmap_Pr roughness.png\nmap_Pm metalness.png\n", encoding="utf-8")
    path = tmp_path / "source.obj"
    path.write_text("mtllib source.mtl\no Part\nusemtl SeparatePbr\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n", encoding="utf-8")
    _, files, materials = export_materials(path, tmp_path)
    np.testing.assert_allclose(pixels(files, materials["SeparatePbr"], "_materialTexture")[0, 0, 1:3], [51, 102], atol=4)
    assert not any("Builder's mask stands in" in warning for warning in files.warnings)


@pytest.mark.parametrize("strength", [0.0, 2.0])
def test_emissive_map_keeps_authored_tint_magnitude_and_strength(tmp_path, strength):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    materials = [{"name": "Glow", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "emissiveTexture": {"index": 0}, "emissiveFactor": [0.25, 0, 0], "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": strength}}}]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["white.png"]), tmp_path)
    material = materials["Glow"]
    assert material.value("_emissiveColor") == "#FF0000FF"
    assert float(material.value("_emissiveIntensity")) == strength
    assert abs(int(pixels(files, material, "_emissiveIntensityTexture")[0, 0, 0]) - 64) <= 1


@pytest.mark.parametrize("names", [("Paint", "paint"), ("Paint", "Paint")])
def test_material_indices_remain_distinct_when_display_names_collide(tmp_path, names):
    Image.new("RGB", (16, 16), "red").save(tmp_path / "red.png")
    Image.new("RGB", (16, 16), "blue").save(tmp_path / "blue.png")
    materials = [{"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": index}, "roughnessFactor": roughness, "metallicFactor": 0}}
                 for index, (name, roughness) in enumerate(zip(names, [0.2, 0.8]))]
    scene, files, materials = export_materials(write_gltf(tmp_path, materials, ["red.png", "blue.png"]), tmp_path)
    assert len({name.casefold() for name in materials}) == 2
    assert any("distinct" in text for text in scene.diagnostics)
    first, second = materials.values()
    np.testing.assert_array_equal(pixels(files, first)[0, 0, :3], [255, 0, 0])
    np.testing.assert_array_equal(pixels(files, second)[0, 0, :3], [0, 0, 255])
    assert abs(int(pixels(files, first, "_materialTexture")[0, 0, 1]) - 51) <= 4
    assert abs(int(pixels(files, second, "_materialTexture")[0, 0, 1]) - 204) <= 4


def test_opaque_alpha_and_mask_cutoff_are_handled_explicitly(tmp_path):
    Image.new("RGBA", (16, 16), (200, 100, 50, 32)).save(tmp_path / "alpha.png")
    materials = [
        {"name": "Opaque", "alphaMode": "OPAQUE", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [1, 1, 1, 0.5]}},
        {"name": "Masked", "alphaMode": "MASK", "alphaCutoff": 0.25, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
    ]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["alpha.png"]), tmp_path)
    assert pixels(files, materials["Opaque"])[0, 0, 3] == 255
    assert pixels(files, materials["Masked"])[0, 0, 3] == 32
    assert any("MASK (cutoff 0.25)" in warning for warning in files.warnings)


def test_normal_scale_already_baked_for_multiple_uv_sets_is_not_applied_twice(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    Image.new("RGB", (16, 16), (210, 180, 220)).save(tmp_path / "normal.png")
    materials = [{"name": "Normal", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "normalTexture": {"index": 1, "texCoord": 1, "scale": 0.5}}]
    path = write_gltf(tmp_path, materials, ["white.png", "normal.png"])
    document = json.loads(path.read_text(encoding="utf-8"))
    document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_1"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")
    scene, files, materials = export_materials(path, tmp_path)
    normal_path = next(path for role, path in scene.material_bindings[0].texture_slots if role == "normal")
    assert normal_path != tmp_path / "normal.png", "the multi-UV importer must have raster-baked this map"
    with Image.open(normal_path) as image:
        source = np.asarray(image.convert("RGB"))[:, :, :2].astype(float)
    actual = pixels(files, materials["Normal"], "_normalTexture")[:, :, :2].astype(float)
    assert np.abs(actual - source).mean() < 2.0, "export must not reapply the already baked normal scale"


def test_dds_normals_apply_scale_but_unmodified_dds_can_still_pass_through(tmp_path):
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.modding.material_replacer import ReplacementTextureSlot
    from cdmw.modding.material_texture_payloads import _build_texture_payload

    png = tmp_path / "normal.png"
    source = tmp_path / "normal.dds"
    Image.new("RGB", (16, 16), (210, 180, 220)).save(png)
    assert encode_dds_with_directxtex(png, source, dds_format="BC5_UNORM", width=16, height=16, mip_count=5)
    original = source.read_bytes()
    for scale in (0.0, 1.0):
        data = _build_texture_payload(
            ReplacementTextureSlot("Normal", "normal", source, normal_scale=scale),
            target_entry=SimpleNamespace(path="character/texture/normal_n.dds"),
            read_original_texture_bytes=lambda entry: original,
            original_texture_source_path=lambda entry: source,
            report=TextureReplacementReport(), on_log=None,
        )
        if scale == 1.0:
            assert data == original
        else:
            with Image.open(BytesIO(data)) as image:
                np.testing.assert_allclose(np.asarray(image)[0, 0, :2], [128, 128], atol=1)
    assert source.read_bytes() == original
