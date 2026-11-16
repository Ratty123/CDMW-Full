"""The November 2026 net veil: thread width from the base and detail heights, as the game shader reads them.

Values are the two net wrappers of cd_phw_00_hel_00_0219 after the patch
(decoded 2026-11-16) and the cloth wrapper before it. The formula is the
shipped pixel shader's (DXIL variant ..._151cd770):
thread = _netThread * 0.0003 * (Hbase + Hdetail) * _screenSpaceDisplacementScale.
"""
import math
from types import SimpleNamespace

import pytest

from cdmw.core.material_shader_controls import control_material_sources, rewrite_shader_controls
from cdmw.domain.mesh.shader_controls import (ShaderControls, preview_factors, veil_layer_factors, veil_layer_inputs,
                                             veil_layer_texture)
from cdmw.services.shader_controls_preview import authored_blended_factors, authored_veil_layer_textures

TEXTURE = "character/texture/"
CLOTH_VALUES = {"_dyeingPropertyBlend": "2139062016", "_colorBlendingFlag": "13", "_dyeingGlobalOpacity": "16777215",
                "_dyeingTransformProperty0": "11565", "_detailScreenSpaceDisplacementScale": "1.732051",
                "_netPitch": "0.142000", "_netThread": "0.275000", "_glow": "0.516000", "_sheen": "0.901000"}
CLOTH_TEXTURES = {"_normalTexture": TEXTURE + "cd_phw_00_hel_00_0219_n.dds",
                  "_heightTexture": TEXTURE + "cd_phw_00_hel_00_0219_02_disp.dds",
                  "_colorBlendingMaskTexture": TEXTURE + "temp_r.dds",
                  "_detailDiffuseMaskR": TEXTURE + "cd_phw_00_hel_00_0219.dds",
                  "_detailHeightMaskR": TEXTURE + "cd_phw_00_hel_00_0219_disp.dds"}
PART_01_VALUES = {"_dyeingPropertyBlend": "2139062016", "_colorBlendingFlag": "13", "_dyeingGlobalOpacity": "16777215",
                  "_netPitch": "0.204000", "_netThread": "1.000000", "_glow": "0.773000", "_sheen": "0.551000"}
BEFORE = {"_netPitch": "0.300000", "_netThread": "0.727000", "_glow": "0.516000", "_sheen": "0.901000",
          "_uvScale": "0.270000", "_dyeingColor": "#d9d9d9ff"}
BEFORE_TEXTURES = {"_baseColorTexture": TEXTURE + "cd_phw_00_hel_00_0219.dds",
                   "_heightTexture": TEXTURE + "cd_phw_00_hel_00_0219_disp.dds", "_maskTexture": TEXTURE + "Temp_r.dds"}
VEIL = "SkinnedMeshTransparency"


def factors(values, textures):
    return preview_factors(ShaderControls(VEIL), {**values, **veil_layer_inputs(VEIL, values, textures)})


def test_the_patched_cloth_lays_out_its_detail_layer_lanes():
    layers = veil_layer_inputs(VEIL, CLOTH_VALUES, CLOTH_TEXTURES)
    assert layers == {"_cdmwVeilLayers": "r", "_cdmwVeilLayerMask": "1"}
    assert veil_layer_texture(layers, CLOTH_TEXTURES).endswith("cd_phw_00_hel_00_0219_disp.dds")
    result = factors(CLOTH_VALUES, CLOTH_TEXTURES)
    assert result[:8] == pytest.approx((11.0, 1.0, 0.0, 0.0, 0.142, 0.275, 0.516, 0.901))
    # On, displacement 1 (no row), detail displacement, opacity x mask, scale, offset, half turn, overlay alpha.
    assert result[13:23] == pytest.approx((1.0, 1.0, 1.732051, 1.0, 45 / 255, 45 / 255, 0.0, 0.0, -math.pi, 1.0))
    assert len(result) == 32 and result[23:30] == (0.0,) * 7


def test_the_01_part_has_the_layer_but_no_detail_displacement():
    result = factors(PART_01_VALUES, {**CLOTH_TEXTURES, "_detailHeightMaskR": TEXTURE + "cd_phw_00_hel_00_0219_01_disp.dds"})
    assert result[13:23] == pytest.approx((1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, -math.pi, 1.0))


