"""Imported Materials & Textures: what Apply refuses, and what it says.

Each case here came from an import that either got the bare "has no proven
target binding" message, a raw decoder error, or was accepted although one
imported part had kept the game's textures.
"""
from pathlib import Path
import struct

from PIL import Image
import pytest

from cdmw.services.mesh_replacement_import import initial_replacement_state, prepare_import
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
from tests.test_mesh_editor_replacement import editor  # noqa: F401
from tests.test_mesh_editor_replacement_materials import _qt_application, material_fixture  # noqa: F401

VERTICES = "v 12 3 7\nv 16 3 7\nv 12 5 8\nv 13 3 7\nv 17 3 7\nv 13 5 8\nvt 0 0\nvt 1 0\nvt 0 1\n"
ONE_PART = "mtllib import.mtl\no Helm\n" + VERTICES + "usemtl Iron_mat\nf 1/1 2/2 3/3\n"
TWO_PARTS = ONE_PART + "usemtl Trim_mat\nf 4/1 5/2 6/3\n"
KEEP = r"or choose Keep Original Materials\.$"


IRON = "newmtl Iron_mat\nmap_Kd hl_albd.png\nmap_Pr hl_mskm.png\n"


def staged(editor, root, *, obj=ONE_PART, mtl=IRON, images=("hl_albd.png", "hl_mskm.png"), **fixture):
    """An import in a folder of its own, so only the textures listed here lie beside the model.

    Two textures, as a Blender export has: a material without one cannot simply
    adopt the only image in the folder.
    """
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, _model = material_fixture(root, snapshot, **fixture)
    folder = root / "model"
    folder.mkdir()
    model = folder / "import.obj"
    model.write_text(obj)
    model.with_suffix(".mtl").write_text(mtl)
    for index, name in enumerate(images):
        Image.new("RGBA", (4, 4), (40 + 50 * index, 30, 200 - 40 * index, 255)).save(folder / name)
    dependencies = capture_replacement_dependencies(target, context)
    keys = tuple(part.part_id for part in initial_replacement_state(snapshot).parts)
    return snapshot, target, dependencies, keys, model


def apply(snapshot, target, dependencies, keys, model, root):
    pending = prepare_import(snapshot, model, target_part_ids=keys, entry=target, dependencies=dependencies)
    return pending, prepare_imported_materials(pending, keys, root)


def test_part_mapped_only_to_a_target_without_textures_names_that_target(editor, tmp_path):
    """Helmet 0451's ghost accessory and 0468's ``mold`` bind no texture at all;
    a valid import mapped there got only "no proven target binding"."""
    from cdmw.services.mesh_rust_replacement import imported_material_status
    snapshot, target, dependencies, keys, model = staged(
        editor, tmp_path, untextured=(1,), shader=("SkinnedMeshStandard", "SkinnedMeshGhost"))
    pending = prepare_import(snapshot, model, target_part_ids=(keys[1],), entry=target, dependencies=dependencies)
    assert imported_material_status(pending)["untextured_targets"] == [keys[1]]
    with pytest.raises(ValueError, match=r"^target1 has no textures in the game's material, so it cannot take "
                                         r"imported textures\. Map Helm to another part, .* " + KEEP):
        prepare_imported_materials(pending, (keys[1],), tmp_path)
    plain = prepare_import(snapshot, model, target_part_ids=(keys[0],), entry=target, dependencies=dependencies)
    assert imported_material_status(plain)["untextured_targets"] == []
    assert any(file.path.endswith(".dds") for file in prepare_imported_materials(plain, (keys[0],), tmp_path))


