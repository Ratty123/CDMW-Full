"""Layered glass (SkinnedMeshGlass) and net veil (SkinnedMeshTransparency) experiments.

Values mirror the shipped sidecars decoded on 2026-10-31: the visor glass of
cd_phm_00_hel_00_0501 and the veil of cd_phw_00_hel_00_0219.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.material_shader_controls import control_material_sources, equipment_shader_options, rewrite_shader_controls
from cdmw.domain.mesh.shader_controls import (BLENDED_FAMILIES, MESH_FAMILIES, NEW_ITEM_FAMILIES, ShaderControls,
                                             catalogue_payload, preview_factors)
from cdmw.services.shader_controls_preview import authored_blended_factors, shader_control_diagnostic
from tests.test_shader_controls import material, field, choice


VISOR = {"_tintOpacity": "0.267000", "_refractiveIndex": "1.680000", "_roughness": "0.087000",
         "_thickness": "0.191000", "_glassColor": "#eef2efd7"}
VEIL = {"_netPitch": "0.300000", "_netThread": "0.727000", "_glow": "0.516000", "_sheen": "0.901000",
        "_uvScale": "0.270000", "_dyeingColor": "#d9d9d9ff"}


def test_both_families_reach_both_editors_with_field_help():
    shaders = {family.shader for family in BLENDED_FAMILIES}
    assert shaders == {"SkinnedMeshGlass", "SkinnedMeshTransparency"}
    assert shaders <= {family.shader for family in MESH_FAMILIES}
    assert shaders <= {family.shader for family in NEW_ITEM_FAMILIES}
    catalogue = {family["shader"]: family for family in catalogue_payload()}
    for shader in shaders:
        assert all(field_row["note"] for field_row in catalogue[shader]["fields"])
    glass = {row["name"]: row for row in catalogue["SkinnedMeshGlass"]["fields"]}
    assert (glass["_refractiveIndex"]["minimum"], glass["_refractiveIndex"]["maximum"]) == (1, 2.5)


def test_preview_factors_carry_the_authored_values_and_colour_alpha():
    glass = preview_factors(ShaderControls("SkinnedMeshGlass"), VISOR)
    assert glass[:2] == (10., 1.)
    assert glass[4:8] == (.267, .191, .087, 1.68)
    assert glass[8:11] == pytest.approx((0xee / 255, 0xf2 / 255, 0xef / 255))
    assert glass[11] == pytest.approx(0xd7 / 255)
    veil = preview_factors(ShaderControls("SkinnedMeshTransparency"), VEIL)
    assert veil[:2] == (11., 1.)
    assert veil[4:9] == (.3, .727, .516, .901, .27)
    assert veil[9:12] == pytest.approx((0xd9 / 255,) * 3)
    assert veil[12] == 1.
    # Unauthored conversions inherit the material definition defaults.
    assert preview_factors(ShaderControls("SkinnedMeshGlass"))[4:12] == (.1, .5, .05, 1.52, 1., 1., 1., 1.)
    # An explicit colour edit replaces RGB only; the source alpha byte survives.
    edited = preview_factors(choice("SkinnedMeshGlass", _glassColor=(1., 0., 0.)), VISOR)
    assert edited[8:12] == pytest.approx((1., 0., 0., 0xd7 / 255))


def test_conversion_accepts_plain_and_glass_sources_and_refuses_layered_ones():
    options = equipment_shader_options(material())["blade"][1]
    assert {"SkinnedMeshGlass", "SkinnedMeshTransparency"} <= set(options)
    translucent = equipment_shader_options(material("SkinnedMeshTranslucent"))["blade"][1]
    assert "SkinnedMeshGlass" in translucent and "SkinnedMeshTransparency" not in translucent
    layered = material("SkinnedMeshStandard", field("_layerBaseColorTexture", "layer.dds", "Texture"))
    assert not {"SkinnedMeshGlass", "SkinnedMeshTransparency"} & set(equipment_shader_options(layered)["blade"][1])
    assert not {"SkinnedMeshGlass", "SkinnedMeshTransparency"} & set(
        equipment_shader_options(material("SkinnedMeshStandard_Ver2"))["blade"][1])


def test_plain_conversion_writes_checked_fields_with_shipped_item_ids():
    controls = choice("SkinnedMeshGlass", _tintOpacity=.4, _glassColor=(.5, .25, 1.))
    after, found = rewrite_shader_controls(material(), (("Blade", controls),))
    assert found == {"blade"}
    shader, values, textures = control_material_sources(after)["blade"]
    assert shader == "SkinnedMeshGlass"
    assert values["_tintOpacity"] == "0.4"
    assert values["_glassColor"] == "#8040FFFF"
    assert "_baseColorTexture" in textures
    root = ET.fromstring(after)
    assert root.find('.//MaterialParameterFloat[@_name="_tintOpacity"]').get("ItemID") == "1809591378640894"
    assert root.find('.//MaterialParameterColor[@_name="_glassColor"]').get("ItemID") == "3337232596336638"
    # Unchecked fields are not written; the game default applies.
    assert "_refractiveIndex" not in values
    veil, _ = rewrite_shader_controls(material(), (("Blade", choice("SkinnedMeshTransparency", _netThread=.9)),))
    shader, values, _ = control_material_sources(veil)["blade"]
    assert (shader, values["_netThread"]) == ("SkinnedMeshTransparency", "0.9")


def test_editing_shipped_glass_keeps_colour_alpha_and_other_values():
    source = material("SkinnedMeshGlass", "".join(
        field(name, value, "Color" if name == "_glassColor" else "Float") for name, value in VISOR.items()))
    after, _ = rewrite_shader_controls(source, (("Blade", choice("SkinnedMeshGlass", _glassColor=(1., 1., 1.))),))
    values = control_material_sources(after)["blade"][1]
    assert values["_glassColor"] == "#FFFFFFd7"
    assert {name: values[name] for name in VISOR if name != "_glassColor"} == {
        name: value for name, value in VISOR.items() if name != "_glassColor"}


def test_archive_parts_of_both_families_preview_blended_without_an_experiment():
    def part(shader, values):
        return SimpleNamespace(preview_sidecar_shader_family=shader, preview_material_texture_inputs=(),
                               preview_material_parameters=tuple(SimpleNamespace(parameter_name=name, value=value)
                                                                 for name, value in values.items()))
    assert authored_blended_factors(part("SkinnedMeshGlass", VISOR))[:6] == (10., 1., 0., 0., .267, .191)
    assert authored_blended_factors(part("SkinnedMeshTransparency", VEIL))[:5] == (11., 1., 0., 0., .3)
    assert authored_blended_factors(part("SkinnedMeshTranslucent", {})) is None
    assert authored_blended_factors(part("SkinnedMeshStandard_Ver2", {})) is None
    # A shipped value outside the editable range is clamped for preview, not refused.
    assert authored_blended_factors(part("SkinnedMeshGlass", {**VISOR, "_refractiveIndex": "3"}))[7] == 2.5
    assert "back faces" in shader_control_diagnostic(None, ShaderControls("SkinnedMeshGlass"), {})


def test_archive_veil_reaches_the_rust_material_presentation():
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.mesh_rust_authoring import _mesh_material_presentations
    veil = SubMesh(name="cd_phw_00_hel_00_0219", material="cd_phw_00_hel_00_0219",
                   vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)])
    veil.preview_sidecar_shader_family = "SkinnedMeshTransparency"
    veil.preview_material_parameters = tuple(SimpleNamespace(parameter_name=name, value=value) for name, value in VEIL.items())
    rows = _mesh_material_presentations(ParsedMesh(path="character/model/veil.pac", format="pac", submeshes=[veil]))
    assert rows[0]["shader_controls"][0] == 11
    assert rows[0]["translucency"] is None


def test_new_item_editor_offers_layered_glass_with_field_help():
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    editor = ShaderControlsEditor()
    events = []
    editor.changed.connect(events.append)
    try:
        editor.refresh((("Blade", "Blade"),), (), equipment_shader_options(material("SkinnedMeshHair")))
        index = editor.family.findData("SkinnedMeshGlass")
        assert index > 0 and not editor.family.model().item(index).isEnabled()
        assert "existing layered glass" in editor.family.model().item(index).toolTip()
        editor.refresh((("Blade", "Blade"),), (), equipment_shader_options(material()))
        index = editor.family.findData("SkinnedMeshGlass")
        assert editor.family.model().item(index).isEnabled()
        editor.family.setCurrentIndex(index)
        assert events[-1] == (("Blade", ShaderControls("SkinnedMeshGlass")),)
        rows = {field_def.name: (enabled, spins) for field_def, enabled, spins in editor._rows}
        enabled, spins = rows["_tintOpacity"]
        assert "0 clear, 1 solid" in enabled.toolTip()
        enabled.setChecked(True)
        spins[0].setValue(.6)
        assert events[-1] == (("Blade", choice("SkinnedMeshGlass", _tintOpacity=.6)),)
        assert len(rows["_glassColor"][1]) == 3
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()