def test_the_veil_before_the_patch_and_other_shaders_are_unchanged():
    assert veil_layer_inputs(VEIL, BEFORE, BEFORE_TEXTURES) == {}
    result = factors(BEFORE, BEFORE_TEXTURES)
    assert result[:13] == pytest.approx((11.0, 1.0, 0.0, 0.0, 0.3, 0.727, 0.516, 0.901, 0.27, 217 / 255, 217 / 255, 217 / 255, 1.0))
    assert result[13:] == (0.0,) * 19
    # The same rows on another shader never switch the veil lanes on.
    assert veil_layer_inputs("SkinnedMeshGlass", CLOTH_VALUES, CLOTH_TEXTURES) == {}
    glass = preview_factors(ShaderControls("SkinnedMeshGlass"), CLOTH_VALUES)
    assert glass[0] == 10.0 and glass[12:] == (0.0,) * 20


@pytest.mark.parametrize("values, textures, expected", [
    # Definition defaults for absent rows: opacity 0, rotation byte 128.
    ({"_colorBlendingFlag": "13"}, {"_detailHeightMaskR": "a.dds"},
     (1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 128 / 255 * 2 * math.pi - math.pi, 1.0)),
    # The mask texture names the channel; G takes its own transform, opacity byte and rotation byte.
    ({"_dyeingGlobalOpacity": str(128 << 8), "_dyeingTransformProperty1": str(51 | 102 << 8 | 26 << 16 | 13 << 24),
      "_dyeingPropertyBlend": str(191 << 8), "_screenSpaceDisplacementScale": "0.5", "_detailScreenSpaceDisplacementScale": "0.25"},
     {"_colorBlendingMaskTexture": "character/texture/Temp_G.dds", "_detailHeightMaskR": "r.dds", "_detailHeightMaskG": "g.dds",
      "_overlayColorTexture": "texture/nonetexture0x80ffffff.dds"},
     (1.0, 0.5, 0.25, 128 / 255, 0.2, 0.4, 26 / 255, 13 / 255, 191 / 255 * 2 * math.pi - math.pi, 128 / 255)),
])
def test_rows_are_decoded_per_channel_with_the_definitions_defaults(values, textures, expected):
    layers = veil_layer_inputs(VEIL, values, textures)
    assert veil_layer_factors({**values, **layers}) == pytest.approx(expected)
    if "_detailHeightMaskG" in textures:
        assert veil_layer_texture(layers, textures) == "g.dds"


def reference_thread(net_thread, base_height, detail_height, lanes, uv=(0.5, 0.5), back=False, spacing=1.0):
    """The shader's thread width and detail UV, written out from the DXIL."""
    _, displacement, detail_scale, gain, scale_x, scale_y, offset_x, offset_y, angle, _ = lanes
    qx = (uv[0] - 0.5 - offset_x) / scale_x
    qy = (uv[1] - 0.5 + offset_y) / scale_y
    detail_uv = (qx * math.cos(angle) - qy * math.sin(angle) + 0.5, qx * math.sin(angle) + qy * math.cos(angle) + 0.5)
    width = net_thread * 0.0003 * (base_height + gain * detail_height * detail_scale) * displacement
    return min(width * (4 if back else 1), spacing), detail_uv


def test_the_formula_the_lanes_feed():
    lanes = factors(CLOTH_VALUES, CLOTH_TEXTURES)[13:23]
    width, detail_uv = reference_thread(0.275, 0.5, 1.0, lanes, uv=(0.6, 0.3))
    assert width == pytest.approx(0.275 * 0.0003 * (0.5 + 1.732051))
    # A half turn at 5.67 repeats: the offset from the centre is mirrored and scaled.
    assert detail_uv == pytest.approx((0.5 - 0.1 * 255 / 45, 0.5 + 0.2 * 255 / 45))
    assert reference_thread(0.275, 0.5, 1.0, lanes, back=True)[0] == pytest.approx(4 * width)
    assert reference_thread(0.275, 0.5, 1.0, lanes, back=True, spacing=1e-4)[0] == 1e-4
    # No opacity, or no detail displacement, leaves the base height alone.
    without = veil_layer_factors({"_cdmwVeilLayers": "r", "_detailScreenSpaceDisplacementScale": "1.7"})
    assert reference_thread(0.275, 0.5, 1.0, without)[0] == pytest.approx(0.275 * 0.0003 * 0.5)
    # A quarter turn and a Y offset follow u' = qx cos - qy sin, v' = qx sin + qy cos with qy = v - 0.5 + Oy.
    quarter = (1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.25, math.pi / 2, 1.0)
    assert reference_thread(1.0, 0.0, 0.0, quarter, uv=(0.75, 0.5))[1] == pytest.approx((0.25, 0.75))