def test_target_without_textures_is_filled_inside_its_own_material(editor, tmp_path):
    """Replaced together with a textured part, the part borrows that part's texture
    format. Its material's empty parameter list is written ``<Vector .../>``; the
    colour row was put into a second, unnamed material appended to the wrapper."""
    snapshot, target, dependencies, keys, model = staged(
        editor, tmp_path, obj=TWO_PARTS, mtl=IRON + "newmtl Trim_mat\nmap_Kd trim_albd.png\n",
        images=("hl_albd.png", "hl_mskm.png", "trim_albd.png"), untextured=(1,), shader="SkinnedMeshStandard")
    _pending, files = apply(snapshot, target, dependencies, keys, model, tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    mold = text[text.index('_subMeshName="target1"'):]
    mold = mold[:mold.index("</SkinnedMeshMaterialWrapper>")]
    assert mold.count("<Material") - mold.count("<MaterialParameter") == 1
    material = mold[mold.index('<Material Name="_resourceMaterial"'):mold.index("</Material>")]
    assert "_overlayColorTexture" in material and "trim_albd" in material


def test_empty_parameter_list_is_opened_for_an_inserted_texture():
    from cdmw.modding.material_source_driven import _insert_source_driven_texture_parameter
    wrapper = ('<SkinnedMeshMaterialWrapper ItemID="51" _subMeshName="mold"><Material Name="_resourceMaterial" '
               '_materialName="SkinnedMeshStandard"><Vector Name="_permutations"/><Vector Name="_parameters"/>'
               '</Material></SkinnedMeshMaterialWrapper>')
    patched, changed = _insert_source_driven_texture_parameter(wrapper, "_overlayColorTexture", "character/texture/a.dds")
    assert changed and patched.count("<Material ") == 1 and "<Material>" not in patched
    inside = patched[patched.index('<Vector Name="_parameters">'):patched.index("</Material>")]
    assert '_path="character/texture/a.dds"' in inside and inside.rstrip().endswith("</Vector>")
    assert '<Vector Name="_permutations"/>' in patched


def test_two_imported_parts_on_one_game_part_are_named_with_the_remedy(editor, tmp_path):
    """Two objects on a one-part helmet: the mapping step offers nothing else, and
    Apply said only "require one source material part per target part"."""
    snapshot, target, dependencies, keys, model = staged(editor, tmp_path, obj=TWO_PARTS, mtl=IRON + "newmtl Trim_mat\n")
    pending = prepare_import(snapshot, model, target_part_ids=keys[:1], entry=target, dependencies=dependencies)
    with pytest.raises(ValueError, match=r"^2 imported parts are mapped to target0\. With Imported Materials & Textures "
                                         r"each game part takes one imported part\. Join them before exporting, map them "
                                         r"to different parts, " + KEEP):
        prepare_imported_materials(pending, (keys[0], keys[0]), tmp_path)


def test_game_textures_missing_from_the_session_are_named_as_the_cause(editor, tmp_path):
    """Browse Archives had moved on before the first Import Replacement, so the
    session held the material file without the part's textures. Apply blamed the
    imported material, in that session and in its draft."""
    snapshot, target, dependencies, keys, model = staged(editor, tmp_path, shader="SkinnedMeshStandard")
    partial = tuple(file for file in dependencies if not file.path.casefold().endswith(".dds"))
    assert len(partial) == 1
    pending = prepare_import(snapshot, model, target_part_ids=keys[:1], entry=target, dependencies=partial)
    with pytest.raises(ValueError, match=r"^The game's textures for target0 were not loaded with this model, so the "
                                         r"imported textures cannot be fitted to it\. Select the model in Browse "
                                         r"Archives again, open it in Mesh Editor as a new edit and import again\. "
                                         r"If that does not help, choose Keep Original Materials\.$"):
        prepare_imported_materials(pending, keys[:1], tmp_path)


def test_import_replacement_uses_the_file_set_its_session_was_opened_with(monkeypatch, tmp_path):
    """Browse Archives keeps four prepared sets. After four other previews, asking
    it again gave "still preparing" for ever, or another file's set."""
    from types import SimpleNamespace
    from cdmw.models import ArchiveEntry
    from cdmw.ui.mesh_editor import replacement_flow

    def browser_moved_on(_owner, _target):
        raise AssertionError("Browse Archives was asked for a set the session already holds")

    monkeypatch.setattr(replacement_flow, "archive_workflow_dependency_context", browser_moved_on)
    monkeypatch.setattr(replacement_flow, "source_path_override", str(tmp_path / "model.obj"))
    entry = ArchiveEntry("a.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
    session = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(
        _session=lambda _sid: SimpleNamespace(replacement_state=None)))
    own = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_closing=False,
                          _current_target_entry=lambda: entry, window=lambda: None, archive_session_dependencies=own)
    event = replacement_flow.prepare_replacement_event(tab, session, {"command": "replacement_choose", "arguments": {}})
    assert event["arguments"]["_archive_dependencies"] is own
    # A session opened without a set of its own still asks.
    tab.archive_session_dependencies = None
    monkeypatch.setattr(replacement_flow, "archive_workflow_dependency_context", lambda _owner, _target: "asked")
    monkeypatch.setattr(replacement_flow, "source_path_override", str(tmp_path / "model.obj"))
    event = replacement_flow.prepare_replacement_event(tab, session, {"command": "replacement_choose", "arguments": {}})
    assert event["arguments"]["_archive_dependencies"] == "asked"


