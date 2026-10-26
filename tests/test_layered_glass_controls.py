"""Layered equipment retains its composed pixels through glass authoring."""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import threading

import pytest
from PIL import Image

from cdmw.core.material_shader_controls import equipment_shader_options, rewrite_shader_controls
from cdmw.core.pac_xml_standard_material import find_material_wrappers, PlainMaterial, plain_material_xml
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart, PART_ID_ATTRIBUTE
from cdmw.domain.mesh.shader_controls import ShaderControls
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_shader_controls import build_shader_control_files, _shader_source_options
from cdmw.services.new_item_shader_controls import apply_shader_controls
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_planning import ModelFiles
from tests.test_shader_controls import field

PAC = "character/model/glass_sword.pac"
XML = "character/modelproperty/glass_sword.pac_xml"
CHOICE = (("Blade", ShaderControls("SkinnedMeshTranslucent", (("_extinctionTint", (1.,)),))),)


def texture(name, path):
    return (f'<MaterialParameterTexture StringItemID="{name}" ItemID="10" _name="{name}" Index="50">'
            f'<ResourceReferencePath_ITexture Name="_value" _path="{path}"/></MaterialParameterTexture>')


def layered_source(shader="SkinnedMeshEmissive_Ver2", tint="#ff8040ff"):
    paths = {role: f"character/texture/glass_{role}.dds" for role in ("base", "normal", "material", "layer", "mask", "glow")}
    block = plain_material_xml(PlainMaterial(base=paths["base"], normal=paths["normal"], material=paths["material"],
        emissive_texture=paths["glow"], emissive_color="#12AAFFFF", emissive_intensity=4))
    block = block.replace('SkinnedMeshEmissive"', shader + '"')
    extra = texture("_detailDiffuseMaskR", paths["layer"]) + texture("_detailMaskTexture", paths["mask"])
    extra += field("_tintColorR", "#ffffff00", "Color") + field("_dyeingDetailLayerColorMaskR", tint, "Color")
    block = block.replace('</Vector>', extra + '</Vector>', 1)
    xml = '<root><SkinnedMeshMaterialWrapper _subMeshName="Blade">' + block + '</SkinnedMeshMaterialWrapper>'
    xml += '<SkinnedMeshMaterialWrapper _subMeshName="Handle">' + plain_material_xml(PlainMaterial(base=paths["base"])) + '</SkinnedMeshMaterialWrapper></root>'
    side = {XML: xml.encode()}
    for role, colour in {"base": (255, 255, 255, 255), "normal": (110, 180, 240, 255),
                         "material": (255, 128, 64, 255), "layer": (200, 200, 200, 255),
                         "mask": (255, 0, 0, 255), "glow": (80, 80, 80, 255)}.items():
        image = Image.new("RGBA", (8, 8), colour)
        if role == "layer":
            image.paste((100, 100, 100, 255), (4, 0, 8, 8))
        if role == "normal":
            image.paste((150, 100, 240, 255), (4, 0, 8, 8))
        stream = BytesIO()
        image.save(stream, format="DDS")
        side[paths[role]] = stream.getvalue()
    return ModelFiles(pac_data=b"original geometry", side_files=side)


def mesh_state(files):
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=[SubMesh(name="Blade"), SubMesh(name="Handle")])
    state = MeshReplacementState(PAC, "a" * 64, (ReplacementPart("blade", 0, shader_controls=CHOICE[0][1]), ReplacementPart("handle", 1)),
        dependencies=tuple(ReplacementFile(path, data) for path, data in files.side_files.items()))
    return mesh, state


