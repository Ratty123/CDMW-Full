"""Independent surface edits reach the viewport, variants and actual DDS output."""
from dataclasses import replace
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.new_item.surface import SurfaceEdit, validate_surface_settings
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_surface import apply_surface_settings, surface_preview_groups, surface_preview_mesh
from cdmw.services.new_item_translucency import translucency_preview_mesh
from cdmw.ui.new_item.surface_editor import SurfaceEditor
from tests.test_new_item_texture_fidelity import export_materials, pixels, write_gltf


def _result(scene, *, atlas=False):
    if not atlas:
        sections = tuple(SimpleNamespace(target_submesh_name=f"part_{i}", source_material_name=part.material)
                         for i, part in enumerate(scene.mesh.submeshes))
    else:
        from cdmw.modding.static_mesh_types import StaticMaterialAtlasRect, StaticOutputDrawSection
        names = tuple(part.material for part in scene.mesh.submeshes)
        sections = (StaticOutputDrawSection(0, 0, "part_0", list(range(len(names))),
            source_material_name=" + ".join(names), atlas_source_material_names=names, atlas_material_name="part_0_atlas",
            atlas_rects=tuple(StaticMaterialAtlasRect(name, (i,), i / len(names), 0, 1 / len(names), 1)
                              for i, name in enumerate(names))),)
    return SimpleNamespace(source_owned_output_draw_sections=sections)


def _wrappers(files):
    xml = next(data for path, data in files.side_files.items() if path.endswith(".pac_xml"))
    return find_material_wrappers(xml.decode("utf-8-sig"))