def test_material_names_with_a_stray_space_bind_like_their_textures():
    """56 shipped wrappers are named like `` cd_phm_00_cloak_00_0447_02``; the
    part's own textures, listed without the space, were filtered out."""
    from types import SimpleNamespace
    from cdmw.services.mesh_replacement_materials import material_binding_name, material_binding_names
    xml = ('<Root><SkinnedMeshMaterialWrapper _subMeshName=" cd_cloak_02"><Material Name="_resourceMaterial" '
           '_materialName="SkinnedMeshStandard"><Vector Name="_parameters"/></Material></SkinnedMeshMaterialWrapper></Root>')
    state = SimpleNamespace(target_path="character/model/cd_cloak.pac", companion_files=(), dependencies=(
        SimpleNamespace(path="character/modelproperty/cd_cloak.pac_xml", data=xml.encode()),))
    names = material_binding_names(state)
    assert names == {"cd_cloak_02"}
    for written in (" CD_Cloak_02", "CD_Cloak_02"):
        assert material_binding_name(SimpleNamespace(name=written, material="(null)"), names) == "cd_cloak_02"


@pytest.mark.parametrize("normal", (False, True), ids=("colour-only-target", "target-with-normal-map"))
@pytest.mark.parametrize("mtl", (IRON + "newmtl Trim_mat\nKd 0.8 0.1 0.1\n", IRON), ids=("plain-colour", "absent-from-mtl"))
def test_second_material_without_a_texture_is_named_with_the_reason(editor, tmp_path, mtl, normal):
    """A second, plain-colour material got the bare binding message. On a target
    with a normal map it was accepted instead, on the strength of the flat normal
    CDMW generates itself, and the part kept the game's colour texture."""
    case = staged(editor, tmp_path, obj=TWO_PARTS, mtl=mtl, normal=normal)
    with pytest.raises(ValueError, match=r"^Imported material Trim_mat has no textures of its own \(a plain colour is "
                                         r"not imported\), .* Give the material an image texture or put its faces on a textured "
                                         r"material, export again, " + KEEP):
        apply(*case, tmp_path)


@pytest.mark.parametrize("normal", (False, True))
def test_single_material_without_a_texture_is_named_with_the_reason(editor, tmp_path, normal):
    case = staged(editor, tmp_path, mtl="newmtl Iron_mat\nKd 0.8 0.1 0.1\n", images=(), normal=normal)
    snapshot, target, dependencies, keys, model = case
    with pytest.raises(ValueError, match=r"^Imported material Iron_mat has no textures of its own"):
        apply(snapshot, target, dependencies, keys[:1], model, tmp_path)


def test_textures_named_after_the_object_count_for_its_material(editor, tmp_path):
    """Textures named after the Blender object were found, routed and converted,
    then refused because the check only knew the material name."""
    snapshot, target, dependencies, keys, model = staged(
        editor, tmp_path, mtl="newmtl Iron_mat\nKd 1 1 1\n",
        images=("Helm_BaseColor.png", "Helm_Normal.png", "gorget_BaseColor.png", "gorget_Normal.png"), normal=True)
    _pending, files = apply(snapshot, target, dependencies, keys[:1], model, tmp_path)
    assert any(file.path.endswith(".dds") for file in files)
    assert "original0.dds" not in next(file for file in files if file.path.endswith(".pac_xml")).data.decode()


