"""A shader experiment can ship the user's own texture in place of the source's."""
import hashlib
from dataclasses import replace
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cdmw.core import shader_texture_store
from cdmw.core.material_shader_controls import control_material_variants, rewrite_texture_paths
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart
from cdmw.domain.mesh.shader_controls import ShaderControls, catalogue_payload
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_shader_controls import (_with_chosen_textures, build_shader_control_files,
                                                import_shader_texture, owned_texture_path)

MESH = "character/model/1_pc/2_phw/armor/20_mask/cd_phw_01_mask_0271.pac"
SIDECAR = "character/modelproperty/1_pc/2_phw/armor/20_mask/cd_phw_01_mask_0271.pac_xml"
PART = "cd_phm_00_mask_0248"
DDS = b"DDS " + bytes(124) + b"height pixels"


def wrapper(pitch, with_height=True):
    height = ('<MaterialParameterTexture StringItemID="_heightTexture" ItemID="4" _name="_heightTexture" Index="1">'
              '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/veil_disp.dds"/>'
              '</MaterialParameterTexture>') if with_height else ""
    return (f'<SkinnedMeshMaterialWrapper ItemID="508" _subMeshName="{PART}">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshTransparency">'
            '<Vector Name="_permutations"><MaterialParameterUint StringItemID="AlphaTest" ItemID="1921855275401214" '
            '_name="AlphaTest" Index="0"/></Vector><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_baseColorTexture" ItemID="7" _name="_baseColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/veil.dds"/>'
            '</MaterialParameterTexture>' + height +
            f'<MaterialParameterFloat StringItemID="_netPitch" ItemID="2027176113209342" _name="_netPitch" '
            f'_value="{pitch}" Index="5"/></Vector></Material></SkinnedMeshMaterialWrapper>'
            '<SkinnedMeshMaterialWrapper ItemID="509" _subMeshName="trim"><Material Name="_resourceMaterial" '
            '_materialName="SkinnedMeshStandard"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_baseColorTexture" ItemID="7" _name="_baseColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/trim.dds"/>'
            '</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>')


def sidecar(with_height=True):
    return ('<ModelProperty Index="0">' + wrapper("0.300000", with_height) + '</ModelProperty>'
            '<ModelProperty Index="1">' + wrapper("0.334000", with_height) + '</ModelProperty>')


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_SHADER_TEXTURE_STORE", str(tmp_path / "store"))
    return tmp_path / "store"


def state_with(controls):
    file = ReplacementFile(SIDECAR, sidecar().encode("utf-8"))
    state = MeshReplacementState(MESH, "a" * 64, (ReplacementPart("veil", 0, shader_controls=controls),
                                                  ReplacementPart("trim", 1)), dependencies=(file,))
    original = SimpleNamespace(format="pac", submeshes=[SimpleNamespace(name=name, material=name) for name in (PART, "trim")])
    return state, original


def test_store_keeps_a_dds_by_its_hash_and_notices_tampering(store):
    digest = shader_texture_store.store_texture(DDS)
    assert digest == hashlib.sha256(DDS).hexdigest()
    assert shader_texture_store.store_texture(DDS) == digest
    assert shader_texture_store.read_texture(digest) == DDS
    with pytest.raises(ValueError, match="not a DDS"):
        shader_texture_store.store_texture(b"\x89PNG" + bytes(200))
    (store / f"{digest}.dds").write_bytes(DDS + b"x")
    with pytest.raises(ValueError, match="has been changed"):
        shader_texture_store.read_texture(digest)
    with pytest.raises(ValueError, match="no longer on this computer"):
        shader_texture_store.read_texture("0" * 64)
    with pytest.raises(ValueError, match="Invalid"):
        shader_texture_store.read_texture("../" + "0" * 61)


