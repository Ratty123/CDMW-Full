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


def export_materials(path, root, *, socket_attached=False, atlas=False, glow=None, translucency=None, scene=None):
    if scene is None:
        scene = import_scene_mesh_with_report(path)
    if socket_attached:
        from dataclasses import replace

        from cdmw.services.new_item_variants import bind_static_import_to_attachment
        from tests.test_new_item_variant_rig import MODEL, PREFAB, _snapshot

        scene = replace(scene, mesh=bind_static_import_to_attachment(scene.mesh, MODEL, _snapshot().payload(PREFAB)))
    sets = group_replacement_texture_sets(scene.discovered_texture_files, obj_mesh=scene.mesh)
    targets = {f"part_{index}": part.material for index, part in enumerate(scene.mesh.submeshes)}
    sections = tuple(SimpleNamespace(target_submesh_name=name, source_material_name=source) for name, source in targets.items())
    if atlas:
        from cdmw.modding.static_mesh_types import StaticMaterialAtlasRect, StaticOutputDrawSection

        names = tuple(targets.values())
        targets = {"part_0": " + ".join(names)}
        sections = (StaticOutputDrawSection(
            0, 0, "part_0", list(range(len(names))), source_material_name=targets["part_0"],
            atlas_source_material_names=names, atlas_material_name="part_0_atlas",
            atlas_rects=tuple(StaticMaterialAtlasRect(name, (index,), index / len(names), 0, 1 / len(names), 1)
                              for index, name in enumerate(names)),
        ),)
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
        output_draw_sections=sections,
        complete_external_material_reset=True, neutralize_inherited_material_layers=True,
        complete_swap_material_profile=FULL_IMPORT_MODEL_REPLACEMENT_PROFILE,
    )
    assert not report.errors, report.errors
    files = route_model_files(
        ModelFiles(pac_data=b"owned synthetic geometry", side_files={payload.target_path: payload.payload_data for payload in payloads}),
        MaterialRoute.PLAIN_PBR, result=SimpleNamespace(source_owned_output_draw_sections=sections), scene=scene, glow=glow,
        translucency=translucency,
    )
    wrappers = {targets[item.submesh_name]: item for item in find_material_wrappers(files.side_files[xml_path].decode("utf-8-sig"))}
    assert len(wrappers) == len(targets)
    return scene, files, wrappers


def pixels(files, material, role="_baseColorTexture"):
    data = files.side_files[material.textures[role]]
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("RGBA"))