def test_unassigned_textures_beside_the_model_are_named_in_the_refusal(editor, tmp_path):
    """The exporter wrote no texture lines, or the folder holds another model's files."""
    snapshot, target, dependencies, keys, model = staged(
        editor, tmp_path, mtl="newmtl Iron_mat\nKd 1 1 1\n",
        images=("gorget_BaseColor.png", "gorget_Normal.png", "pants_BaseColor.png"), normal=True)
    with pytest.raises(ValueError, match=r"^Imported material Iron_mat has no textures of its own\. The textures found "
                                         r"beside the model \(gorget_BaseColor\.png, gorget_Normal\.png, pants_BaseColor\.png\) "
                                         r"are not assigned to it, so they were not used\. Assign them to the material before "
                                         r"exporting, " + KEEP):
        apply(snapshot, target, dependencies, keys[:1], model, tmp_path)


DAE = '''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit meter="1"/><up_axis>Y_UP</up_axis></asset>
<library_images><image id="albd" name="albd"><init_from>hl_albd.png</init_from></image></library_images>
<library_effects><effect id="fx"><profile_COMMON>
<newparam sid="albd-surface"><surface type="2D"><init_from>albd</init_from></surface></newparam>
<newparam sid="albd-sampler"><sampler2D><source>albd-surface</source></sampler2D></newparam>
<technique sid="common"><lambert><diffuse><texture texture="albd-sampler" texcoord="UVMap"/></diffuse></lambert></technique>
</profile_COMMON></effect></library_effects>
<library_materials><material id="mat" name="Iron mat "><instance_effect url="#fx"/></material></library_materials>
<library_geometries><geometry id="geo" name="Helm"><mesh>
<source id="positions"><float_array id="positions-array" count="9">12 3 7 16 3 7 12 5 8</float_array><technique_common><accessor source="#positions-array" count="3" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uvs"><float_array id="uvs-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#uvs-array" count="3" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="1" material="mat"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uvs" offset="1" set="0"/><p>0 0 1 1 2 2</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node id="Helm" name="Helm" type="NODE"><instance_geometry url="#geo"><bind_material><technique_common><instance_material symbol="mat" target="#mat"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>'''


def test_material_name_with_a_trailing_space_is_bound(editor, tmp_path):
    """Routing trims names; the check compared the untrimmed one and refused."""
    snapshot, target, dependencies, keys, model = staged(editor, tmp_path)
    model = model.with_suffix(".dae")
    model.write_text(DAE, encoding="utf-8")
    pending, files = apply(snapshot, target, dependencies, keys[:1], model, tmp_path)
    assert pending.source.mesh.submeshes[0].material == "Iron mat "
    assert any(file.path.endswith(".dds") for file in files)


def dx10_dds(path, dxgi_format, payload):
    """A 4x4 single-mip DDS with a DX10 header in the given DXGI format."""
    block = dxgi_format in (72, 78)
    header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, 0x1007 | (0x80000 if block else 0x8), 4, 4,
                         len(payload) if block else 16, 0, 1)
    pixel_format = struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    path.write_bytes(header + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
                     + struct.pack("<IIIII", dxgi_format, 3, 0, 1, 0) + payload)
    return path


# BC1 sRGB, BC3 sRGB and B8G8R8A8: what texture tools save, and Pillow does not read every one.
SURFACE_SOURCES = {72: bytes(8), 78: bytes(16), 87: bytes((30, 200, 90, 255)) * 16}