def veil_part(values, textures, owner=2):
    part = SimpleNamespace(name="cd_phw_00_hel_00_0219", material="cd_phw_00_hel_00_0219",
                           preview_sidecar_shader_family=VEIL, preview_pac_material_owner_slot_index=owner)
    part.preview_material_parameters = ()
    parameters = tuple(SimpleNamespace(parameter_name=key, value=value) for key, value in values.items())
    part.preview_material_texture_inputs = tuple(
        SimpleNamespace(parameter_name=name, source_texture_path=path, source_dds_path="", preview_texture_path="",
                        material_parameters=parameters, shader_family=VEIL, owner_slot_index=owner,
                        binding_authority="authoritative")
        for name, path in textures.items())
    return part


def test_an_archive_part_gets_the_same_lanes_and_its_two_height_textures():
    part = veil_part(CLOTH_VALUES, CLOTH_TEXTURES)
    assert authored_blended_factors(part) == factors(CLOTH_VALUES, CLOTH_TEXTURES)
    height, detail = authored_veil_layer_textures(part)
    assert height.source_texture_path.endswith("0219_02_disp.dds")
    assert detail.source_texture_path.endswith("0219_disp.dds") and detail.parameter_name == "_detailHeightMaskR"
    # Another wrapper's rows on the same part are not this part's.
    other = SimpleNamespace(parameter_name="_heightTexture", source_texture_path="other.dds", source_dds_path="",
                            preview_texture_path="", material_parameters=(), shader_family=VEIL, owner_slot_index=0,
                            binding_authority="authoritative")
    part.preview_material_texture_inputs = (other, *part.preview_material_texture_inputs)
    assert authored_veil_layer_textures(part)[0].source_texture_path.endswith("0219_02_disp.dds")
    assert authored_veil_layer_textures(veil_part(BEFORE, BEFORE_TEXTURES)) == (None, None)
    glass = veil_part(CLOTH_VALUES, CLOTH_TEXTURES)
    glass.preview_sidecar_shader_family = "SkinnedMeshGlass"
    assert authored_veil_layer_textures(glass) == (None, None)


def texture_row(name, item_id, index, path):
    return (f'<MaterialParameterTexture StringItemID="{name}" ItemID="{item_id}" _name="{name}" Index="{index}">'
            f'<ResourceReferencePath_ITexture Name="_value" _path="character/texture/{path}"/></MaterialParameterTexture>')


LAYERED_VEIL = (
    '<SkinnedMeshMaterialWrapper ItemID="848" _subMeshName="veil">'
    '<Material Name="_resourceMaterial" _materialName="SkinnedMeshTransparency">'
    '<Vector Name="_permutations"><MaterialParameterUint StringItemID="AlphaTest" ItemID="1921855275401214" '
    '_name="AlphaTest" Index="0"/></Vector><Vector Name="_parameters">'
    + texture_row("_heightTexture", "4", 0, "cd_phw_00_hel_00_0219_02_disp.dds")
    + texture_row("_detailHeightMaskR", "9", 1, "cd_phw_00_hel_00_0219_disp.dds")
    + '<MaterialParameterUint StringItemID="_colorBlendingFlag" ItemID="11" _name="_colorBlendingFlag" _value="13" Index="2"/>'
    '<MaterialParameterFloat StringItemID="_netPitch" ItemID="2027176113209342" _name="_netPitch" _value="0.142000" Index="3"/>'
    '<MaterialParameterFloat StringItemID="_netThread" ItemID="3127355417559038" _name="_netThread" _value="0.275000" Index="4"/>'
    '</Vector></Material></SkinnedMeshMaterialWrapper>')
