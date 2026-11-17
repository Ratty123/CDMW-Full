"""Force replace: any equipment material becomes the net veil or layered glass.

The user wants a cloth (or any) material turned into a transparent one even when
its look comes from layers the target shader cannot read. The source checks and
the appearance bake are skipped; the rebuild writes the target's own rows and
keeps only the source textures the user leaves in.
"""
from dataclasses import replace
from unittest.mock import patch

import pytest

from cdmw.core.material_shader_controls import control_material_sources, rewrite_shader_controls
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.shader_controls import SHADER_LAYOUTS, ShaderControls, catalogue_payload
from cdmw.services.mesh_shader_controls import build_shader_control_files
from cdmw.services.new_item_shader_controls import apply_shader_controls
from tests.test_layered_glass_controls import XML, layered_source, mesh_state, texture

CLOTH = (
    '<root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material Name="_resourceMaterial" '
    '_materialName="SkinnedMeshCloth_Ver2"><Vector Name="_permutations"><MaterialParameterUint StringItemID="Cloth" '
    'ItemID="42" _name="Cloth" Index="0"/></Vector><Vector Name="_parameters">'
    + texture("_baseColorTexture", "character/texture/shirt.dds")
    + texture("_normalTexture", "character/texture/shirt_n.dds")
    + texture("_heightTexture", "character/texture/shirt_disp.dds")
    + texture("_detailDiffuseMaskR", "character/texture/shirt_lace.dds")
    + '<MaterialParameterString StringItemID="_clothCategory" ItemID="77" _name="_clothCategory" _value="Silk" Index="4"/>'
    '<MaterialParameterFloat StringItemID="_sheen" ItemID="78" _name="_sheen" _value="0.6" Index="5"/>'
    '</Vector></Material></SkinnedMeshMaterialWrapper>'
    '<SkinnedMeshMaterialWrapper _subMeshName="Handle"><Material Name="_resourceMaterial" _materialName="SkinnedMeshCloth">'
    '<Vector Name="_permutations"/><Vector Name="_parameters">'
    + texture("_baseColorTexture", "character/texture/handle.dds")
    + '</Vector></Material></SkinnedMeshMaterialWrapper></root>')
VEIL = ("_netPitch", (0.2,))


def forced(shader="SkinnedMeshTransparency", values=(VEIL,), **kwargs):
    return ShaderControls(shader, values, rebuild=True, force=True, **kwargs)


def test_a_cloth_material_is_refused_without_force_and_replaced_with_it():
    with pytest.raises(ValueError):
        rewrite_shader_controls(CLOTH, (("Blade", ShaderControls("SkinnedMeshTransparency", (VEIL,), rebuild=True)),))
    edited, _ = rewrite_shader_controls(CLOTH, (("Blade", forced()),))
    blade, handle = find_material_wrappers(edited)
    assert blade.shader == "SkinnedMeshTransparency" and float(blade.value("_netPitch")) == pytest.approx(0.2)
    # Only the veil's own rows remain; the source's textures carry over where the veil has a slot.
    shader, values, textures = control_material_sources(edited)["blade"]
    names = {name for _kind, name, _id, _default in SHADER_LAYOUTS["SkinnedMeshTransparency"]}
    assert (set(values) | set(textures)) - {"AlphaTest"} <= names
    assert textures["_baseColorTexture"].endswith("shirt.dds") and textures["_heightTexture"].endswith("shirt_disp.dds")
    assert "_clothCategory" not in edited and "_detailDiffuseMaskR" not in edited[:edited.index("Handle")]
    assert 'StringItemID="Cloth"' not in edited and 'StringItemID="AlphaTest"' in edited
    # The other part is untouched.
    assert edited[edited.index('_subMeshName="Handle"'):] == CLOTH[CLOTH.index('_subMeshName="Handle"'):]


def test_left_out_textures_take_the_layout_default_or_no_row():
    edited, _ = rewrite_shader_controls(CLOTH, (("Blade", forced(dropped_textures=("_heightTexture", "_normalTexture"))),))
    textures = control_material_sources(edited)["blade"][2]
    assert "_heightTexture" not in textures and "_normalTexture" not in textures
    assert textures["_baseColorTexture"].endswith("shirt.dds")
    glass, _ = rewrite_shader_controls(CLOTH, (("Blade", forced("SkinnedMeshGlass", (("_tintOpacity", (0.3,)),),
                                                                  dropped_textures=("_heightTexture",))),))
    blade, _ = find_material_wrappers(glass)
    assert blade.shader == "SkinnedMeshGlass" and float(blade.value("_tintOpacity")) == pytest.approx(0.3)
    assert "_heightTexture" not in blade.textures and blade.textures["_normalTexture"].endswith("shirt_n.dds")