@pytest.mark.parametrize("dxgi_format", sorted(SURFACE_SOURCES))
def test_surface_map_pillow_cannot_read_is_decoded_or_named(tmp_path, monkeypatch, dxgi_format):
    """A roughness map saved as BC1 sRGB raised a bare ``NotImplementedError:
    Unimplemented DXGI format 72`` at the mapping step and at Apply."""
    import cdmw.core.texture_native as texture_native
    from cdmw.services.mesh_replacement_materials import _image_channel_means, _source_image
    source = dx10_dds(tmp_path / "helm_roughness.dds", dxgi_format, SURFACE_SOURCES[dxgi_format])
    try:
        with Image.open(source) as image:
            image.load()
        readable = True
    except (NotImplementedError, OSError, ValueError, SyntaxError):
        readable = False

    def decoded(_dds, png, **_options):
        Image.new("RGBA", (4, 4), (10, 128, 250, 255)).save(png)
        return {"ok": True}

    monkeypatch.setattr(texture_native, "decode_dds_preview_with_directxtex", decoded)
    assert _source_image(source, tmp_path).size == (4, 4)
    if not readable:
        # The app's own decoder stands in, so the map's values are still read.
        assert _image_channel_means(source, "GB") == pytest.approx((128 / 255, 250 / 255))
        monkeypatch.setattr(texture_native, "decode_dds_preview_with_directxtex", lambda *_a, **_k: None)
        with pytest.raises(ValueError, match=r"^Imported texture helm_roughness\.dds could not be read \(.*\)\. "
                                             r"Save it as BC7 or as PNG, then import again\.$"):
            _source_image(source, tmp_path)


def test_mapping_step_reads_a_roughness_map_pillow_cannot(editor, tmp_path, monkeypatch):
    """Choosing the model already failed: the mapping step reads the map for its sliders."""
    import cdmw.core.texture_native as texture_native
    from cdmw.services.mesh_rust_replacement import imported_material_status
    snapshot, target, dependencies, keys, model = staged(
        editor, tmp_path, mtl="newmtl Iron_mat\nmap_Kd hl_albd.png\nmap_Pr hl_rough.dds\n")
    source = dx10_dds(model.with_name("hl_rough.dds"), 72, SURFACE_SOURCES[72])

    def decoded(_dds, png, **_options):
        Image.new("RGBA", (4, 4), (128, 128, 128, 255)).save(png)
        return {"ok": True}

    monkeypatch.setattr(texture_native, "decode_dds_preview_with_directxtex", decoded)
    pending = prepare_import(snapshot, model, target_part_ids=keys[:1], entry=target, dependencies=dependencies)
    surface = imported_material_status(pending)["surface"]
    try:
        with Image.open(source) as image:
            image.load()
    except NotImplementedError:
        assert surface["roughness"] == pytest.approx(128 / 255, abs=0.01)
    else:
        assert surface["roughness"] is not None


def test_renamed_pair_with_a_stale_mtllib_uses_the_mtl_named_like_the_obj(editor, tmp_path):
    """``fiendish helm 2.obj`` still says ``mtllib fiendish helm.mtl``. The importer
    read ``fiendish helm 2.mtl``, yet Apply said the library ``.../fiendish`` was missing."""
    snapshot, target, dependencies, keys, model = staged(editor, tmp_path)
    renamed = model.with_name("fiendish helm 2.obj")
    renamed.write_text(ONE_PART.replace("mtllib import.mtl", "mtllib fiendish helm.mtl"))
    model.with_suffix(".mtl").rename(renamed.with_suffix(".mtl"))
    pending, files = apply(snapshot, target, dependencies, keys[:1], renamed, tmp_path)
    assert not pending.material_error
    assert any(file.path.endswith(".dds") for file in files)


def test_missing_material_library_is_named_as_the_obj_writes_it(editor, tmp_path):
    snapshot, target, dependencies, keys, model = staged(editor, tmp_path)
    lone = model.with_name("helm.obj")
    lone.write_text(ONE_PART.replace("mtllib import.mtl", "mtllib fiendish helm.mtl"))
    pending = prepare_import(snapshot, lone, target_part_ids=keys[:1], entry=target, dependencies=dependencies)
    assert pending.material_error == ("Missing imported material library: fiendish helm.mtl. "
                                      "Put it next to helm.obj, or name the MTL helm.mtl.")