EDITS = (("_netPitch", (0.2,)), ("_uvScale", (0.27,)), ("_dyeingColor", (0.5, 0.5, 0.5)))


def test_the_writer_does_not_add_the_rows_the_patched_veil_no_longer_reads():
    edited, _ = rewrite_shader_controls(LAYERED_VEIL, (("veil", ShaderControls(VEIL, EDITS)),))
    _, values, textures = control_material_sources(edited)["veil"]
    assert values["_netPitch"].startswith("0.2")
    assert "_uvScale" not in values and "_dyeingColor" not in values
    assert textures["_detailHeightMaskR"].endswith("0219_disp.dds")
    assert veil_layer_inputs(VEIL, values, textures)


def test_the_veil_before_the_patch_still_takes_both_rows():
    before = LAYERED_VEIL.replace(texture_row("_detailHeightMaskR", "9", 1, "cd_phw_00_hel_00_0219_disp.dds"), "").replace(
        '<MaterialParameterUint StringItemID="_colorBlendingFlag" ItemID="11" _name="_colorBlendingFlag" _value="13" Index="2"/>', "")
    edited, _ = rewrite_shader_controls(before, (("veil", ShaderControls(VEIL, EDITS)),))
    _, values, _ = control_material_sources(edited)["veil"]
    assert values["_uvScale"].startswith("0.27") and values["_dyeingColor"].casefold().startswith("#808080")


def test_the_composed_graph_leaves_a_net_veils_detail_height_to_the_renderer(tmp_path):
    """Blended over the base height it replaced the thread map; the game adds it instead."""
    from cdmw.services.mesh_rust_preview_package import _copy_preview_core_material_layers

    def batch(parameters):
        return [{"index": 0, "material_name": "veil", "material_layers": [
            {"layer_role": "base", "mask_channel": "", "owner_wrapper_item_id": "848", "material_wrapper_index": 2},
            {"layer_role": "detail", "mask_channel": "r", "owner_wrapper_item_id": "848", "material_wrapper_index": 2,
             "source_parameter": "_detailHeightMaskR", "mask_parameter": "_colorBlendingMaskTexture",
             "height_source": "missing_disp.dds", "height_archive_path": "character/texture/missing_disp.dds"}],
            "material_inputs": [{"owner_wrapper_item_id": "848", "material_parameters": parameters}]}]

    veil = [{"parameter_name": "_netPitch", "value": "0.142"}, {"parameter_name": "_dyeingTransformProperty0", "value": "11565",
                                                                 "integer_value": 11565}]
    # Preview Core packages keep the inputs under dds_textures (the reopen path); a batch may carry them on top.
    nested = batch(veil)
    nested[0]["dds_textures"] = {"material_inputs": nested[0].pop("material_inputs")}
    for batches in (batch(veil), nested):
        materials = []
        _copy_preview_core_material_layers(batches, tmp_path, tmp_path, "metadata", {}, 0, 0, {}, materials, 0, None, None)
        detail = materials[0]["layers"][1]
        assert detail["height"] is None and detail["height_declared"] is False
        assert detail["uv_transform"][0] == pytest.approx(45 / 255)
    # Any other material still resolves its detail height (here: fails on the missing file).
    with pytest.raises(ValueError, match="missing"):
        _copy_preview_core_material_layers(batch([{"parameter_name": "_roughness", "value": "1"}]), tmp_path, tmp_path,
                                           "metadata", {}, 0, 0, {}, [], 0, None, None)