def test_controls_name_replacement_textures_only_for_slots_the_shader_reads():
    digest = "ab" * 32
    controls = ShaderControls("SkinnedMeshTransparency", (("_netPitch", (.3,)),), textures=(("_heightTexture", digest),))
    assert controls.to_dict()["textures"] == {"_heightTexture": digest}
    assert ShaderControls.from_dict(controls.to_dict()) == controls
    assert "textures" not in ShaderControls("SkinnedMeshTransparency").to_dict()
    for bad in ((("_normalTexture", digest),), (("_heightTexture", "XYZ"),),
                (("_heightTexture", digest), ("_heightTexture", digest))):
        with pytest.raises(ValueError, match="replacement texture"):
            ShaderControls("SkinnedMeshTransparency", textures=bad).validate()
    slots = {family["shader"]: [slot["name"] for slot in family["textures"]] for family in catalogue_payload()}
    assert slots["SkinnedMeshTransparency"] == ["_baseColorTexture", "_heightTexture"]
    assert slots["SkinnedMeshGlass"] == ["_baseColorTexture", "_normalTexture"]
    assert slots["SkinnedMeshWing"] == []


def test_texture_paths_change_in_every_variant_and_keep_the_rows_identity():
    text, found = rewrite_texture_paths(sidecar(), {PART: {"_heightTexture": "character/texture/mine.dds"}})
    assert found == {PART}
    for variant in control_material_variants(text):
        assert variant[PART][2]["_heightTexture"] == "character/texture/mine.dds"
        assert variant[PART][2]["_baseColorTexture"] == "character/texture/veil.dds"
        assert variant["trim"][2] == {"_baseColorTexture": "character/texture/trim.dds"}
    rows = ET.fromstring("<r>" + text + "</r>").findall(".//MaterialParameterTexture[@_name='_heightTexture']")
    assert [(row.get("ItemID"), row.get("Index")) for row in rows] == [("4", "1")] * 2
    assert text.count('_value="0.300000"') == 1 and text.count('_value="0.334000"') == 1


def test_missing_texture_row_is_appended_after_the_last_index():
    text, _ = rewrite_texture_paths(sidecar(with_height=False), {PART: {"_heightTexture": "character/texture/mine.dds"}})
    rows = ET.fromstring("<r>" + text + "</r>").findall(".//MaterialParameterTexture[@_name='_heightTexture']")
    assert [row.get("Index") for row in rows] == ["6", "6"]
    assert all(row.find("ResourceReferencePath_ITexture").get("_path") == "character/texture/mine.dds" for row in rows)


def test_build_ships_the_texture_under_its_own_name_and_points_the_material_at_it(store):
    digest = shader_texture_store.store_texture(DDS)
    controls = ShaderControls("SkinnedMeshTransparency", (("_netThread", (.4,)),), textures=(("_heightTexture", digest),))
    state, original = state_with(controls)
    files = {file.path: file.data for file in build_shader_control_files(state, original, ())}
    owned = owned_texture_path(MESH, "_heightTexture", digest)
    assert owned == f"character/texture/1_pc/2_phw/armor/20_mask/cd_phw_01_mask_0271_cdmw_tex_{digest[:10]}_height.dds"
    assert set(files) == {SIDECAR, owned}
    assert files[owned] == DDS
    for variant in control_material_variants(files[SIDECAR].decode("utf-8")):
        shader, values, textures = variant[PART]
        assert shader == "SkinnedMeshTransparency" and values["_netThread"] == "0.4"
        assert textures == {"_baseColorTexture": "character/texture/veil.dds", "_heightTexture": owned}
        assert variant["trim"][2] == {"_baseColorTexture": "character/texture/trim.dds"}
    # The game's own texture file is never part of the output.
    assert "character/texture/veil_disp.dds" not in files
    # A texture alone, with no changed number, is still an edit.
    only, original = state_with(ShaderControls("SkinnedMeshTransparency", textures=(("_baseColorTexture", digest),)))
    assert owned_texture_path(MESH, "_baseColorTexture", digest) in {
        file.path for file in build_shader_control_files(only, original, ())}


