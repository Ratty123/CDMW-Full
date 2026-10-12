"""Glass authoring through PAMI/PAC output, saved intent and both preview routes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.material_shader_controls import control_material_sources, equipment_shader_options, rewrite_shader_controls
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart
from cdmw.domain.mesh.shader_controls import ShaderControls, catalogue_payload, preview_factors, validate_choices
from cdmw.services.mesh_shader_controls import build_shader_control_files
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.new_item_shader_controls import apply_shader_controls
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.shader_controls_preview import authored_static_glass_factors, shader_preview_groups, shader_preview_mesh
from tests.test_shader_controls import material, field, choice
from tests.test_translucency_surface import source_files, PAC, XML


def pami(shader="Translucent", extra=""):
    return ('<StaticMeshInstance Version="1"><StaticMesh Path="object/window.pam"/><MaterialData>'
            '<Material PrimitiveName="Glass"><Common MaterialName="' + shader + '"/><Permutations/>'
            '<Parameters><MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/colour.dds"/>'
            '<MaterialParameterTexture Name="_normalTexture" Value="object/texture/normal.dds"/>'
            '<MaterialParameterFloat Name="_extinctionCoefficient" Value="10" ItemID="99"/>'
            '<MaterialParameterColor Name="_tintColor" Value="1 0.7 0.8"/>' + extra + '</Parameters></Material>'
            '<Material PrimitiveName="Stone"><Common MaterialName="MultiTextured"/><Parameters/></Material>'
            '</MaterialData></StaticMeshInstance>')


def glass(shader="Translucent", **values):
    return choice(shader, **values)


def test_static_pami_exports_explicit_values_and_preserves_other_materials_and_metadata(tmp_path):
    before = pami()
    controls = glass(_thickness=.02, _extinctionCoefficient=10, _extinctionTint=1)
    file = ReplacementFile("object/window.pami", b"\xff\xfe" + before.encode("utf-16-le"))
    state = MeshReplacementState("object/window.pam", "a" * 64,
        (ReplacementPart("glass", 0, shader_controls=controls), ReplacementPart("stone", 1)), dependencies=(file,))
    original = SimpleNamespace(format="pam", submeshes=[SimpleNamespace(name=name, material=name) for name in ("Glass", "Stone")])
    result, = build_shader_control_files(state, original, ())
    assert result.data.startswith(b"\xff\xfe")
    after = result.data[2:].decode("utf-16-le")
    authored = control_material_sources(after, static=True)
    assert authored["glass"][0] == "Translucent"
    assert authored["glass"][1] == {"_extinctionCoefficient": "10", "_tintColor": "1 0.7 0.8",
                                    "_thickness": "0.02", "_extinctionTint": "1"}
    assert authored["stone"] == control_material_sources(before, static=True)["stone"]
    assert after[after.index('<Material PrimitiveName="Stone"'):] == before[before.index('<Material PrimitiveName="Stone"'):]
    assert ET.fromstring(after).find('.//MaterialParameterFloat[@Name="_extinctionCoefficient"]').get("ItemID") == "99"
    assert state.dependencies == (file,)
    restored = replace(state, parts=tuple(replace(part, shader_controls=None) for part in state.parts))
    assert build_shader_control_files(restored, original, ()) == ()
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = save_replacement_state(state, tmp_path, generation)
    assert load_replacement_state(payload, tmp_path) == state


def test_static_conversion_is_explicit_and_never_crosses_vertex_pipelines():
    controls = glass(_extinctionCoefficient=2)
    output, found = rewrite_shader_controls(pami("Standard"), (("Glass", controls),), static=True)
    assert found == {"glass"}
    assert control_material_sources(output, static=True)["glass"][0] == "Translucent"
    for source in (pami("MultiTextured"), pami("Standard", '<MaterialParameterTexture Name="_layerBaseColorTexture" Value="layer.dds"/>')):
        with pytest.raises(ValueError, match="compatible plain"):
            rewrite_shader_controls(source, (("Glass", controls),), static=True)
    with pytest.raises(ValueError, match="vertex pipelines"):
        rewrite_shader_controls(material(), (("Blade", controls),))
    with pytest.raises(ValueError, match="vertex pipelines"):
        rewrite_shader_controls(pami(), (("Glass", glass("SkinnedMeshTranslucent")),), static=True)
    with pytest.raises(ValueError, match="static object"):
        validate_choices((("Glass", controls),), equipment=True)


@pytest.mark.parametrize("different_absorption", [False, True])
def test_static_variants_reuse_resolved_maps_but_refuse_conflicting_absorption(monkeypatch, tmp_path, different_absorption):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.mesh_shader_controls_preview import stage_shader_preview
    first = pami()
    second = first.replace('Value="1 0.7 0.8"', 'Value="0.5 0 0"').replace('</Parameters>',
        '<MaterialParameterUint Name="_materialFlags" Value="1"/></Parameters>')
    if different_absorption:
        second = second.replace('Value="10"', 'Value="9"')
    part = SubMesh(name="Glass", material="Glass")
    part._cdmw_replacement_part_id = "glass"
    mesh = ParsedMesh(path="object/window.pam", format="pam", submeshes=[part])
    state = MeshReplacementState(mesh.path, "a" * 64, (ReplacementPart("glass", 0, shader_controls=glass(_thickness=.02)),),
        dependencies=(ReplacementFile("object/window.pami", first.encode()), ReplacementFile("object/window_variant.pami", second.encode())))
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_mesh", lambda *_: mesh)
    def publish(_root, bindings, sources, *_):
        assert not bindings and not sources  # Reuse the original prepared maps.
        return []
    monkeypatch.setattr("cdmw.services.mesh_rust_authoring._publish_rust_texture_resources", publish)
    authoring = SimpleNamespace(shadow_service=SimpleNamespace(_session=lambda _: SimpleNamespace(original_data=b"source")),
        shadow_session_id="test", archive_refit_material_cache={}, root=tmp_path, root_identity=None)
    presentations = {(0, 0): {"texture_tint": [1, .7, .8]}}
    payload = {"textures": []}
    if different_absorption:
        with pytest.raises(ValueError, match="separate shader previews"):
            stage_shader_preview(authoring, mesh, state, payload, presentations, None)
    else:
        stage_shader_preview(authoring, mesh, state, payload, presentations, None)
        assert presentations[(0, 0)]["texture_tint"] == [1, .7, .8]
        assert presentations[(0, 0)]["shader_controls"][4:6] == [.02, 10]
        assert "glass" in payload["shader_diagnostics"]


@pytest.mark.parametrize("route", ["template", "prepared_import"])
def test_equipment_glass_exports_through_existing_new_item_routes(route):
    files = source_files()
    before = dict(files.side_files)
    settings = (("Blade", glass("SkinnedMeshTranslucent", _thickness=.2, _extinctionCoefficient=1, _extinctionTint=1)),)
    if route == "template":
        snapshot = SimpleNamespace(payload=lambda path: files.pac_data if path == PAC else files.side_files[path],
                                   has_entry=files.side_files.__contains__)
        output = prepare_template_model(snapshot, (PAC,), shader_controls=settings)
    else:
        output = apply_shader_controls(files, settings)
    text = output.side_files[XML].decode()
    blade, gem = find_material_wrappers(text)
    old_blade, old_gem = find_material_wrappers(before[XML].decode())
    assert blade.shader == "SkinnedMeshTranslucent"
    assert [float(blade.value(name)) for name in ("_thickness", "_extinctionCoefficient", "_extinctionTint")] == [.2, 1, 1]
    assert blade.textures == old_blade.textures
    assert text[gem.start:gem.end] == before[XML].decode()[old_gem.start:old_gem.end]
    assert output.pac_data == files.pac_data
    if route == "prepared_import":
        assert {path: data for path, data in output.side_files.items() if path != XML} == {path: data for path, data in before.items() if path != XML}
    else:
        # Templates retain archive references instead of copying unchanged DDS.
        assert set(output.side_files) == {XML}
    assert files.side_files == before


def test_shadow_only_edit_inherits_equipment_absorption_and_preserves_packed_metadata():
    before = material("SkinnedMeshTranslucent", field("_thickness", ".4") + field("_extinctionCoefficient", ".7") + field("_extinctionTint", "0"))
    controls = glass("SkinnedMeshTranslucent", _extinctionTint=1)
    after, _ = rewrite_shader_controls(before, (("Blade", controls),))
    authored = control_material_sources(after)["blade"][1]
    assert preview_factors(controls, authored)[4:7] == (.4, .7, 1.)
    assert field("_thickness", ".4") in after
    assert field("_extinctionCoefficient", ".7") in after
    tint = ET.fromstring(after).find('.//MaterialParameterFloat[@_name="_extinctionTint"]')
    assert tint.get("ItemID") == "123" and tint.get("Index") == "50"
    with pytest.raises(ValueError):
        glass("SkinnedMeshTranslucent", _extinctionCoefficient=10).validate()
    assert preview_factors(glass(_extinctionCoefficient=10))[5] == 10
    assert "SkinnedMeshTranslucent" in equipment_shader_options(material())["blade"][1]
    assert "SkinnedMeshTranslucent" not in equipment_shader_options(material("SkinnedMeshHair"))["blade"][1]


def test_static_authored_material_reaches_rust_presentation_with_full_extinction():
    from cdmw.services.mesh_rust_authoring import _mesh_material_presentations
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    part = SubMesh(name="Glass", material="Glass", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)])
    part.preview_sidecar_shader_family = "Translucent"
    part.preview_material_parameters = (SimpleNamespace(parameter_name="_extinctionCoefficient", numeric_value=10.),)
    mesh = ParsedMesh(path="object/window.pam", format="pam", submeshes=[part])
    rows = _mesh_material_presentations(mesh)
    assert rows[0]["shader_controls"][0] == 8
    assert rows[0]["shader_controls"][4:7] == (.02, 10., 0.)
    part.preview_sidecar_shader_family = "Standard"
    assert authored_static_glass_factors(part) is None
    part.preview_sidecar_shader_family = "Glass"
    assert authored_static_glass_factors(part) is None


def test_prepared_preview_and_live_groups_use_same_equipment_glass_factors():
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    part = SubMesh(name="Blade", material="Blade", vertices=[(0, 0, 0)], faces=[])
    mesh = ParsedMesh(path="import.obj", format="obj", submeshes=[part])
    controls = glass("SkinnedMeshTranslucent", _thickness=.2, _extinctionCoefficient=1, _extinctionTint=1)
    settings = (("Blade", controls),)
    prepared = shader_preview_mesh(mesh, settings, plain_pbr=True)
    groups = shader_preview_groups(mesh, settings, plain_pbr=True)
    assert groups[0]["shader_controls"] == prepared.submeshes[0].preview_native_material_overrides["shader_controls"]
    assert groups[0]["shader_controls"][:7] == [9., 0., 0., 0., .2, 1., 1.]
    assert not hasattr(part, "preview_native_material_overrides")


def test_new_item_glass_controls_are_reachable_and_emit_only_checked_fields():
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    editor = ShaderControlsEditor()
    events = []
    editor.changed.connect(events.append)
    try:
        editor.refresh((("Blade", "Blade"),), (), equipment_shader_options(material()))
        index = editor.family.findData("SkinnedMeshTranslucent")
        assert index > 0 and editor.family.model().item(index).isEnabled()
        assert editor.family.findData("Translucent") == -1
        editor.family.setCurrentIndex(index)
        assert events[-1] == (("Blade", ShaderControls("SkinnedMeshTranslucent")),)
        for field_def, enabled, spins in editor._rows:
            assert not enabled.isChecked()
            if field_def.name == "_extinctionCoefficient":
                assert spins[0].maximum() == 1
            if field_def.name == "_extinctionTint":
                assert "preview does not show" in enabled.toolTip()
                enabled.setChecked(True)
                spins[0].setValue(1)
        assert events[-1] == (("Blade", glass("SkinnedMeshTranslucent", _extinctionTint=1)),)
        editor.reset.click()
        assert events[-1] == ()
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()
    catalogue = {family["shader"]: family for family in catalogue_payload()}
    assert catalogue["Translucent"]["fields"][1]["maximum"] == 10
    assert catalogue["SkinnedMeshTranslucent"]["fields"][1]["maximum"] == 1