@pytest.mark.parametrize("route", ["mesh", "template", "prepared_import"])
@pytest.mark.parametrize("shader", ["SkinnedMeshStandard_Ver2", "SkinnedMeshEmissive_Ver2"])
def test_layered_glass_bakes_colours_and_preserves_other_materials(route, shader):
    files = layered_source(shader)
    before = dict(files.side_files)
    assert "SkinnedMeshTranslucent" in equipment_shader_options(before[XML].decode())["blade"][1]
    if route == "mesh":
        mesh, state = mesh_state(files)
        side = {file.path: file.data for file in build_shader_control_files(state, mesh, ())}
        restored = replace(state, parts=tuple(replace(part, shader_controls=None) for part in state.parts))
        assert build_shader_control_files(restored, mesh, ()) == ()
    elif route == "template":
        snapshot = SimpleNamespace(has_entry=before.__contains__, payload=lambda path: files.pac_data if path == PAC else before[path])
        output = prepare_template_model(snapshot, (PAC,), shader_controls=CHOICE)
        side = output.side_files
        assert output.pac_data == files.pac_data
    else:
        output = apply_shader_controls(files, CHOICE)
        side = output.side_files
        assert output.pac_data == files.pac_data
    text = side[XML].decode()
    blade, handle = find_material_wrappers(text)
    old_blade, old_handle = find_material_wrappers(before[XML].decode())
    assert blade.shader == "SkinnedMeshTranslucent"
    assert float(blade.value("_extinctionTint")) == 1
    assert float(blade.value("_thickness")) == pytest.approx(.02)
    assert float(blade.value("_extinctionCoefficient")) == pytest.approx(.3)
    assert blade.textures["_emissiveIntensityTexture"] == old_blade.textures["_emissiveIntensityTexture"]
    assert blade.value("_emissiveColor") == "#12AAFFFF" and float(blade.value("_emissiveIntensity")) == 4
    assert text[handle.start:handle.end] == before[XML].decode()[old_handle.start:old_handle.end]
    assert files.side_files == before
    assert "_detailDiffuseMaskR" not in blade.textures
    with Image.open(BytesIO(side[blade.textures["_baseColorTexture"]])) as image:
        left, right = image.convert("RGB").getpixel((1, 1)), image.convert("RGB").getpixel((6, 1))
    assert left[0] > left[1] > left[2], (left, right)
    assert all(a > b for a, b in zip(left, right)), (left, right)
    assert blade.textures["_normalTexture"] in side and blade.textures["_materialTexture"] in side


def test_layered_conversion_never_bypasses_missing_sources_or_strict_xml_writer():
    files = layered_source()
    with pytest.raises(ValueError, match="compatible plain"):
        rewrite_shader_controls(files.side_files[XML].decode(), CHOICE)
    missing = replace(files, side_files={path: data for path, data in files.side_files.items() if not path.endswith("glass_layer.dds")})
    with pytest.raises(ValueError, match="missing texture"):
        apply_shader_controls(missing, CHOICE)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RunCancelled):
        apply_shader_controls(files, CHOICE, stop_event=cancelled)
    ambiguous = files.side_files[XML].replace(b'_subMeshName="Handle"', b'_subMeshName="Blade"')
    with pytest.raises(ValueError, match="Ambiguous layered material"):
        apply_shader_controls(replace(files, side_files={**files.side_files, XML: ambiguous}), CHOICE)


def test_mesh_shader_availability_matches_source_and_keeps_conflicts_disabled():
    files = layered_source()
    mesh, state = mesh_state(files)
    for part, rule in zip(mesh.submeshes, state.parts):
        setattr(part, PART_ID_ATTRIBUTE, rule.part_id)
    session = SimpleNamespace(replacement_state=state, mesh_format="pac", working_mesh=mesh, base_mesh=mesh)
    options = _shader_source_options(session)
    assert options[0]["source_shader"] == "SkinnedMeshEmissive_Ver2"
    assert options[0]["shader_options"]["SkinnedMeshTranslucent"] == ""
    assert options[0]["shader_options"]["SkinnedMeshWing"]
    assert options[0]["shader_options"]["Translucent"]
    session.replacement_state = replace(state, parts=(replace(state.parts[0], translucency=(.1, .3)), state.parts[1]))
    assert all(_shader_source_options(session)[0]["shader_options"].values())
    session.replacement_state = None
    assert all(_shader_source_options(session)[0]["shader_options"].values())
    mesh.submeshes[0].preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
    mesh.submeshes[0].preview_material_texture_inputs = (SimpleNamespace(parameter_name="_detailDiffuseMaskR", source_texture_path="layer.dds"),)
    assert _shader_source_options(session)[0]["shader_options"]["SkinnedMeshTranslucent"] == ""