def test_build_fails_plainly_when_the_stored_texture_is_gone(store):
    controls = ShaderControls("SkinnedMeshTransparency", textures=(("_heightTexture", "0" * 64),))
    state, original = state_with(controls)
    with pytest.raises(ValueError, match="Choose the texture again"):
        build_shader_control_files(state, original, ())


def test_replacement_texture_survives_a_saved_draft(store, tmp_path):
    digest = shader_texture_store.store_texture(DDS)
    state, _ = state_with(ShaderControls("SkinnedMeshTransparency", textures=(("_heightTexture", digest),)))
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = save_replacement_state(state, tmp_path, generation)
    assert load_replacement_state(payload, tmp_path).parts[0].shader_controls.textures == (("_heightTexture", digest),)


def test_choosing_files_stores_dds_and_an_empty_path_restores_the_source(store, tmp_path):
    source = tmp_path / "my_height.dds"
    source.write_bytes(DDS)
    base = ShaderControls("SkinnedMeshTransparency", (("_netPitch", (.3,)),))
    chosen = _with_chosen_textures(base, {"_heightTexture": str(source)}, None)
    assert chosen.textures == (("_heightTexture", hashlib.sha256(DDS).hexdigest()),)
    assert chosen.values == base.values
    assert _with_chosen_textures(chosen, {"_heightTexture": ""}, None) == base
    assert _with_chosen_textures(chosen, None, None) is chosen
    with pytest.raises(ValueError, match="replacement texture"):
        _with_chosen_textures(base, {"_normalTexture": str(source)}, None)
    with pytest.raises(ValueError, match="does not exist"):
        import_shader_texture(tmp_path / "missing.dds")
    text = tmp_path / "notes.txt"
    text.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="not a DDS or a readable image"):
        import_shader_texture(text)


def test_image_sides_must_be_powers_of_two(tmp_path):
    from PIL import Image
    path = tmp_path / "odd.png"
    Image.new("RGBA", (100, 64)).save(path)
    with pytest.raises(ValueError, match="powers of two"):
        import_shader_texture(path)


# ----------------------------------------------------------------- layout rebuild

from cdmw.core.material_shader_controls import rewrite_shader_controls

STANDARD = (
    '<ModelProperty Index="0"><SkinnedMeshMaterialWrapper ItemID="33" _subMeshName="veil" _jiggleWindWeight="0">\n'
    '\t<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard">\n'
    '\t\t<Vector Name="_permutations"/>\n'
    '\t\t<Vector Name="_parameters">\n'
    '\t\t\t<MaterialParameterTexture StringItemID="_baseColorTexture" ItemID="5" _name="_baseColorTexture" Index="0">'
    '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/mask.dds"/></MaterialParameterTexture>\n'
    '\t\t\t<MaterialParameterTexture StringItemID="_normalTexture" ItemID="4" _name="_normalTexture" Index="1">'
    '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/mask_n.dds"/></MaterialParameterTexture>\n'
    '\t\t\t<MaterialParameterTexture StringItemID="_heightTexture" ItemID="2" _name="_heightTexture" Index="2">'
    '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/mask_disp.dds"/></MaterialParameterTexture>\n'
    '\t\t\t<MaterialParameterFloat StringItemID="_screenSpaceDisplacementScale" ItemID="1" '
    '_name="_screenSpaceDisplacementScale" _value="0.012000" Index="3"/>\n'
    '\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="0" _name="_renderSettingFlag" '
    '_value="6" Index="4"/>\n'
    '\t\t</Vector>\n\t</Material>\n</SkinnedMeshMaterialWrapper></ModelProperty>')


def _rows(text):
    root = ET.fromstring("<r>" + text + "</r>")
    parameters = root.find(".//Vector[@Name='_parameters']")
    return [(row.tag.removeprefix("MaterialParameter"), row.get("_name"), row.get("ItemID"), row.get("Index"),
             row.get("_value") or row.find("ResourceReferencePath_ITexture").get("_path")) for row in parameters]