def test_red_gem_surface_is_independent_of_glow_and_glass(tmp_path):
    materials = [
        {"name": "Gem_inside", "emissiveFactor": [1, 0, 0],
         "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 10}},
         "pbrMetallicRoughness": {"baseColorFactor": [0, 1, 0.79, 1], "roughnessFactor": 0.92}},
        {"name": "Gem_outside", "alphaMode": "BLEND", "doubleSided": True,
         "extensions": {"KHR_materials_transmission": {"transmissionFactor": 0.5}},
         "pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 0.5], "roughnessFactor": 0}},
        {"name": "Blade", "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.3, 0.4, 1]}},
    ]
    scene, files, before = export_materials(write_gltf(tmp_path, materials, []), tmp_path, socket_attached=True)
    original = dict(files.side_files)
    choices = (("Gem_inside", SurfaceEdit((1, 0, 0), metallic=0)),
               ("Gem_outside", SurfaceEdit(roughness=0.9, metallic=0)))
    edited = apply_surface_settings(files, choices, result=_result(scene), scene=scene)
    inner, outer, blade = _wrappers(edited)
    assert files.side_files == original and edited.pac_data == files.pac_data
    assert inner.shader == "SkinnedMeshEmissive" and outer.shader == "SkinnedMeshTranslucent"
    assert inner.value("_emissiveColor") == "#FF0000FF" and float(inner.value("_emissiveIntensity")) == 10
    assert inner.textures["_emissiveIntensityTexture"] == before["Gem_inside"].textures["_emissiveIntensityTexture"]
    np.testing.assert_allclose(pixels(edited, inner)[0, 0], [255, 0, 0, 255], atol=1)
    np.testing.assert_allclose(pixels(edited, outer)[0, 0], [255, 0, 0, 128], atol=1)
    np.testing.assert_allclose(pixels(edited, inner, "_materialTexture")[0, 0], [255, 235, 0, 255], atol=1)
    np.testing.assert_allclose(pixels(edited, outer, "_materialTexture")[0, 0], [255, 230, 0, 255], atol=1)
    assert outer.value("_thickness") == before["Gem_outside"].value("_thickness")
    assert blade.textures == before["Blade"].textures
    assert surface_preview_groups(scene.mesh, choices)[0]["glow_surface_color"] == [1, 0, 0]
    assert apply_surface_settings(files, ()) is files


def test_shared_texture_edit_is_private_and_does_not_turn_on_glow(tmp_path):
    Image.new("RGBA", (16, 16), (0, 120, 240, 128)).save(tmp_path / "colour.png")
    materials = [{"name": name, "alphaMode": "BLEND", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
                 for name in ("Gem", "Other")]
    scene, files, before = export_materials(write_gltf(tmp_path, materials, ["colour.png"]), tmp_path)
    edited = apply_surface_settings(files, (("Gem", SurfaceEdit((1, 0, 0), 0.9, 0)),), result=_result(scene), scene=scene)
    gem, other = _wrappers(edited)
    assert gem.shader == other.shader == "SkinnedMeshStandard"
    assert "_emissiveIntensityTexture" not in gem.textures
    assert other.textures == before["Other"].textures
    rgba = pixels(edited, gem)
    assert rgba[0, 0, 0] >= 235 and rgba[:, :, 1:3].max() <= 1
    assert abs(int(rgba[0, 0, 3]) - 128) <= 1


def test_atlas_changes_only_selected_cells(tmp_path):
    Image.new("RGB", (16, 16), (0, 200, 180)).save(tmp_path / "colour.png")
    materials = [{"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}} for name in ("Gem", "Other")]
    scene, files, _ = export_materials(write_gltf(tmp_path, materials, ["colour.png"]), tmp_path, atlas=True)
    before = _wrappers(files)[0]
    edited = apply_surface_settings(files, (("Gem", SurfaceEdit((1, 0, 0), 0.9, 0)),), result=_result(scene, atlas=True), scene=scene)
    after = _wrappers(edited)[0]
    rgb, sp = pixels(edited, after), pixels(edited, after, "_materialTexture")
    y, left, right = rgb.shape[0] // 2, rgb.shape[1] // 4, rgb.shape[1] * 3 // 4
    assert rgb[y, left, 0] > 190 and rgb[y, left, 1:3].max() < 2
    np.testing.assert_allclose(rgb[y, right], pixels(files, before)[y, right], atol=2)
    np.testing.assert_allclose(sp[y, left, 1:3], [230, 0], atol=2)
    np.testing.assert_allclose(sp[y, right], pixels(files, before, "_materialTexture")[y, right], atol=2)


def test_preview_partial_override_retains_translucency_channel_and_source(tmp_path):
    from cdmw.modding.scene_importer import import_scene_mesh_with_report
    scene = import_scene_mesh_with_report(write_gltf(tmp_path, [{"name": "Gem"}], []))
    original = dict(scene.mesh.submeshes[0].preview_native_material_overrides)
    glass = TranslucencyChoice.from_settings({"Gem": (0.1, 0.3)}, {"Gem": (0.7, 1.0)})
    choices = (("Gem", SurfaceEdit(metallic=0)),)
    group = surface_preview_groups(scene.mesh, choices, translucency=glass)[0]
    assert group["translucency_surface"] == [0.7, 0]
    mesh = surface_preview_mesh(translucency_preview_mesh(scene.mesh, glass), choices)
    overrides = mesh.submeshes[0].preview_native_material_overrides
    assert overrides["translucency_surface"] == [0.7, 0]
    assert overrides["translucency"] == [0.1, 0.3]
    assert scene.mesh.submeshes[0].preview_native_material_overrides == original


@pytest.mark.parametrize("choice", [SurfaceEdit((1, 0)), SurfaceEdit(metallic=float("nan")), SurfaceEdit(roughness=-0.1)])
def test_invalid_surface_is_rejected(choice):
    with pytest.raises(ValueError):
        validate_surface_settings((("Gem", choice),))


def test_missing_material_is_an_error(tmp_path):
    scene, files, _ = export_materials(write_gltf(tmp_path, [{"name": "Gem", "pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1]}}], []), tmp_path)
    with pytest.raises(ValueError, match="missing"):
        apply_surface_settings(files, (("Missing", SurfaceEdit(metallic=0)),), result=_result(scene), scene=scene)


def test_cloned_wrapper_inherits_owned_source(tmp_path):
    scene, files, _ = export_materials(write_gltf(tmp_path, [{"name": "Gem",
        "pbrMetallicRoughness": {"baseColorFactor": [0, 1, 1, 1]}}], []), tmp_path)
    path = next(path for path in files.side_files if path.endswith(".pac_xml"))
    xml = files.side_files[path].decode("utf-8-sig")
    original = _wrappers(files)[0]
    start = xml.rfind("<SkinnedMeshMaterialWrapper ", 0, original.start)
    end = xml.index("</SkinnedMeshMaterialWrapper>", original.end) + len("</SkinnedMeshMaterialWrapper>")
    clone = xml[start:end].replace('_subMeshName="part_0"', '_subMeshName="cloned_part"')
    xml = xml[:end] + clone + xml[end:]
    files = replace(files, side_files={**files.side_files, path: xml.encode("utf-8")})
    edited = apply_surface_settings(files, (("Gem", SurfaceEdit((1, 0, 0), metallic=0)),),
                                    result=_result(scene), scene=scene)
    first, second = _wrappers(edited)
    assert first.textures == second.textures
    np.testing.assert_allclose(pixels(edited, second)[0, 0], [255, 0, 0, 255], atol=1)


@pytest.mark.parametrize("imported,route,valid", [(True, "plain_pbr", True), (False, "plain_pbr", False),
                                               (True, "builder", False), (True, "invalid", False)])
def test_surface_validation_handles_variant_routes(imported, route, valid):
    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.domain.new_item.rules import validate_spec
    from tests.test_new_item_spec import _spec
    variant = VariantAppearance("model.prefab", "model.pac", custom_model=imported, material_route=route,
                                surface_settings=(("Gem", SurfaceEdit(metallic=0)),))
    errors = [issue for issue in validate_spec(_spec(variants=(variant,))) if issue.code == "surface_settings.invalid"]
    assert bool(errors) is not valid


def test_editor_preserves_per_part_values_and_restores_source(tmp_path):
    from cdmw.modding.scene_importer import import_scene_mesh_with_report
    app = QApplication.instance() or QApplication([])
    scene = import_scene_mesh_with_report(write_gltf(tmp_path, [{"name": "Gem", "emissiveFactor": [1, 0, 0]}, {"name": "Blade"}], []))
    editor = SurfaceEditor()
    changes = []
    editor.changed.connect(changes.append)
    editor.refresh((("Gem", "Gem"), ("Blade", "Blade")), (), enabled=True, mesh=scene.mesh)
    editor.setChecked(True)
    editor.match_glow.click()
    editor.preset.setCurrentIndex(1)
    assert changes[-1] == (("Gem", SurfaceEdit((1, 0, 0), 0.9, 0)),)
    editor.part.setCurrentIndex(1)
    assert not editor.colour_enabled.isChecked()
    assert not editor.fields[0][0].isChecked()
    editor.part.setCurrentIndex(0)
    assert editor.colour_enabled.isChecked() and editor.fields[0][1].value() == 0.9
    editor.setChecked(False)
    assert changes[-1] == ()
    editor.setChecked(True)
    assert changes[-1][0][1].metallic == 0
    editor.reset.click()
    assert changes[-1] == ()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_variant_build_and_top_level_plan_apply_the_surface(tmp_path, monkeypatch):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_variants import prepare_variant_models
    from tests.test_new_item_provenance import setup_game, spec
    from tests.test_new_item_variant_authoring import selections
    from tests.test_translucency_surface import source_files
    service, snapshot, _ = setup_game(tmp_path)
    files = source_files()
    choices = (("Blade", SurfaceEdit((1, 0, 0), 0.9, 0)),)
    appearance = replace(selections(snapshot)[0], custom_model=True, surface_settings=choices)
    monkeypatch.setattr("cdmw.services.new_item_variants.validate_variant_rig", lambda *_args, **_kwargs: None)
    output = prepare_variant_models(replace(spec(), variants=(appearance,)), snapshot, {appearance.identity: files}, {})
    part = _wrappers(output[appearance.identity])[0]
    assert pixels(output[appearance.identity], part, "_materialTexture")[0, 0, 2] == 0
    captured = Mock(wraps=apply_surface_settings)
    monkeypatch.setattr("cdmw.services.new_item_surface.apply_surface_settings", captured)
    service.plan(replace(spec(), model_source=ModelSource.IMPORTED, surface_settings=choices), snapshot, model=files)
    assert captured.call_args.args[1] == choices