@pytest.mark.parametrize("authored_glass", [False, True])
def test_translucent_colour_uses_source_precision_without_changing_shared_opaque_parts(tmp_path, authored_glass):
    from cdmw.domain.new_item.translucency import TranslucencyChoice

    y, x = np.indices((32, 32))
    source = np.stack((24 + x, 27 + y, 31 + (x + y) // 2), axis=-1).astype(np.uint8)
    Image.fromarray(source).save(tmp_path / "colour.png")
    materials = [{"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
                 for name in ("Glass", "Opaque")]
    if authored_glass:
        materials[0]["extensions"] = {"KHR_materials_transmission": {"transmissionFactor": 0.5}}
    _, files, wrappers = export_materials(
        write_gltf(tmp_path, materials, ["colour.png"]), tmp_path, socket_attached=True,
        translucency=None if authored_glass else TranslucencyChoice(("Glass",)),
    )
    glass, opaque = wrappers["Glass"], wrappers["Opaque"]
    assert glass.textures["_baseColorTexture"] != opaque.textures["_baseColorTexture"]
    for material, expected in ((glass, "BC7_UNORM"), (opaque, "BC1_UNORM")):
        info = inspect_dds_native(files.side_files[material.textures["_baseColorTexture"]])
        assert info.format_name == expected
        assert (info.width, info.height, info.mip_count) == (32, 32, 6)
    # Re-encoding the Builder's BC1 into BC7 would fail this precision check.
    error = lambda material: np.abs(pixels(files, material)[:, :, :3].astype(float) - source).mean()
    assert error(glass) < error(opaque) * 0.5
    assert np.all(pixels(files, glass)[:, :, 3] == 255)
    assert opaque.shader == "SkinnedMeshStandard"


def test_translucent_atlas_bakes_original_colours_factors_and_alpha_once(tmp_path):
    from cdmw.domain.new_item.translucency import TranslucencyChoice

    Image.new("RGBA", (16, 16), (200, 100, 50, 128)).save(tmp_path / "colour.png")
    materials = [
        {"name": "OpaqueSource", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
        {"name": "GlassSource", "alphaMode": "BLEND",
         "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [0.25, 1, 1, 0.5]}},
    ]
    path = write_gltf(tmp_path, materials, ["colour.png"])
    _, files, wrappers = export_materials(path, tmp_path, atlas=True,
        translucency=TranslucencyChoice(("OpaqueSource", "GlassSource")))
    material = next(iter(wrappers.values()))
    assert inspect_dds_native(files.side_files[material.textures["_baseColorTexture"]]).format_name == "BC7_UNORM"
    rgba = pixels(files, material)
    h, w, _ = rgba.shape
    np.testing.assert_allclose(rgba[h // 2, w // 4], [200, 100, 50, 255], atol=1)
    np.testing.assert_allclose(rgba[h // 2, w * 3 // 4], [50, 100, 50, 64], atol=1)


def test_standalone_authored_dds_is_not_recompressed_for_translucency(tmp_path):
    from cdmw.domain.new_item.translucency import TranslucencyChoice

    original = dds(b"DXT1")
    (tmp_path / "colour.dds").write_bytes(original)
    (tmp_path / "source.mtl").write_text("newmtl Glass\nKd 1 1 1\nmap_Kd colour.dds\n", encoding="utf-8")
    path = tmp_path / "source.obj"
    path.write_text("mtllib source.mtl\no Part\nusemtl Glass\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n", encoding="utf-8")
    _, files, wrappers = export_materials(path, tmp_path, translucency=TranslucencyChoice(("Glass",)))
    material = wrappers["Glass"]
    assert material.shader == "SkinnedMeshTranslucent"
    assert files.side_files[material.textures["_baseColorTexture"]] == original


@pytest.mark.parametrize("alpha_mode, expected_alpha", [("BLEND", 64), ("OPAQUE", 255)])
def test_selected_translucency_keeps_source_alpha_through_import_and_export(tmp_path, alpha_mode, expected_alpha):
    from cdmw.domain.new_item.translucency import TranslucencyChoice

    Image.new("RGBA", (16, 16), (200, 100, 50, 128)).save(tmp_path / "glass.png")
    materials = [
        {"name": "Glass", "alphaMode": alpha_mode, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [1, 1, 1, 0.5]}},
        {"name": "Grip", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
    ]
    _, files, wrappers = export_materials(
        write_gltf(tmp_path, materials, ["glass.png"]), tmp_path,
        socket_attached=True, translucency=TranslucencyChoice(("Glass",), 0.2, 0.6),
    )
    assert wrappers["Glass"].shader == "SkinnedMeshTranslucent"
    assert wrappers["Glass"].value("_thickness") == "0.200000"
    assert wrappers["Glass"].value("_extinctionCoefficient") == "0.600000"
    assert abs(int(pixels(files, wrappers["Glass"])[0, 0, 3]) - expected_alpha) <= 1
    assert wrappers["Grip"].shader == "SkinnedMeshStandard"


@pytest.mark.parametrize("selected_parts", [(), ("Blade",), ("GemOutside",)])
def test_authored_glass_shell_does_not_hide_or_recolour_the_emissive_gem(tmp_path, selected_parts):
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.services.new_item_translucency import translucency_preview_parameter_groups

    # A red glass shell around a turquoise surface with red emission. Selecting
    # the blade must not make the unselected source glass opaque during export.
    materials = [
        {"name": "Blade", "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.2, 0.2, 1]}},
        {"name": "GemOutside", "alphaMode": "BLEND", "doubleSided": True,
         "pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 0.5], "roughnessFactor": 0},
         "extensions": {"KHR_materials_transmission": {"transmissionFactor": 0.5}}},
        {"name": "GemInside", "emissiveFactor": [1, 0, 0],
         "pbrMetallicRoughness": {"baseColorFactor": [0, 1, 0.7911, 1], "roughnessFactor": 0.92},
         "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 10}}},
    ]
    choice = TranslucencyChoice(selected_parts, 0.05, 0.5) if selected_parts else None
    scene, files, wrappers = export_materials(
        write_gltf(tmp_path, materials, []), tmp_path, socket_attached=True, translucency=choice,
    )
    shell = wrappers["GemOutside"]
    assert shell.shader == "SkinnedMeshTranslucent"
    absorption = (0.05, 0.5) if "GemOutside" in selected_parts else (0.1, 0.3)
    assert float(shell.value("_thickness")) == absorption[0]
    assert float(shell.value("_extinctionCoefficient")) == absorption[1]
    np.testing.assert_allclose(pixels(files, shell)[0, 0], [255, 0, 0, 128], atol=1)
    gem = wrappers["GemInside"]
    assert gem.shader == "SkinnedMeshEmissive"
    assert gem.value("_emissiveColor") == "#FF0000FF"
    assert float(gem.value("_emissiveIntensity")) == 10
    assert pixels(files, gem, "_emissiveIntensityTexture")[0, 0, 0] == 255
    base = pixels(files, gem)[0, 0]
    assert base[0] == 0 and base[1] == 255 and 198 <= base[2] <= 210 and base[3] == 255
    assert wrappers["Blade"].shader == ("SkinnedMeshTranslucent" if "Blade" in selected_parts else "SkinnedMeshStandard")
    groups = translucency_preview_parameter_groups(scene.mesh, choice)
    for part, group in zip(scene.mesh.submeshes, groups):
        exported = wrappers[part.material]
        if exported.shader == "SkinnedMeshTranslucent":
            assert group["translucency"] == [float(exported.value("_thickness")), float(exported.value("_extinctionCoefficient"))]
        else:
            assert group["translucency"] is None
    if "GemOutside" not in selected_parts:
        assert any("GemOutside" in warning and "approximates" in warning for warning in files.warnings)
    assert not any("GemOutside" in warning and "does not support" in warning for warning in files.warnings)


@pytest.mark.parametrize("transmission, shader", [(0, "SkinnedMeshStandard"), (0.5, "SkinnedMeshTranslucent")])
def test_source_transmission_is_independent_of_alpha_mode(tmp_path, transmission, shader):
    materials = [{"name": "Glass", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.2, 0.1, 1]},
                  "extensions": {"KHR_materials_transmission": {"transmissionFactor": transmission}}}]
    _, _, wrappers = export_materials(write_gltf(tmp_path, materials, []), tmp_path)
    assert wrappers["Glass"].shader == shader


@pytest.mark.parametrize("edit", ["delete", "reorder"])
def test_mesh_edit_rebinds_glass_and_emission_to_the_surviving_materials(tmp_path, edit):
    from cdmw.modding.mesh_edit_ops import _delete_submeshes
    from cdmw.services.new_item_translucency import translucency_preview_parameter_groups
    from cdmw.ui.new_item.model_import import prepare_model_import_mesh_edit

    Image.new("RGB", (16, 16), "white").save(tmp_path / "glass.png")
    path = write_gltf(tmp_path, [
        {"name": "Opaque", "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.2, 0.2, 1]}},
        {"name": "Glass", "alphaMode": "BLEND", "doubleSided": True,
         "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [1, 0, 0, 0.5]},
         "extensions": {"KHR_materials_transmission": {"transmissionFactor": 0.5}}},
        {"name": "Glow", "emissiveFactor": [1, 0, 0],
         "pbrMetallicRoughness": {"baseColorFactor": [0, 1, 0.7911, 1]},
         "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 10}}},
    ], ["glass.png"])
    scene = import_scene_mesh_with_report(path)
    original_bindings = deepcopy(scene.material_bindings)
    mesh = deepcopy(scene.mesh)
    if edit == "delete":
        _delete_submeshes(mesh, [0])
    else:
        mesh.submeshes.reverse()
    edited_scene, _, _, _ = prepare_model_import_mesh_edit(mesh, scene=scene, model_path=path)
    assert scene.material_bindings == original_bindings
    for binding in edited_scene.material_bindings:
        part = mesh.submeshes[binding.submesh_index]
        assert binding.material_name == part.material
        assert binding.submesh_name == part.name
        original = next(row for row in original_bindings if row.material_name == part.material)
        assert binding.texture_slots == original.texture_slots
    assert {binding.material_name for binding in edited_scene.material_bindings} == {part.material for part in mesh.submeshes}
    _, files, wrappers = export_materials(path, tmp_path, scene=edited_scene, socket_attached=True)
    assert wrappers["Glass"].shader == "SkinnedMeshTranslucent"
    np.testing.assert_allclose(pixels(files, wrappers["Glass"])[0, 0], [255, 0, 0, 128], atol=1)
    assert wrappers["Glow"].shader == "SkinnedMeshEmissive"
    assert wrappers["Glow"].value("_emissiveColor") == "#FF0000FF"
    assert float(wrappers["Glow"].value("_emissiveIntensity")) == 10
    preview = translucency_preview_parameter_groups(mesh)
    assert [group["translucency"] for group in preview] == [
        [0.1, 0.3] if part.material == "Glass" else None for part in mesh.submeshes
    ]


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


def test_socket_attachment_keeps_gem_colour_and_textured_material_factors(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "blade_basecolor.png")
    Image.new("RGB", (16, 16), (210, 180, 220)).save(tmp_path / "blade_normal.png")
    materials = [
        {"name": "Blade", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [0, 0, 1, 1]},
         "normalTexture": {"index": 1, "scale": 0}},
        {"name": "Gem", "alphaMode": "BLEND", "pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 0.5]}},
    ]
    scene, files, materials = export_materials(
        write_gltf(tmp_path, materials, ["blade_basecolor.png", "blade_normal.png"]), tmp_path, socket_attached=True,
    )
    assert scene.mesh.has_bones
    assert pixels(files, materials["Blade"])[0, 0].tolist() == [0, 0, 255, 255]
    assert pixels(files, materials["Gem"])[0, 0].tolist() == [255, 0, 0, 128]
    assert pixels(files, materials["Blade"], "_normalTexture")[0, 0, :2].tolist() == [128, 128]
    assert "_normalTexture" not in materials["Gem"].textures
    assert all(material.shader == "SkinnedMeshStandard" for material in materials.values())


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


@pytest.mark.parametrize("socket_attached", [False, True])
@pytest.mark.parametrize("strength", [0.0, 2.0, 32.0])
def test_emissive_map_keeps_authored_tint_magnitude_and_strength(tmp_path, strength, socket_attached):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    materials = [{"name": "Glow", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "emissiveTexture": {"index": 0}, "emissiveFactor": [0.25, 0, 0], "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": strength}}}]
    _, files, materials = export_materials(write_gltf(tmp_path, materials, ["white.png"]), tmp_path, socket_attached=socket_attached)
    material = materials["Glow"]
    assert material.value("_emissiveColor") == "#FF0000FF"
    assert float(material.value("_emissiveIntensity")) == strength
    assert abs(int(pixels(files, material, "_emissiveIntensityTexture")[0, 0, 0]) - 64) <= 1


@pytest.mark.parametrize("disable_gem", [False, True])
def test_atlas_keeps_blue_runes_separate_strengths_and_dark_regions(tmp_path, disable_gem):
    from cdmw.domain.new_item.spec import GlowChoice

    Image.new("RGB", (16, 16), "white").save(tmp_path / "base.png")
    emission = Image.new("RGB", (16, 16), "black")
    emission.paste((0, 0, 255), (4, 4, 12, 12))
    emission.save(tmp_path / "runes_emissive.png")
    materials = [
        {"name": "Runes", "emissiveTexture": {"index": 1}, "emissiveFactor": [1, 1, 1],
         "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 4.5522127}}},
        {"name": "Gem", "emissiveFactor": [0, 0, 1],
         "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 2}}},
        {"name": "Skull"},
    ]
    for material in materials:
        material["pbrMetallicRoughness"] = {"baseColorTexture": {"index": 0}}
    _, files, materials = export_materials(
        write_gltf(tmp_path, materials, ["base.png", "runes_emissive.png"]), tmp_path, socket_attached=True, atlas=True,
        glow=GlowChoice(parts=("Gem",), color=(0, 0, 1), intensity=0) if disable_gem else None,
    )
    material = next(iter(materials.values()))
    assert material.shader == "SkinnedMeshEmissive"
    assert material.value("_emissiveColor") == "#0000FFFF"
    assert float(material.value("_emissiveIntensity")) == pytest.approx(4.5522127, abs=1e-6)
    mask = pixels(files, material, "_emissiveIntensityTexture")[:, :, 0]
    height, width = mask.shape
    assert int(mask[height // 2, width // 6]) >= 250
    assert abs(int(mask[height // 2, width // 2]) - (0 if disable_gem else round(255 * 2 / 4.5522127))) <= 2
    assert not mask[:, 2 * width // 3:].any(), "non-emissive atlas regions must stay dark"
    assert int(mask[height // 32, width // 6]) == 0, "only the rune mask glows"


def test_dim_blue_emission_keeps_its_hue(tmp_path):
    from cdmw.services.new_item_materials import encode_emissive_from_png

    path = tmp_path / "dim_blue.png"
    Image.new("RGB", (16, 16), (0, 0, 3)).save(path)
    data, color = encode_emissive_from_png(path)
    assert color == "#0000FFFF"
    with Image.open(BytesIO(data)) as mask:
        assert mask.convert("RGB").getpixel((0, 0)) == (3, 3, 3)


@pytest.mark.parametrize("atlas", [False, True])
def test_glow_override_keeps_the_source_mask_multiplier_with_or_without_an_atlas(tmp_path, atlas):
    from cdmw.domain.new_item.spec import GlowChoice

    Image.new("RGB", (16, 16), "white").save(tmp_path / "white.png")
    material = {"name": "Runes", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                "emissiveTexture": {"index": 0}, "emissiveFactor": [0.25, 0, 0]}
    _, files, materials = export_materials(
        write_gltf(tmp_path, [material], ["white.png"]), tmp_path, atlas=atlas,
        glow=GlowChoice(parts=("Runes",), color=(0, 0, 1), intensity=5),
    )
    material = next(iter(materials.values()))
    assert material.value("_emissiveColor") == "#0000FFFF"
    assert float(material.value("_emissiveIntensity")) == 5
    assert abs(int(pixels(files, material, "_emissiveIntensityTexture")[0, 0, 0]) - 64) <= 1


def test_declared_emissive_texture_cannot_silently_disappear(tmp_path):
    from cdmw.services.new_item_materials import source_materials_from_import
    from cdmw.services.new_item_planning import NewItemPlanError

    Image.new("RGB", (16, 16), "white").save(tmp_path / "base.png")
    emission = tmp_path / "emissive.png"
    Image.new("RGB", (16, 16), "blue").save(emission)
    material = {"name": "Runes", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                "emissiveTexture": {"index": 1}, "emissiveFactor": [1, 1, 1]}
    scene = import_scene_mesh_with_report(write_gltf(tmp_path, [material], ["base.png", "emissive.png"]))
    emission.unlink()
    result = SimpleNamespace(source_owned_output_draw_sections=(SimpleNamespace(target_submesh_name="blade", source_material_name="Runes"),))
    with pytest.raises(NewItemPlanError, match="Runes: the declared emissive texture is unavailable"):
        source_materials_from_import(result, scene)


def test_obj_emissive_map_and_colour_survive_socket_attachment(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "base.png")
    emission = Image.new("RGB", (16, 16), "black")
    emission.paste("white", (4, 4, 12, 12))
    emission.save(tmp_path / "runes.png")
    (tmp_path / "source.mtl").write_text("newmtl Runes\nKd 1 1 1\nmap_Kd base.png\nKe 0 0 1\nmap_Ke runes.png\n", encoding="utf-8")
    path = tmp_path / "source.obj"
    path.write_text("mtllib source.mtl\no Blade\nusemtl Runes\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n", encoding="utf-8")
    _, files, materials = export_materials(path, tmp_path, socket_attached=True)
    material = materials["Runes"]
    assert material.shader == "SkinnedMeshEmissive"
    assert material.value("_emissiveColor") == "#0000FFFF"
    assert float(material.value("_emissiveIntensity")) == 1.0
    np.testing.assert_array_equal(pixels(files, material, "_emissiveIntensityTexture")[:, :, 0], np.asarray(emission)[:, :, 0])


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


@pytest.mark.parametrize("source_format", ["BC7_UNORM", "BC7_UNORM_SRGB"])
@pytest.mark.parametrize("template_fourcc", [b"DXT1", b"DXT5"], ids=["bc1-template", "bc3-template"])
@pytest.mark.parametrize("edit", ["unchanged", "colour", "alpha", "opaque", "blend"])
def test_bc7_dds_preserves_format_and_pixels_when_material_settings_require_encoding(
    tmp_path, source_format, template_fourcc, edit,
):
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.modding.material_replacer import ReplacementTextureSlot
    from cdmw.modding.material_texture_payloads import _build_texture_payload

    png, source, template = (tmp_path / name for name in ("colour.png", "colour.dds", "template.dds"))
    Image.new("RGBA", (16, 16), (128, 96, 64, 160)).save(png)
    assert encode_dds_with_directxtex(png, source, dds_format=source_format, width=16, height=16, mip_count=5,
                                     source_color_policy="assume_srgb" if source_format.endswith("_SRGB") else "auto")
    original = source.read_bytes()
    template_bytes = dds(template_fourcc)
    template.write_bytes(template_bytes)
    settings = {
        "unchanged": {}, "colour": {"base_color_factor": (0.5, 1.0, 1.0)},
        "alpha": {"base_alpha_factor": 0.5, "alpha_mode": "BLEND"},
        "opaque": {"alpha_mode": "OPAQUE"}, "blend": {"alpha_mode": "BLEND"},
    }[edit]
    payload = _build_texture_payload(
        ReplacementTextureSlot("Colour", "base", source, **settings),
        target_entry=SimpleNamespace(path="character/texture/colour.dds"),
        read_original_texture_bytes=lambda _entry: template_bytes,
        original_texture_source_path=lambda _entry: template,
        report=TextureReplacementReport(), on_log=None,
    )
    info = inspect_dds_native(payload)
    assert info.format_name == source_format
    assert (info.width, info.height, info.mip_count) == (16, 16, 5)
    with Image.open(BytesIO(original)) as image:
        expected = np.asarray(image.convert("RGBA"))[0, 0].astype(float)
    if edit == "colour":
        expected[0] *= 0.5
    elif edit == "alpha":
        expected[3] *= 0.5
    elif edit == "opaque":
        expected[3] = 255
    with Image.open(BytesIO(payload)) as image:
        np.testing.assert_allclose(np.asarray(image.convert("RGBA"))[0, 0], expected, atol=2)
    if edit == "unchanged":
        assert payload == original
    assert source.read_bytes() == original
    assert template.read_bytes() == template_bytes


@pytest.mark.parametrize("source_format", ["BC7_UNORM", "BC7_UNORM_SRGB"])
def test_new_item_bc7_colour_keeps_its_format_after_import_and_factor_bake(tmp_path, source_format):
    from cdmw.core.texture_native import encode_dds_with_directxtex

    png, source = tmp_path / "colour.png", tmp_path / "colour.dds"
    Image.new("RGBA", (16, 16), (128, 96, 64, 255)).save(png)
    assert encode_dds_with_directxtex(png, source, dds_format=source_format, width=16, height=16, mip_count=5,
                                     source_color_policy="assume_srgb" if source_format.endswith("_SRGB") else "auto")
    original = source.read_bytes()
    path = write_gltf(tmp_path, [{"name": "Opaque", "pbrMetallicRoughness": {
        "baseColorTexture": {"index": 0}, "baseColorFactor": [0.5, 1, 1, 1],
    }}], ["colour.dds"])
    _, files, materials = export_materials(path, tmp_path, socket_attached=True)
    material = materials["Opaque"]
    assert material.shader == "SkinnedMeshStandard"
    info = inspect_dds_native(files.side_files[material.textures["_baseColorTexture"]])
    assert info.format_name == source_format
    np.testing.assert_allclose(pixels(files, material)[0, 0], [64, 96, 64, 255], atol=2)
    assert source.read_bytes() == original


def test_bc7_normal_conversion_keeps_bc5_and_numeric_channels(tmp_path):
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.modding.material_replacer import ReplacementTextureSlot
    from cdmw.modding.material_texture_payloads import _build_texture_payload

    png, source = tmp_path / "normal.png", tmp_path / "normal.dds"
    Image.new("RGB", (16, 16), (128, 96, 250)).save(png)
    assert encode_dds_with_directxtex(png, source, dds_format="BC7_UNORM_SRGB", width=16, height=16,
                                     mip_count=5, source_color_policy="assume_srgb")
    original = source.read_bytes()
    data = _build_texture_payload(
        ReplacementTextureSlot("Normal", "normal", source, normal_space="green_up"),
        target_entry=SimpleNamespace(path="character/texture/normal_n.dds"),
        read_original_texture_bytes=lambda _entry: original,
        original_texture_source_path=lambda _entry: source,
        report=TextureReplacementReport(), on_log=None,
    )
    assert inspect_dds_native(data).format_name == "BC5_UNORM"
    with Image.open(BytesIO(data)) as image:
        np.testing.assert_allclose(np.asarray(image.convert("RGBA"))[0, 0, :2], [128, 159], atol=2)
    assert source.read_bytes() == original