def test_rebuilt_net_veil_matches_the_shipped_layout_row_for_row():
    controls = ShaderControls("SkinnedMeshTransparency", (("_netPitch", (.3,)), ("_netThread", (.627,))), rebuild=True)
    text, _ = rewrite_shader_controls(STANDARD, [("veil", controls)])
    assert _rows(text) == [
        ("Texture", "_baseColorTexture", "7", "0", "character/texture/mask.dds"),
        ("Texture", "_normalTexture", "6", "1", "character/texture/mask_n.dds"),
        # The source has no material texture, so none is invented.
        ("Texture", "_heightTexture", "4", "2", "character/texture/mask_disp.dds"),
        ("Texture", "_maskTexture", "2", "3", "character/texture/Temp_r.dds"),
        ("Float", "_netPitch", "2027176113209342", "4", "0.3"),
        ("Float", "_netThread", "3127355417559038", "5", "0.627"),
        # Unchanged fields are written with the shader definition's defaults.
        ("Float", "_glow", "2839560803319806", "6", "0.65"),
        ("Float", "_sheen", "403124275642366", "7", "0.22"),
        ("Float", "_uvScale", "2292528656154622", "8", "1"),
        ("Color", "_dyeingColor", "2595737222250494", "9", "#FFFFFFFF"),
    ]
    root = ET.fromstring("<r>" + text + "</r>")
    permutation, = root.find(".//Vector[@Name='_permutations']")
    assert (permutation.tag, permutation.get("_name"), permutation.get("ItemID"), permutation.get("_value")) == (
        "MaterialParameterUint", "AlphaTest", "1921855275401214", None)
    assert root.find(".//Material").get("_materialName") == "SkinnedMeshTransparency"
    # The wrapper itself is untouched.
    assert 'ItemID="33" _subMeshName="veil" _jiggleWindWeight="0"' in text
    assert "_renderSettingFlag" not in text and "_screenSpaceDisplacementScale" not in text


def test_without_rebuild_the_source_rows_stay_as_before():
    controls = ShaderControls("SkinnedMeshTransparency", (("_netPitch", (.3,)),))
    text, _ = rewrite_shader_controls(STANDARD, [("veil", controls)])
    rows = _rows(text)
    assert [row[1:4] for row in rows[:5]] == [
        ("_baseColorTexture", "5", "0"), ("_normalTexture", "4", "1"), ("_heightTexture", "2", "2"),
        ("_screenSpaceDisplacementScale", "1", "3"), ("_renderSettingFlag", "0", "4")]
    assert rows[5][1:] == ("_netPitch", "2027176113209342", "5", "0.3")
    assert '<Vector Name="_permutations"/>' in text


def test_rebuilt_layered_glass_keeps_the_sources_displacement_and_orders_rows_as_the_mod_does():
    controls = ShaderControls("SkinnedMeshGlass", (("_tintOpacity", (.4,)),), rebuild=True)
    text, _ = rewrite_shader_controls(STANDARD, [("veil", controls)])
    assert [row[:4] for row in _rows(text)] == [
        ("Texture", "_baseColorTexture", "7", "0"), ("Texture", "_normalTexture", "6", "1"),
        ("Texture", "_heightTexture", "4", "2"), ("Float", "_screenSpaceDisplacementScale", "3", "3"),
        ("Float", "_tintOpacity", "1809591378640894", "4"), ("Float", "_refractiveIndex", "98498246606846", "5"),
        ("Float", "_roughness", "1406263355244542", "6"), ("Float", "_thickness", "3214133184954366", "7"),
        ("Color", "_glassColor", "3337232596336638", "8")]
    assert dict((row[1], row[4]) for row in _rows(text))["_screenSpaceDisplacementScale"] == "0.012000"


def test_rebuild_is_refused_for_shaders_without_a_known_layout():
    assert ShaderControls.from_dict({"shader": "SkinnedMeshGlass", "values": {}, "rebuild": True}).rebuild
    assert "rebuild" not in ShaderControls("SkinnedMeshGlass").to_dict()
    with pytest.raises(ValueError, match="no known parameter layout"):
        ShaderControls("SkinnedMeshWing", rebuild=True).validate()
    assert {family["shader"] for family in catalogue_payload() if family["rebuild"]} == {
        "SkinnedMeshGlass", "SkinnedMeshTransparency"}