@pytest.mark.parametrize("bad", [
    dict(force=True),                                            # Force needs the shader's own rows.
    dict(rebuild=True, dropped_textures=("_baseColorTexture",)),  # The base colour always stays.
    dict(rebuild=True, dropped_textures=("_unknown",)),
    dict(dropped_textures=("_heightTexture",)),                  # Leaving rows out is a rebuild.
    dict(rebuild=True, dropped_textures=("_heightTexture", "_heightTexture")),
])
def test_invalid_force_settings_are_refused(bad):
    with pytest.raises(ValueError):
        ShaderControls("SkinnedMeshTransparency", **bad).validate()
    with pytest.raises(ValueError):
        ShaderControls("SkinnedMeshTranslucent", rebuild=True, force=True).validate()  # No known layout.


def test_force_survives_a_round_trip_and_the_catalogue_lists_droppable_textures():
    value = forced(dropped_textures=("_heightTexture",))
    assert ShaderControls.from_dict(value.to_dict()) == value
    assert value.to_dict()["force"] is True and value.to_dict()["dropped_textures"] == ["_heightTexture"]
    assert "force" not in ShaderControls("SkinnedMeshTransparency").to_dict()
    veil = next(f for f in catalogue_payload() if f["shader"] == "SkinnedMeshTransparency")
    assert [name for name, _label in veil["layout_textures"]] == ["_normalTexture", "_materialTexture", "_heightTexture"]


@pytest.mark.parametrize("route", ["mesh", "prepared_import"])
def test_a_layered_ver2_material_is_replaced_directly_without_the_bake(route):
    files = layered_source("SkinnedMeshStandard_Ver2")
    before = dict(files.side_files)
    choice = forced()
    with patch("cdmw.services.new_item_template_materials._bake_material_maps",
               side_effect=AssertionError("force replace must not bake")):
        if route == "mesh":
            mesh, state = mesh_state(files)
            state = replace(state, parts=(replace(state.parts[0], shader_controls=choice), state.parts[1]))
            side = {file.path: file.data for file in build_shader_control_files(state, mesh, ())}
        else:
            side = apply_shader_controls(files, (("Blade", choice),)).side_files
    blade, _ = find_material_wrappers(side[XML].decode())
    assert blade.shader == "SkinnedMeshTransparency"
    # The source base colour is kept as it is (no baked texture).
    assert blade.textures["_baseColorTexture"] == "character/texture/glass_base.dds"
    assert "_detailDiffuseMaskR" not in blade.textures and files.side_files == before


def _preview_part(shader, values):
    from types import SimpleNamespace
    part = SimpleNamespace(name="cloth_part", material="cloth_part", preview_sidecar_shader_family=shader)
    part.preview_material_parameters = tuple(SimpleNamespace(parameter_name=key, value=value) for key, value in values.items())
    part.preview_material_texture_inputs = (
        SimpleNamespace(parameter_name="_baseColorTexture", source_texture_path="character/texture/cloth_part.dds",
                        material_parameters=(), shader_family=shader),)
    return part


def _panel_row(part, static=False):
    from types import SimpleNamespace
    from cdmw.services.mesh_shader_controls import _shader_source_options
    mesh = SimpleNamespace(submeshes=[part])
    session = SimpleNamespace(replacement_state=None, mesh_format="pam" if static else "pac", working_mesh=mesh, base_mesh=mesh)
    return _shader_source_options(session)[0]


def test_the_panel_offers_force_only_for_known_equipment_sources_and_previews_it_live():
    row = _panel_row(_preview_part("SkinnedMeshCloth_Ver2", {"_dyeingColor": "#808080ff"}))
    # The source checks refuse the veil, but force replace may still apply it.
    assert row["shader_options"]["SkinnedMeshTransparency"]
    assert row["forceable"] == {shader: shader in SHADER_LAYOUTS for shader in row["forceable"]}
    # A forced shader previews while its sliders move; other refused shaders do not.
    assert "SkinnedMeshTransparency" in row["preview_base"] and "SkinnedMeshGlass" in row["preview_base"]
    assert "Dissolve" not in row["preview_base"]
    # No source shader, or a world object: nothing to force.
    assert not any(_panel_row(_preview_part("", {}))["forceable"].values())
    assert not any(_panel_row(_preview_part("Standard", {}), static=True)["forceable"].values())