@pytest.mark.parametrize("route", ["mesh", "template", "prepared_import"])
def test_sword_model_variants_keep_distinct_colours_and_private_maps(route):
    from cdmw.core.material_shader_controls import control_material_variants
    from cdmw.services.shader_controls_preview import preview_material_variant, shader_preview_mesh
    first, second = layered_source(), layered_source(tint="#4080ffff")
    before = '<ModelPropertyList><ModelProperty Index="0">' + first.side_files[XML].decode() + '</ModelProperty>'
    before += '<ModelProperty Index="1">' + second.side_files[XML].decode() + '</ModelProperty></ModelPropertyList>'
    files = replace(first, side_files={**first.side_files, XML: before.encode()})
    assert "SkinnedMeshTranslucent" in equipment_shader_options(before)["blade"][1]
    mesh, state = mesh_state(files)
    snapshot = SimpleNamespace(payload=lambda path: files.pac_data if path == PAC else files.side_files[path], has_entry=files.side_files.__contains__)
    if route == "mesh":
        output = {file.path: file.data for file in build_shader_control_files(state, mesh, ())}
    elif route == "template":
        output = prepare_template_model(snapshot, (PAC,), shader_controls=CHOICE).side_files
    else:
        output = apply_shader_controls(files, CHOICE).side_files
    variants = control_material_variants(output[XML].decode())
    paths = [variant["blade"][2]["_baseColorTexture"] for variant in variants]
    assert len(set(paths)) == 2
    pixels = [Image.open(BytesIO(output[path])).convert("RGB").getpixel((1, 1)) for path in paths]
    assert pixels[0][0] > pixels[0][2] and pixels[1][2] > pixels[1][0]
    assert all(variant["blade"][0] == "SkinnedMeshTranslucent" for variant in variants)
    mesh.submeshes[0].preview_pac_material_owner_slot_index = 2
    assert 'Index="1"' in preview_material_variant(before, mesh.submeshes[0])
    preview = shader_preview_mesh(mesh, CHOICE, snapshot=snapshot)
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][0] == 9
    assert preview.submeshes[1] is mesh.submeshes[1]
    # One incompatible variant blocks the shared choice before Apply.
    unsupported = before
    split = unsupported.index('<ModelProperty Index="1">')
    unsupported = unsupported[:split] + unsupported[split:].replace('SkinnedMeshEmissive_Ver2', 'SkinnedMeshHair')
    assert "SkinnedMeshTranslucent" not in equipment_shader_options(unsupported)["blade"][1]


def test_new_item_layered_glass_is_selectable_and_other_experiments_are_disabled():
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    editor = ShaderControlsEditor()
    events = []
    editor.changed.connect(events.append)
    try:
        editor.refresh((("Blade", "Blade"),), (), equipment_shader_options(layered_source().side_files[XML].decode()))
        index = editor.family.findData("SkinnedMeshTranslucent")
        assert editor.family.model().item(index).isEnabled()
        assert not editor.family.model().item(editor.family.findData("SkinnedMeshWing")).isEnabled()
        editor.family.setCurrentIndex(index)
        assert events[-1] == (("Blade", ShaderControls("SkinnedMeshTranslucent")),)
        editor.reset.click()
        assert events[-1] == ()
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()