def test_rebuild_numbers_a_texture_row_the_replacement_added(store):
    digest = shader_texture_store.store_texture(DDS)
    source = ReplacementFile(SIDECAR, STANDARD.replace('_subMeshName="veil"', f'_subMeshName="{PART}"').encode("utf-8"))
    controls = ShaderControls("SkinnedMeshTransparency", textures=(("_baseColorTexture", digest),), rebuild=True)
    state = MeshReplacementState(MESH, "a" * 64, (ReplacementPart("veil", 0, shader_controls=controls),),
                                 dependencies=(source,))
    original = SimpleNamespace(format="pac", submeshes=[SimpleNamespace(name=PART, material=PART)])
    files = {file.path: file.data for file in build_shader_control_files(state, original, ())}
    rows = _rows(files[SIDECAR].decode("utf-8"))
    assert rows[0] == ("Texture", "_baseColorTexture", "7", "0", owned_texture_path(MESH, "_baseColorTexture", digest))
    assert [row[1:4] for row in rows[1:4]] == [
        ("_normalTexture", "6", "1"), ("_heightTexture", "4", "2"), ("_maskTexture", "2", "3")]


def _panel(owner_slot):
    """Panel state for the two-variant veil when the viewport drew the wrapper at ``owner_slot``."""
    from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
    from cdmw.services.mesh_shader_controls import _shader_source_options

    state, original = state_with(None)
    parts = []
    for binding, source in zip(state.parts, original.submeshes):
        part = SimpleNamespace(name=source.name, material=source.material)
        setattr(part, PART_ID_ATTRIBUTE, binding.part_id)
        parts.append(part)
    parts[0].preview_pac_material_owner_slot_index = owner_slot
    mesh = SimpleNamespace(submeshes=parts, path=MESH)
    session = SimpleNamespace(replacement_state=state, mesh_format="pac", working_mesh=mesh, base_mesh=mesh)
    return _shader_source_options(session)[0]


def test_source_view_lists_the_wrapper_rows_exactly_as_the_file_writes_them():
    row = _panel(owner_slot=0)
    assert row["source"] == {"path": SIDECAR, "part": PART.casefold(), "viewport_slot": 0}
    first = row["authored"][0]
    assert first["variants"] == ["0"] and first["slot"] == 0
    assert [(item["kind"], item["name"], item["item_id"], item["index"], item["value"]) for item in first["rows"]] == [
        ("Uint", "AlphaTest", "1921855275401214", 0, ""),
        ("Texture", "_baseColorTexture", "7", 0, "character/texture/veil.dds"),
        ("Texture", "_heightTexture", "4", 1, "character/texture/veil_disp.dds"),
        ("Float", "_netPitch", "2027176113209342", 5, "0.300000"),
    ]


def test_the_variant_the_viewport_draws_leads_the_panel():
    # Wrappers in file order: veil(0), trim(1) in Index 0; veil(2), trim(3) in Index 1.
    shown_second = _panel(owner_slot=2)
    assert [item["variants"] for item in shown_second["authored"]] == [["1"], ["0"]]
    assert shown_second["authored"][0]["fields"]["SkinnedMeshTransparency"]["_netPitch"] == [0.334]
    assert shown_second["preview_base"]["SkinnedMeshTransparency"][4] == pytest.approx(0.334)
    shown_first = _panel(owner_slot=0)
    assert [item["variants"] for item in shown_first["authored"]] == [["0"], ["1"]]
    assert shown_first["preview_base"]["SkinnedMeshTransparency"][4] == pytest.approx(0.3)
    # Unknown owner: file order, as before.
    assert [item["variants"] for item in _panel(owner_slot=-1)["authored"]] == [["0"], ["1"]]