def test_the_editor_gets_the_veils_own_height_map_and_its_detail_height_texture(tmp_path):
    """On every open path: the composed height (lace blended over the folds) is not what the shader reads."""
    from unittest.mock import patch

    import cdmw.services.mesh_rust_authoring as authoring
    from cdmw.models import PreviewMaterialTextureInput

    session_root = tmp_path / "session"
    session_root.mkdir()
    files = {}
    for name in ("folds", "lace", "composed"):
        files[name] = tmp_path / f"{name}.dds"
        files[name].write_bytes(b"DDS " + name.encode())
    parameters = tuple(SimpleNamespace(parameter_name=key, value=value) for key, value in CLOTH_VALUES.items())

    def texture_input(name, path, source):
        return PreviewMaterialTextureInput(parameter_name=name, source_texture_path=source, source_dds_path=str(path),
                                           owner_slot_index=2, binding_authority="authoritative", shader_family=VEIL,
                                           material_parameters=parameters)

    def payloads(textures, synthesized):
        submesh = SimpleNamespace(
            name="veil", material="veil", preview_pac_material_owner_slot_index=2, preview_sidecar_shader_family=VEIL,
            preview_material_parameters=(),
            preview_material_texture_inputs=tuple(texture_input(name, files[key], source)
                                                  for name, (key, source) in textures.items()))
        mesh = SimpleNamespace(path="character/model/veil.pac", lod_levels=[], submeshes=[submesh])
        with patch.object(authoring, "_vortice_material_layer_overrides", return_value={}, create=True), \
                patch.object(authoring, "_mesh_synthesized_texture_overrides", return_value=synthesized):
            rows = authoring._mesh_texture_payloads(session_root, mesh,
                                                    expected_root_identity=authoring._session_root_identity(session_root))
        return {row["role"]: row for row in rows}

    layered = {"_heightTexture": ("folds", CLOTH_TEXTURES["_heightTexture"]),
               "_detailHeightMaskR": ("lace", CLOTH_TEXTURES["_detailHeightMaskR"]),
               "_colorBlendingMaskTexture": ("composed", CLOTH_TEXTURES["_colorBlendingMaskTexture"])}
    sha = lambda name: __import__("hashlib").sha256(files[name].read_bytes()).hexdigest()
    for synthesized in ({}, {(0, 0, "height"): files["composed"]}):
        rows = payloads(layered, synthesized)
        assert rows["height"]["file"]["sha256"].casefold() == sha("folds")
        assert rows["shader_mask"]["file"]["sha256"].casefold() == sha("lace")
        assert rows["shader_mask"]["material_indices_by_lod"] == [[0]]
    # The veil before the patch: no detail texture, and a composed height stays in use.
    before = {"_heightTexture": ("folds", BEFORE_TEXTURES["_heightTexture"])}
    parameters = tuple(SimpleNamespace(parameter_name=key, value=value) for key, value in BEFORE.items())
    rows = payloads(before, {(0, 0, "height"): files["composed"]})
    assert "shader_mask" not in rows and rows["height"]["file"]["sha256"].casefold() == sha("composed")


def test_an_archive_part_bound_by_extracted_files_alone_still_gets_its_detail_texture():
    """The Archive Browser's model can carry only the extracted DDS path of a texture
    (the first open of the patched veil did): the layer must still be found."""
    part = veil_part(CLOTH_VALUES, CLOTH_TEXTURES)
    for item in part.preview_material_texture_inputs:
        name = item.source_texture_path.rsplit("/", 1)[-1]
        item.source_dds_path, item.source_texture_path = f"C:/cache/a5793a90c178ccf0_{name}", ""
    height, detail = authored_veil_layer_textures(part)
    assert height.source_dds_path.endswith("_cd_phw_00_hel_00_0219_02_disp.dds")
    assert detail.parameter_name == "_detailHeightMaskR" and detail.source_dds_path.endswith("_0219_disp.dds")
    assert authored_blended_factors(part)[13:23] == pytest.approx(factors(CLOTH_VALUES, CLOTH_TEXTURES)[13:23])
    # The hashed mask name still names its channel, and a hashed constant overlay its alpha.
    layers = veil_layer_inputs(VEIL, {"_colorBlendingFlag": "13"}, {
        "_colorBlendingMaskTexture": "C:/cache/11_temp_g.dds", "_detailHeightMaskR": "r.dds", "_detailHeightMaskG": "g.dds",
        "_overlayColorTexture": "C:/cache/22_nonetexture0x40ffffff.dds"})
    assert layers["_cdmwVeilLayers"] == "g" and float(layers["_cdmwVeilOverlayAlpha"]) == pytest.approx(64 / 255)