def test_mesh_preview_publishes_exported_glass_maps_and_keeps_unselected_bindings(tmp_path, monkeypatch):
    import hashlib
    from cdmw.services.mesh_shader_controls_preview import stage_shader_preview
    from cdmw.services.mesh_rust_authoring import _session_root_identity
    files = layered_source()
    mesh, state = mesh_state(files)
    for part, rule in zip(mesh.submeshes, state.parts):
        setattr(part, PART_ID_ATTRIBUTE, rule.part_id)
        part.vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        part.faces = [(0, 1, 2)]
        part.uvs = [(0, 0), (1, 0), (0, 1)]
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_mesh", lambda *_: mesh)
    session = SimpleNamespace(original_data=b"source")
    authoring = SimpleNamespace(root=tmp_path, root_identity=_session_root_identity(tmp_path),
        shadow_session_id="test", shadow_service=SimpleNamespace(_session=lambda _: session), archive_refit_material_cache={})
    old = {"role": "base_color", "file": {"path": "original.dds"}, "material_indices_by_lod": [[0, 1]]}
    payload = {"textures": [old]}
    presentations = {(0, 0): {"texture_tint": [.1, .2, .3]}, (0, 1): {"texture_tint": [.5, .6, .7]}}
    stage_shader_preview(authoring, mesh, state, payload, presentations, None)
    assert old["material_indices_by_lod"] == [[0, 1]]
    assert payload["textures"][0]["material_indices_by_lod"] == [[1]]
    assert presentations[(0, 1)] == {"texture_tint": [.5, .6, .7]}
    assert presentations[(0, 0)]["texture_tint"] is None  # Baked colour needs no second tint.
    assert presentations[(0, 0)]["shader_controls"][0] == 9
    output = {file.path: file.data for file in build_shader_control_files(state, mesh, ())}
    blade = find_material_wrappers(output[XML].decode())[0]
    for parameter, role in (("_baseColorTexture", "base_color"), ("_normalTexture", "normal"), ("_materialTexture", "material")):
        expected = hashlib.sha256(output[blade.textures[parameter]]).hexdigest().upper()
        assert any(row["role"] == role and row["file"].get("sha256") == expected and row["material_indices_by_lod"] == [[0]]
                   for row in payload["textures"]), (role, expected, payload["textures"])


@pytest.mark.parametrize("route", ["mesh", "template"])
def test_translucency_bakes_each_model_variant_from_its_own_layers(route):
    from cdmw.core.material_shader_controls import control_material_variants
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from cdmw.services.mesh_translucency import build_translucency_files

    def baseless(tint):
        files = layered_source(tint=tint)
        text = files.side_files[XML].decode()
        blade = find_material_wrappers(text)[0]
        block = text[blade.start:blade.end].replace(texture("_baseColorTexture", "character/texture/glass_base.dds"), "")
        base = '<MaterialParameterTexture StringItemID="_baseColorTexture" ItemID="2" _name="_baseColorTexture" Index="0">'
        start = block.index(base)
        block = block[:start] + block[block.index("</MaterialParameterTexture>", start) + len("</MaterialParameterTexture>"):]
        return text[:blade.start] + block + text[blade.end:], files

    first, files = baseless("#ff8040ff")
    second, _ = baseless("#4080ffff")
    assert "_baseColorTexture" not in find_material_wrappers(first)[0].textures
    before = ('<ModelPropertyList><ModelProperty Index="0">' + first + '</ModelProperty>'
              '<ModelProperty Index="1">' + second + '</ModelProperty></ModelPropertyList>')
    files = replace(files, side_files={**files.side_files, XML: before.encode()})
    if route == "mesh":
        mesh, state = mesh_state(files)
        state = replace(state, parts=(replace(state.parts[0], shader_controls=None, translucency=(.1, .3)), state.parts[1]))
        output = {file.path: file.data for file in build_translucency_files(state, mesh, ())}
    else:
        snapshot = SimpleNamespace(payload=lambda path: files.pac_data if path == PAC else files.side_files[path],
                                   has_entry=files.side_files.__contains__)
        output = prepare_template_model(snapshot, (PAC,), translucency=TranslucencyChoice(("blade",), .1, .3)).side_files
    variants = control_material_variants(output[XML].decode())
    assert all(variant["blade"][0] == "SkinnedMeshTranslucent" for variant in variants)
    paths = [variant["blade"][2]["_baseColorTexture"] for variant in variants]
    assert len(set(paths)) == 2
    pixels = [Image.open(BytesIO(output[path])).convert("RGB").getpixel((1, 1)) for path in paths]
    assert pixels[0][0] > pixels[0][2] and pixels[1][2] > pixels[1][0]
