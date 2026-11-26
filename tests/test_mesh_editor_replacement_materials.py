from dataclasses import replace
from pathlib import Path
import io
import re
import struct
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_import import initial_replacement_state, prepare_import, compose_import
from cdmw.services.mesh_replacement_import import commit_replacement
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
from tests.test_mesh_editor_replacement import editor
from tests.owned_settings import owned_settings


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    # Material preparation can initialize Qt image resources before the final
    # widget test. Keep one application alive for both paths from the start.
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application


def entry(root, path, data):
    source = root / Path(path).name
    source.write_bytes(data)
    return ArchiveEntry(path, root / "0009/0.pamt", source, 0, len(data), len(data), 0, 0)


def material_fixture(root, snapshot, *, layered=False, normal=False, shader="", surface=None,
                     surface_parameter="_materialTexture", untextured=(), stray_space=False):
    source = root / "color.dds"
    Image.new("RGBA", (4, 4), (210, 30, 60, 255)).save(source)
    original = root / "original.dds"
    Image.new("RGBA", (4, 4), (20, 190, 90, 255)).save(original)
    # A layered target paints its own detail mask on the original UV layout.
    layer = (lambda i: f'<MaterialParameterTexture _name="_detailMaskTexture" Index="1"><ResourceReferencePath_ITexture '
             f'_path="character/texture/detail{i}.dds"/></MaterialParameterTexture>') if layered else (lambda i: "")
    if normal:
        # Its normal map is sculpted for that layout too (Kairos Plate Helm).
        layer = (lambda i: f'<MaterialParameterTexture _name="_normalTexture" Index="1"><ResourceReferencePath_ITexture '
                 f'_path="character/texture/original{i}_n.dds"/></MaterialParameterTexture>')
    surface_dds = root / "original_sp.dds"
    if surface is not None:
        # The game part's own surface map (an `_sp`: G roughness, B metal), in
        # two halves so only its mean is a single value.
        image = Image.new("RGBA", (4, 4), (255, surface[0] - 20, surface[1], 255))
        image.paste((255, surface[0] + 20, surface[1], 255), (0, 2, 4, 4))
        image.save(surface_dds)
        layer = (lambda i: f'<MaterialParameterTexture StringItemID="{surface_parameter}" ItemID="6" _name="{surface_parameter}" '
                 f'Index="1"><ResourceReferencePath_ITexture Name="_value" _path="character/texture/original{i}_sp.dds"/>'
                 '</MaterialParameterTexture>')
    xml = ('<Root>' + ''.join(
        # 56 shipped wrappers carry a stray leading space (`` cd_phm_00_cloak_00_0447_02``).
        f'<SkinnedMeshMaterialWrapper _subMeshName="{" " if stray_space else ""}target{i}">'
        + (f'<Material Name="_resourceMaterial" _materialName="{shader[i] if isinstance(shader, tuple) else shader}">'
           if shader else '<Material>')
        # A part in `untextured` is drawn by a material with an empty parameter list, as the game writes it (a mold).
        + ('<Vector Name="_permutations"/><Vector Name="_parameters"/>' if i in untextured else
           '<Vector Name="_parameters">'
           f'<MaterialParameterTexture _name="_diffuseTexture" Index="0"><ResourceReferencePath_ITexture '
           f'_path="character/texture/original{i}.dds"/></MaterialParameterTexture>{layer(i)}</Vector>')
        + '</Material></SkinnedMeshMaterialWrapper>' for i in range(2)) + '</Root>')
    target = entry(root, snapshot.mesh.path, snapshot.original_data)
    entries = [target, entry(root, str(Path(target.path).with_suffix(".pac_xml")), xml.encode()),
               *(entry(root, f"character/texture/original{i}.dds", original.read_bytes()) for i in range(2)),
               *((entry(root, f"character/texture/detail{i}.dds", original.read_bytes()) for i in range(2)) if layered else ()),
               *((entry(root, f"character/texture/original{i}_n.dds", original.read_bytes()) for i in range(2)) if normal else ()),
               *((entry(root, f"character/texture/original{i}_sp.dds", surface_dds.read_bytes()) for i in range(2))
                 if surface is not None else ())]
    context = SimpleNamespace(entries_by_basename={Path(item.path).name.casefold(): [item] for item in entries},
                              entries_by_normalized_path={item.path.casefold(): [item] for item in entries})
    model = root / "import.obj"
    model.write_text("mtllib import.mtl\no replacement\nusemtl imported\nv 12 3 7\nv 16 3 7\nv 12 5 8\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\n")
    return target, context, model


def test_imported_materials_use_retained_converter_and_preserve_unselected_binding(editor, tmp_path):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    assert len(dependencies) == 3
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    assert any(file.path.endswith(".dds") for file in files)
    sidecar = next(file for file in files if file.path.endswith(".pac_xml"))
    text = sidecar.data.decode()
    assert "original1.dds" in text
    mesh, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
    assert mesh.submeshes[1].material == snapshot.mesh.submeshes[1].material
    assert state.parts[0].material_choice == "imported"


@pytest.fixture
def target1_is_a_helper(monkeypatch):
    """Treat fixture part target1 as a helmet's ``*_inside`` helper wrapper."""
    import cdmw.modding.material_replacer as replacer
    import cdmw.modding.material_source_driven as routing
    helper = lambda name: str(name).casefold() == "target1"  # noqa: E731
    monkeypatch.setattr(replacer, "is_static_replacement_helper_material_name", helper)
    monkeypatch.setattr(routing, "is_static_replacement_helper_material_name", helper)


def test_imported_material_mapped_only_to_a_helper_target_names_it(editor, tmp_path, target1_is_a_helper):
    """A user mapped a helmet piece to ``_inside`` and Apply said only "no proven
    target binding"; the mapping step and Apply now name the helper target."""
    from cdmw.services.mesh_rust_replacement import imported_material_status
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    keys = tuple(part.part_id for part in initial_replacement_state(snapshot).parts)
    pending = prepare_import(snapshot, model, target_part_ids=(keys[1],), entry=target, dependencies=dependencies)
    assert imported_material_status(pending)["helper_targets"] == [keys[1]]
    with pytest.raises(ValueError, match=r"^target1 is a helper material for the inside of the model .* "
                                         r"or choose Keep Original Materials\.$"):
        prepare_imported_materials(pending, (keys[1],), tmp_path)
    plain = prepare_import(snapshot, model, target_part_ids=(keys[0],), entry=target, dependencies=dependencies)
    assert imported_material_status(plain)["helper_targets"] == []


def test_helper_target_sharing_a_routed_material_is_allowed(editor, tmp_path, target1_is_a_helper):
    """The helper wrapper keeps the game's material; the shared imported material
    still reaches the main part, so Apply goes ahead."""
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    model.write_text("mtllib import.mtl\nusemtl imported\nv 12 3 7\nv 16 3 7\nv 12 5 8\nvt 0 0\nvt 1 0\nvt 0 1\n"
                     "o shell\nf 1/1 2/2 3/3\no lining\nf 1/1 3/3 2/2\n")
    dependencies = capture_replacement_dependencies(target, context)
    keys = tuple(part.part_id for part in initial_replacement_state(snapshot).parts)
    pending = prepare_import(snapshot, model, target_part_ids=keys, entry=target, dependencies=dependencies)
    assert len(pending.source.mesh.submeshes) == 2
    files = prepare_imported_materials(pending, keys, tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, helper = text.split('_subMeshName="target1"')
    assert "original0.dds" not in replaced and "original1.dds" in helper


def test_imported_materials_are_built_with_the_weights_choice_apply_will_use(editor, tmp_path, monkeypatch):
    """A rig that cannot be kept has no default choice, so the materials pass must
    compose with the chosen one or Apply stops asking for a choice already made."""
    import cdmw.services.mesh_replacement_import as imports
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    composed, compose = [], imports.compose_import
    monkeypatch.setattr(imports, "compose_import", lambda *args, **kwargs: (
        composed.append(kwargs.get("skin_policy")), compose(*args, **kwargs))[1])
    assert prepare_imported_materials(pending, (key,), tmp_path, skin_policy="transfer")
    assert prepare_imported_materials(pending, (key,), tmp_path)
    assert composed == ["transfer", None]


def test_imported_materials_drop_the_targets_inherited_detail_layers(editor, tmp_path):
    """The target's detail mask follows the original UVs; on the imported
    model's UVs it shows through as a mixed-up second texture."""
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, layered=True)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    assert "detail0.dds" not in replaced and "original0.dds" not in replaced
    assert "detail1.dds" in untouched and "original1.dds" in untouched


@pytest.mark.parametrize("own_normal", [False, True])
def test_imported_materials_replace_the_targets_normal_map(editor, tmp_path, own_normal):
    """The target's normal map follows the original UVs; on the imported
    model's UVs its engravings show through the imported texture."""
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, normal=True)
    if own_normal:
        Image.new("RGBA", (4, 4), (140, 100, 255, 255)).save(tmp_path / "bumps.png")
        model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\nmap_Bump bumps.png\n")
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    assert "original0_n.dds" not in replaced and "_normalTexture" in replaced
    assert ("normal_neutral" in replaced) is not own_normal
    assert "original1_n.dds" in untouched
    bound = {path.casefold() for path in re.findall(r'_path="([^"]+)"', replaced)}
    assert all(file.path.casefold() in bound for file in files if file.path.endswith(".dds"))


def _surface_pending(editor, tmp_path, shader="SkinnedMeshCloth_Ver2", mtl="", **fixture):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader=shader, **fixture)
    if mtl:
        model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\n" + mtl)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    return prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies), key


def test_imported_materials_write_roughness_and_metallic_as_layer_r(editor, tmp_path):
    """Ver2 equipment shaders read roughness (G) and metalness (B) from
    _detailMaterialMaskR, weighted by _dyeingGlobalOpacity byte 0 and enabled
    by _colorBlendingFlag bit 2. Without it the imported surface is mirror-like."""
    from cdmw.services.mesh_rust_replacement import imported_surface_support
    pending, key = _surface_pending(editor, tmp_path)
    assert imported_surface_support(pending) == ""
    files = prepare_imported_materials(pending, (key,), tmp_path, surface=(0.8, 0.25))
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    layer = re.search(r'_name="_detailMaterialMaskR"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]+)"', replaced)
    assert layer and 'StringItemID="_detailMaterialMaskR" ItemID="3806852434362366"' in replaced
    diffuse = re.search(r'_name="_detailDiffuseMaskR"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]+)"', replaced)
    assert diffuse and diffuse.group(1) == "texture/nonetexture0xff888888.dds"
    assert 'StringItemID="_detailDiffuseMaskR" ItemID="1028073018359806"' in replaced
    assert re.search(r'_name="_colorBlendingFlag" _value="4"', replaced)
    assert re.search(r'_name="_dyeingGlobalOpacity" _value="255"', replaced)
    assert "_detailMaterialMaskR" not in untouched and "_detailDiffuseMaskR" not in untouched and "_colorBlendingFlag" not in untouched
    texture = next(file for file in files if file.path == layer.group(1))
    with Image.open(io.BytesIO(texture.data)) as image:
        assert image.size == (4, 4) and image.convert("RGBA").getpixel((0, 0)) == (0, 204, 64, 255)
    assert struct.unpack_from("<I", texture.data, 28)[0] == 3  # full mip chain for 4x4


@pytest.mark.parametrize("shader", ["SkinnedMeshBlendHeight", "SkinnedMeshStandard"])
def test_imported_materials_write_roughness_and_metallic_as_the_material_texture(editor, tmp_path, shader):
    """The SkinnedMeshStandard-technique shaders most creatures use (the wyvern's
    BlendHeight body, Standard) read roughness (G) and metalness (B) from
    _materialTexture once the import has removed the layers. The import writes
    none, and its default is NoneTexture0x00000000, so the surface was a mirror."""
    from cdmw.services.mesh_rust_replacement import imported_surface_support
    pending, key = _surface_pending(editor, tmp_path, shader=shader)
    assert imported_surface_support(pending) == ""
    files = prepare_imported_materials(pending, (key,), tmp_path, surface=(0.8, 0.25))
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    material = re.search(r'<MaterialParameterTexture StringItemID="_materialTexture" ItemID="6" _name="_materialTexture" '
                         r'Index="\d+"><ResourceReferencePath_ITexture Name="_value" _path="([^"]+_sp\.dds)"', replaced)
    assert material
    assert "_detailMaterialMaskR" not in replaced and "_detailDiffuseMaskR" not in replaced and "_colorBlendingFlag" not in replaced
    assert "_materialTexture" not in untouched
    textures = [file for file in files if file.path.endswith(".dds") and "_cdmw_surface_" in file.path]
    assert [file.path for file in textures] == [material.group(1)]  # the unused layer-R texture is pruned
    with Image.open(io.BytesIO(textures[0].data)) as image:
        assert image.size == (4, 4) and image.convert("RGBA").getpixel((0, 0)) == (255, 204, 64, 255)


@pytest.mark.parametrize("shader, parameter", [("SkinnedMeshCloth_Ver2", "_detailMaterialMaskR"),
                                               ("SkinnedMeshStandard", "_materialTexture")])
def test_surface_reaches_wrappers_named_with_a_stray_space(editor, tmp_path, shader, parameter):
    """56 shipped wrappers are named `` cd_...``. The binding names are trimmed,
    so the surface code, comparing the untrimmed wrapper name, refused the
    sliders ("found no replaced equipment material") and at defaults wrote no
    surface at all, which the game reads as roughness 0."""
    for surface in ((0.8, 0.25), None):
        root = tmp_path / ("slider" if surface else "default")
        root.mkdir()
        pending, key = _surface_pending(editor, root, shader=shader, stray_space=True)
        files = prepare_imported_materials(pending, (key,), root, surface=surface)
        text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
        replaced, untouched = text.split('_subMeshName=" target1"')
        match = re.search(rf'_name="{parameter}"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]+)"', replaced)
        assert match and "_cdmw_surface_" in match.group(1), replaced
        assert "_cdmw_surface_" not in untouched
        expected = (204, 64) if surface else (128, 0)
        texture = next(file for file in files if file.path == match.group(1))
        with Image.open(io.BytesIO(texture.data)) as image:
            assert image.convert("RGBA").getpixel((0, 0))[1:3] == expected


def test_one_surface_reaches_ver2_and_standard_wrappers_by_their_own_paths():
    from cdmw.core.pac_xml_surface_layer import apply_surface_layer

    def wrapper(name, shader):
        return (f'<SkinnedMeshMaterialWrapper _subMeshName="{name}"><Material Name="_resourceMaterial" '
                f'_materialName="{shader}"><Vector Name="_parameters"><MaterialParameterTexture '
                f'StringItemID="_baseColorTexture" ItemID="8" _name="_baseColorTexture" Index="0">'
                f'<ResourceReferencePath_ITexture Name="_value" _path="character/texture/{name}.dds"/>'
                '</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>')

    text = "<Root>" + wrapper("armour", "SkinnedMeshStandard_Ver2") + wrapper("body", "SkinnedMeshBlendHeight") + "</Root>"
    edited, changed = apply_surface_layer(text, {"armour", "body"}, "layer.dds", "material_sp.dds")
    armour, body = edited.split('_subMeshName="body"')
    assert changed == 2
    assert '_name="_detailMaterialMaskR"' in armour and "material_sp.dds" not in armour
    assert '_name="_detailDiffuseMaskR"' in armour and "texture/nonetexture0xff888888.dds" in armour
    assert '_name="_materialTexture"' in body and "layer.dds" not in body and "_colorBlendingFlag" not in body and '_name="_detailDiffuseMaskR"' not in body


def _surface_binding(files, parameter):
    """The replaced wrapper's texture for ``parameter`` and its first pixel."""
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    match = re.search(rf'_name="{parameter}"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]+)"', replaced)
    assert match, replaced
    assert "_cdmw_surface_" not in untouched
    texture = next(file for file in files if file.path == match.group(1))
    with Image.open(io.BytesIO(texture.data)) as image:
        return match.group(1), image.size, image.convert("RGBA").getpixel((0, 0))


@pytest.mark.parametrize("shader", ["SkinnedMeshBlendHeight", "SkinnedMeshStandard", "SkinnedMeshFur"])
def test_imported_materials_take_the_game_parts_surface_by_default(editor, tmp_path, shader):
    """A wyvern import with the sliders left alone came out wet: the import drops
    _materialTexture and the shader then reads roughness 0. Without a surface of
    its own the import now takes the mean of the game part's _sp texture (the
    wyvern body's averages G 0.47, B 0.22), not the texture itself, whose layout
    follows the original UVs."""
    pending, key = _surface_pending(editor, tmp_path, shader=shader, surface=(120, 57))
    files = prepare_imported_materials(pending, (key,), tmp_path)
    path, size, pixel = _surface_binding(files, "_materialTexture")
    assert path.endswith("_cdmw_surface_120_057_sp.dds") and "original0_sp" not in path
    assert size == (4, 4) and pixel == (255, 120, 57, 255)


def test_imported_materials_without_any_surface_are_matte_not_a_mirror(editor, tmp_path):
    pending, key = _surface_pending(editor, tmp_path, shader="SkinnedMeshBlendHeight")
    files = prepare_imported_materials(pending, (key,), tmp_path)
    assert _surface_binding(files, "_materialTexture")[2] == (255, 128, 0, 255)


def test_imported_values_outrank_the_game_parts_surface(editor, tmp_path):
    pending, key = _surface_pending(editor, tmp_path, shader="SkinnedMeshBlendHeight", surface=(120, 57), mtl="Pr 0.8\n")
    files = prepare_imported_materials(pending, (key,), tmp_path)
    # Roughness from the MTL, metal from the game part: the import states none.
    assert _surface_binding(files, "_materialTexture")[2] == (255, 204, 57, 255)


def test_imported_roughness_and_metallic_maps_become_the_material_texture(editor, tmp_path):
    """map_Pr/map_Pm were reported as "not auto-bound". On a Standard-technique
    wrapper they share the import's UVs with its colour map, so they are packed
    per pixel (R 255, G roughness, B metal) in the game _sp's own BC1 format."""
    rough = Image.new("L", (8, 8), 40)
    rough.paste(200, (0, 4, 8, 8))
    rough.save(tmp_path / "rough.png")
    Image.new("L", (4, 4), 160).save(tmp_path / "metal.png")
    pending, key = _surface_pending(editor, tmp_path, shader="SkinnedMeshBlendHeight", surface=(120, 57),
                                    mtl="map_Pr rough.png\nmap_Pm metal.png\n")
    files = prepare_imported_materials(pending, (key,), tmp_path)
    path, size, pixel = _surface_binding(files, "_materialTexture")
    texture = next(file for file in files if file.path == path)
    assert re.search(r"_cdmw_surface_[0-9a-f]{12}_sp\.dds$", path)
    assert texture.data[84:88] == b"DXT1" and struct.unpack_from("<I", texture.data, 28)[0] == 4
    with Image.open(io.BytesIO(texture.data)) as image:
        rgba = image.convert("RGBA")
        top, bottom = rgba.getpixel((0, 0)), rgba.getpixel((0, 7))
    assert size == (8, 8)
    assert top[0] >= 250 and abs(top[1] - 40) <= 4 and abs(top[2] - 160) <= 8
    assert abs(bottom[1] - 200) <= 4 and abs(bottom[2] - 160) <= 8


@pytest.mark.parametrize("fixture, mtl, expected", [
    ({"surface": (120, 57), "surface_parameter": "_detailMaterialMaskR"}, "", (0, 120, 57, 255)),
    ({}, "Pr 0.8\nPm 0.25\n", (0, 204, 64, 255)),
    ({}, "", (0, 128, 0, 255)),
])
def test_ver2_imports_get_a_default_layer_r(editor, tmp_path, fixture, mtl, expected):
    """Ver2 layer UVs are rotated, so the default is uniform: the import's own
    values, else the game part's layer R mean, else matte."""
    pending, key = _surface_pending(editor, tmp_path, shader="SkinnedMeshCloth_Ver2", mtl=mtl, **fixture)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    assert _surface_binding(files, "_detailMaterialMaskR")[2] == expected


def _two_shader_variant_pending(editor, tmp_path, layer_shader="SkinnedMeshStandard_Ver2",
                                material_shader="SkinnedMeshStandard", layer_parameter="_detailMaterialMaskR"):
    """target0 is Standard_Ver2 in variant 0 and SkinnedMeshStandard in variant 1,
    each with its own game surface texture, as ``cd_phm_00_ub_belt_0010_02`` is in
    the stock ``cd_m0001_00_so_phm_ub_33005`` armour."""
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader=material_shader, surface=(120, 57))
    layer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 60, 250, 255)).save(layer, format="DDS")
    dependencies = list(capture_replacement_dependencies(target, context))
    for index, file in enumerate(dependencies):
        if not file.path.endswith(".pac_xml"):
            continue
        body = file.data.decode().removeprefix("<Root>").removesuffix("</Root>")
        first, rest = body.split('<SkinnedMeshMaterialWrapper _subMeshName="target1"')
        ver2 = (first.replace(f'_materialName="{material_shader}"', f'_materialName="{layer_shader}"')
                .replace("_materialTexture", layer_parameter).replace("original0_sp.dds", "layer0_sp.dds"))
        variants = (ver2 + '<SkinnedMeshMaterialWrapper _subMeshName="target1"' + rest, body)
        dependencies[index] = replace(file, data=('<ModelPropertyList>' + ''.join(
            f'<ModelProperty Index="{i}">{text}</ModelProperty>' for i, text in enumerate(variants)
        ) + '</ModelPropertyList>').encode())
    game_sp = next(file for file in dependencies if file.path.endswith("original0_sp.dds"))
    dependencies.append(replace(game_sp, path="character/texture/layer0_sp.dds", data=layer.getvalue()))
    key = initial_replacement_state(snapshot).parts[0].part_id
    return prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=tuple(dependencies)), key


def _variant_surface(files, variant, parameter):
    from cdmw.core.material_shader_controls import material_variant_blocks
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced = material_variant_blocks(text)[variant].group().split('_subMeshName="target1"')[0]
    match = re.search(rf'_name="{parameter}"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]*)"', replaced)
    assert match and match.group(1), f"variant {variant} has no {parameter}: {replaced}"
    texture = next(file for file in files if file.path == match.group(1))
    with Image.open(io.BytesIO(texture.data)) as image:
        return image.convert("RGBA").getpixel((0, 0))


_VARIANT_SHADERS = [("SkinnedMeshStandard_Ver2", "SkinnedMeshStandard"), ("SkinnedMeshCloth_Ver2", "SkinnedMeshCloth"),
                    ("SkinnedMeshFur_Ver2", "SkinnedMeshFur"), ("SkinnedMeshEmissive_Ver2", "SkinnedMeshEmissive")]


@pytest.mark.parametrize("layer_shader, material_shader", _VARIANT_SHADERS)
def test_a_part_with_a_different_shader_in_each_variant_gets_each_its_own_surface(editor, tmp_path, layer_shader,
                                                                                   material_shader):
    """The stock south-faction armour 33005 uses Standard_Ver2 for its first part in
    one variant and SkinnedMeshStandard in the other. The default surface looked
    the shader up by part name, so the Ver2 wrapper was bound to an empty layer R
    (roughness 0, a mirror) and the Standard one took 0.5 instead of its own _sp."""
    pending, key = _two_shader_variant_pending(editor, tmp_path, layer_shader, material_shader)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    assert not re.search(r'_name="(_detailMaterialMaskR|_materialTexture)"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_path=""', text)
    assert _variant_surface(files, 0, "_detailMaterialMaskR") == (0, 60, 250, 255)
    assert _variant_surface(files, 1, "_materialTexture") == (255, 120, 57, 255)


@pytest.mark.parametrize("layer_shader, material_shader", _VARIANT_SHADERS)
def test_a_chosen_surface_reaches_each_variant_by_its_own_shader(editor, tmp_path, layer_shader, material_shader):
    pending, key = _two_shader_variant_pending(editor, tmp_path, layer_shader, material_shader)
    files = prepare_imported_materials(pending, (key,), tmp_path, surface=(0.8, 0.25))
    assert _variant_surface(files, 0, "_detailMaterialMaskR") == (0, 204, 64, 255)
    assert _variant_surface(files, 1, "_materialTexture") == (255, 204, 64, 255)


@pytest.mark.parametrize("own_shader", ["SkinnedMeshHair", "SkinnedMeshAnimalHair", "SkinnedMeshEye"])
def test_an_untraced_variant_keeps_its_own_surface_beside_a_standard_one(editor, tmp_path, own_shader):
    """131 game files mix an untraced shader (hair, animal hair, an eye) and a
    traced one on the same part across variants, such as the mangalica pig. The
    untraced variant gets its own game _sp mean back; the other its own default."""
    pending, key = _two_shader_variant_pending(editor, tmp_path, own_shader, "SkinnedMeshStandard", "_materialTexture")
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    assert "_detailMaterialMaskR" not in text and "_colorBlendingFlag" not in text
    assert _variant_surface(files, 0, "_materialTexture") == (255, 60, 250, 255)
    assert _variant_surface(files, 1, "_materialTexture") == (255, 120, 57, 255)


def test_dependencies_include_the_textures_of_every_variant(editor, tmp_path):
    """The shared reference reader keeps one wrapper per part name, so 33005's
    variant-1 textures for cd_phm_00_ub_belt_0010_02 (its own _sp among them)
    were not captured and that variant fell back to 50% roughness and no metal."""
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader="SkinnedMeshStandard", surface=(120, 57))
    xml_entry = next(items[0] for path, items in context.entries_by_normalized_path.items() if path.endswith(".pac_xml"))
    body = xml_entry.paz_file.read_text().removeprefix("<Root>").removesuffix("</Root>")
    xml = ('<ModelPropertyList>' + ''.join(f'<ModelProperty Index="{index}">{text}</ModelProperty>' for index, text in (
        (0, body), (1, body.replace("original0_sp.dds", "variant1_sp.dds")))) + '</ModelPropertyList>').encode()
    own = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 140, 250, 255)).save(own, format="DDS")
    (tmp_path / "variant").mkdir()
    extra = [entry(tmp_path / "variant", xml_entry.path, xml), entry(tmp_path / "variant", "character/texture/variant1_sp.dds", own.getvalue())]
    for item in extra:
        context.entries_by_normalized_path[item.path.casefold()] = [item]
        context.entries_by_basename[Path(item.path).name.casefold()] = [item]
    dependencies = capture_replacement_dependencies(target, context)
    assert "character/texture/variant1_sp.dds" in {file.path for file in dependencies}
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    assert _variant_surface(files, 0, "_materialTexture") == (255, 120, 57, 255)
    assert _variant_surface(files, 1, "_materialTexture") == (255, 140, 250, 255)


def test_a_surface_is_never_bound_to_an_empty_path():
    from cdmw.core.pac_xml_surface_layer import apply_surface_layer
    text = ('<Root><SkinnedMeshMaterialWrapper _subMeshName="armour"><Material Name="_resourceMaterial" '
            '_materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters"></Vector></Material>'
            '</SkinnedMeshMaterialWrapper></Root>')
    with pytest.raises(ValueError, match="no material texture to write"):
        apply_surface_layer(text, {"armour"}, "", "material_sp.dds")


@pytest.mark.parametrize("shader", ["SkinnedMeshCloth_Ver2", "SkinnedMeshBlendHeight"])
def test_a_chosen_surface_replaces_the_default_and_zero_is_kept(editor, tmp_path, shader):
    """Moving a slider sets one uniform surface, 0% included: that is a choice now,
    not the default it used to fall back to."""
    parameter = "_materialTexture" if shader == "SkinnedMeshBlendHeight" else "_detailMaterialMaskR"
    pending, key = _surface_pending(editor, tmp_path, shader=shader, surface=(120, 57), surface_parameter=parameter)
    zero = prepare_imported_materials(pending, (key,), tmp_path, surface=(0.0, 0.0))
    assert _surface_binding(zero, parameter)[2][1:3] == (0, 0)
    assert _surface_binding(prepare_imported_materials(pending, (key,), tmp_path), parameter)[2][1:3] == (120, 57)


def test_an_eye_in_the_import_does_not_refuse_the_surface_for_the_body(editor, tmp_path):
    """A whole-wyvern import covers the eye (SkinnedMeshEye), and that greyed out
    Roughness and Metallic for every part. The eye keeps its own surface; the
    body takes the chosen one."""
    from cdmw.services.mesh_rust_replacement import (
        check_imported_surface_support, imported_material_status, imported_surface_support)
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader=("SkinnedMeshBlendHeight", "SkinnedMeshEye"),
                                              surface=(120, 57))
    model.write_text("mtllib import.mtl\nusemtl imported\nv 12 3 7\nv 16 3 7\nv 12 5 8\nvt 0 0\nvt 1 0\nvt 0 1\n"
                     "o body\nf 1/1 2/2 3/3\no eye\nf 1/1 3/3 2/2\n")
    dependencies = capture_replacement_dependencies(target, context)
    keys = tuple(part.part_id for part in initial_replacement_state(snapshot).parts)
    pending = prepare_import(snapshot, model, target_part_ids=keys, entry=target, dependencies=dependencies)
    assert imported_surface_support(pending) == ""
    assert imported_material_status(pending)["surface"]["unsupported"] == [keys[1]]
    files = prepare_imported_materials(pending, keys, tmp_path, surface=(0.6, 0.2))
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    body, eye = text.split('_subMeshName="target1"')
    assert re.search(r'_name="_materialTexture"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_cdmw_surface_153_051_sp\.dds', body)
    # The eye keeps its own surface: the mean of its game _sp, not the slider value
    # and not roughness 0, which the stripped texture would leave.
    assert "_cdmw_surface_153_051" not in eye
    assert re.search(r'_name="_materialTexture"[^>]*>\s*<ResourceReferencePath_ITexture[^>]*_cdmw_surface_255_120_057_sp\.dds', eye)
    # Mapped onto the eye alone, the sliders have nothing to set.
    with pytest.raises(ValueError, match="not available for this item's material shader"):
        check_imported_surface_support(pending, (keys[1],))
    check_imported_surface_support(pending, keys)


# AmplifiedGlare reads _materialTexture too, but no shipped wrapper of it declares one.
@pytest.mark.parametrize("shader", ["SkinnedMeshHair", "SkinnedMeshAmplifiedGlare"])
def test_roughness_and_metallic_refuse_materials_outside_the_traced_shaders(editor, tmp_path, shader):
    from cdmw.services.mesh_rust_replacement import imported_surface_support
    pending, key = _surface_pending(editor, tmp_path, shader=shader)
    assert "not available for this item's material shader" in imported_surface_support(pending)
    with pytest.raises(ValueError, match="not available for this item's material shader"):
        prepare_imported_materials(pending, (key,), tmp_path, surface=(0.5, 0.0))
    # Without a surface choice the import itself still works.
    assert prepare_imported_materials(pending, (key,), tmp_path)


@pytest.mark.parametrize("mtl, expected", [
    ("Pr 0.7\nPm 0.2\n", {"roughness": 0.7, "metallic": 0.2}),
    ("map_Pr rough.png\nmap_Pm metal.png\n", {"roughness": round(180 / 255, 3), "metallic": round(60 / 255, 3)}),
    ("", {"roughness": None, "metallic": None}),
])
def test_imported_surface_defaults_read_the_models_own_values(editor, tmp_path, mtl, expected):
    from cdmw.services.mesh_replacement_materials import imported_surface_defaults
    Image.new("RGB", (4, 4), (180, 180, 180)).save(tmp_path / "rough.png")
    Image.new("RGB", (4, 4), (60, 60, 60)).save(tmp_path / "metal.png")
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader="SkinnedMeshCloth_Ver2")
    model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\n" + mtl)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    assert imported_surface_defaults(pending) == expected


@pytest.mark.parametrize("mtl, expected", [
    # Blender's OBJ export of a DD2 helm named its mask texture for both maps.
    ("map_Pr mask.png\nmap_Pm mask.png\n", ["imported"]),
    ("map_Pr rough.png\nmap_Pm metal.png\n", []),
    ("Pr 0.5\nPm 0.5\n", []),
    ("", []),
])
def test_imported_surface_flags_one_texture_named_for_roughness_and_metallic(editor, tmp_path, mtl, expected):
    from cdmw.services.mesh_replacement_materials import imported_surface_shared_maps
    from cdmw.services.mesh_rust_replacement import imported_material_status
    for name in ("mask", "rough", "metal"):
        Image.new("RGB", (4, 4), (60, 120, 255)).save(tmp_path / f"{name}.png")
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader="SkinnedMeshCloth_Ver2")
    model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\n" + mtl)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    assert imported_surface_shared_maps(pending) == expected
    assert imported_material_status(pending)["surface"]["shared_maps"] == expected


def _snapshot_with_material_labels(snapshot, labels):
    from cdmw.modding.mesh_parser import parse_mesh

    raw = bytearray(snapshot.original_data)
    for index, label in enumerate(labels):
        name = f"target{index}".encode("ascii")
        assert len(label) == len(name)
        name_offset = raw.index(name)
        material_offset = raw.index(name, name_offset + len(name))
        raw[material_offset:material_offset + len(name)] = label.encode("ascii")
    data = bytes(raw)
    return replace(snapshot, original_data=data, mesh=parse_mesh(data, snapshot.mesh.path))


@pytest.mark.parametrize("labels", [("diffuse", "cloth__"), ("shared_", "shared_"), ("TARGET0", "TARGET1")])
def test_imported_materials_bind_part_wrappers_instead_of_embedded_labels(editor, tmp_path, labels):
    service, session_id = editor
    snapshot = _snapshot_with_material_labels(service.capture_export_snapshot(session_id), labels)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)

    files = prepare_imported_materials(pending, (key,), tmp_path)

    sidecar = next(file for file in files if file.path.endswith(".pac_xml"))
    text = sidecar.data.decode()
    assert "original0.dds" not in text
    assert "original1.dds" in text
    assert any(file.path.endswith(".dds") for file in files)


def test_imported_material_apply_matches_case_insensitive_target_bindings(editor, tmp_path):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.services.mesh_service import MeshService
    from tests.test_mesh_rust_replacement import command

    original_service, original_id = editor
    snapshot = original_service.capture_export_snapshot(original_id)
    data = snapshot.original_data.replace(b"target0", b"TARGET0").replace(b"target1", b"TARGET1")
    mesh = parse_mesh(data, snapshot.mesh.path)
    mesh._cdmw_original_data = data
    service = MeshService()
    session_id = service.open_edit_session(mesh).session_id
    host = None
    try:
        snapshot = service.capture_export_snapshot(session_id)
        target, context, model = material_fixture(tmp_path, snapshot)
        host = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=service, active_session_id=session_id),
            tmp_path / "host", process_generation=1,
        )
        key = initial_replacement_state(snapshot).parts[0].part_id
        command(host, "replacement_choose", {
            "scope": "selected", "part_ids": [key], "source_path": str(model),
            "_archive_entry": target, "_archive_dependencies": context,
        })
        result = command(host, "replacement_apply", {"targets": [key], "materials": "imported"})
        material_key = result["state"]["archive_refit_materials"]["key"]
        assert material_key != "base"
        textures = host.archive_refit_material_cache[material_key]["textures"]
        texture = next(row for row in textures if row["role"] == "base_color"
                       and 0 in row["material_indices_by_lod"][0])
        with Image.open(host.root / texture["file"]["path"]) as image:
            assert image.convert("RGBA").getpixel((0, 0)) == (210, 30, 60, 255)
        edited = host.shadow_service.working_mesh(host.shadow_session_id)
        assert [(part.name, part.material) for part in edited.submeshes] == [
            ("TARGET0", "TARGET0"), ("TARGET1", "TARGET1"),
        ]
    finally:
        if host is not None and not host.closed:
            host.cancel()
        service.close_edit_session(session_id)


def test_imported_materials_still_reject_a_genuinely_shared_wrapper(editor, tmp_path):
    import re

    service, session_id = editor
    snapshot = _snapshot_with_material_labels(service.capture_export_snapshot(session_id), ("target0", "target0"))
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    dependencies = tuple(replace(file, path=target.path.replace("/model/", "/modelproperty/") + "_xml", data=re.sub(
        r'<SkinnedMeshMaterialWrapper _subMeshName="target1">.*?</SkinnedMeshMaterialWrapper>', "",
        file.data.decode(), flags=re.S,
    ).replace("<Material>", '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard">').encode())
        if file.path.endswith(".pac_xml") else file for file in dependencies)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)

    with pytest.raises(ValueError, match="share a material with an untouched part"):
        prepare_imported_materials(pending, (key,), tmp_path)


def test_replacement_material_merge_matches_each_model_property_index():
    from cdmw.services.mesh_replacement_materials import _merge_material_rows

    def property_block(index, value, untouched):
        return (f'<ModelProperty Index="{index}"><SkinnedMeshProperty><Vector Name="_subMeshResources">'
                f'<SkinnedMeshMaterialWrapper _subMeshName="target0"><Material value="{value}"/></SkinnedMeshMaterialWrapper>'
                f'<SkinnedMeshMaterialWrapper _subMeshName="target1"><Material value="{untouched}"/></SkinnedMeshMaterialWrapper>'
                '</Vector></SkinnedMeshProperty></ModelProperty>')

    current = '<ModelPropertyList>' + property_block(0, "old0", "keep0") + property_block(3, "old3", "keep3") + '</ModelPropertyList>'
    donor = '<ModelPropertyList>' + property_block(3, "new3", "wrong3") + property_block(0, "new0", "wrong0") + '</ModelPropertyList>'
    expected = '<ModelPropertyList>' + property_block(0, "new0", "keep0") + property_block(3, "new3", "keep3") + '</ModelPropertyList>'

    merged, changed = _merge_material_rows(current, donor, {"target0"})

    assert changed
    assert merged == expected


@pytest.mark.parametrize("fault", ["duplicate-index", "missing-index", "missing-index-attribute", "duplicate-wrapper"])
def test_replacement_material_merge_refuses_ambiguous_property_variants(fault):
    from cdmw.services.mesh_replacement_materials import _merge_material_rows

    wrapper = '<SkinnedMeshMaterialWrapper _subMeshName="target0"><Material/></SkinnedMeshMaterialWrapper>'
    block = f'<ModelProperty Index="0">{wrapper}</ModelProperty>'
    current = f'<ModelPropertyList>{block}</ModelPropertyList>'
    if fault == "duplicate-index":
        donor = f'<ModelPropertyList>{block}{block}</ModelPropertyList>'
    elif fault == "missing-index":
        donor = current.replace('Index="0"', 'Index="1"')
    elif fault == "missing-index-attribute":
        donor = current.replace(' Index="0"', '')
    else:
        donor = current.replace(wrapper, wrapper + wrapper)

    with pytest.raises(ValueError, match="ambiguous|variants|unambiguous"):
        _merge_material_rows(current, donor, {"target0"})


def test_imported_materials_update_each_property_variant_and_preserve_untouched_wrappers(editor, tmp_path):
    from cdmw.core.material_shader_controls import material_variant_blocks

    service, session_id = editor
    snapshot = _snapshot_with_material_labels(service.capture_export_snapshot(session_id), ("diffuse", "cloth__"))
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    variants = {}
    for file in dependencies:
        if file.path.endswith(".pac_xml"):
            body = file.data.decode().removeprefix("<Root>").removesuffix("</Root>")
            variants[file.path] = ('<ModelPropertyList>' + ''.join(
                f'<ModelProperty Index="{index}">{body}</ModelProperty>' for index in (0, 3)
            ) + '</ModelPropertyList>').encode()
    dependencies = tuple(replace(file, data=variants.get(file.path, file.data)) for file in dependencies)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)

    files = prepare_imported_materials(pending, (key,), tmp_path)

    text = next(file.data.decode() for file in files if file.path.endswith(".pac_xml"))
    blocks = material_variant_blocks(text)
    assert len(blocks) == 2
    for block in blocks:
        assert "original0.dds" not in block.group()
        assert "original1.dds" in block.group()


@pytest.mark.parametrize("layout", ["space-name", "quoted-name", "nested", "nested-parent-reference",
                                   "multiple-libraries", "tabs-and-comment", "unicode-name", "quoted-hash-name"])
def test_obj_material_paths_resolve_declared_files_and_keep_their_pixels(editor, tmp_path, layout):
    from io import BytesIO
    from cdmw.services.mesh_replacement_output import prepare_replacement_output

    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    target, context, model = material_fixture(tmp_path, snapshot)
    nested = layout.startswith("nested")
    filename = {"unicode-name": "衣装素材.mtl", "quoted-hash-name": "#dress edit.mtl"}.get(layout, "dress edit.mtl")
    material = tmp_path / ("materials/dress.mtl" if nested else filename)
    material.parent.mkdir(exist_ok=True)
    model.with_suffix(".mtl").rename(material)
    declaration = material.relative_to(tmp_path).as_posix()
    if layout in {"quoted-name", "multiple-libraries", "tabs-and-comment", "quoted-hash-name"}:
        declaration = f'"{declaration}"'
    if layout == "multiple-libraries":
        (tmp_path / "unused.mtl").write_text("newmtl unused\nKd 1 1 1\n")
        declaration = f"unused.mtl {declaration}"
    directive = f"mtllib\t{declaration}\t# exported material" if layout == "tabs-and-comment" else f"mtllib {declaration}"
    model.write_text(model.read_text().replace("mtllib import.mtl", directive), encoding="utf-8")
    expected_color = (20, 50, 210, 255) if nested else (210, 30, 60, 255)
    if nested:
        # A different texture with the same filename beside the OBJ must not win.
        texture = tmp_path / ("images/color.dds" if layout == "nested-parent-reference" else "materials/color.dds")
        texture.parent.mkdir(exist_ok=True)
        Image.new("RGBA", (4, 4), expected_color).save(texture)
        if layout == "nested-parent-reference":
            material.write_text(material.read_text().replace("color.dds", "../images/color.dds"))
    else:
        texture = tmp_path / "color.dds"
    key = initial_replacement_state(snapshot).parts[0].part_id
    dependencies = capture_replacement_dependencies(target, context)
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    assert not pending.material_error
    slots = [Path(slot.source_texture_path) for part in pending.source.mesh.submeshes
             for slot in part.preview_material_texture_inputs if slot.slot_kind == "base"]
    assert slots == [texture.resolve()]
    captured = {Path(path) for path, digest in pending.material_source_files}
    assert {material.resolve(), texture.resolve()}.issubset(captured)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    candidate, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
    commit_replacement(service, snapshot, candidate, state, label="Import material paths")
    output = prepare_replacement_output(service.capture_export_snapshot(sid))
    textures = [file for file in output.companion_files if file.path.endswith(".dds")]
    assert len(textures) == 1
    with Image.open(BytesIO(textures[0].data)) as decoded:
        assert decoded.convert("RGBA").getpixel((0, 0)) == pytest.approx(expected_color, abs=4)
    before = service.session_view(sid)
    Image.new("RGBA", (4, 4), (10, 200, 40, 255)).save(texture)
    with pytest.raises(ValueError, match="dependency changed"):
        prepare_imported_materials(pending, (key,), tmp_path)
    after = service.session_view(sid)
    assert (after.revision, after.undo_count) == (before.revision, before.undo_count)
    after_output = prepare_replacement_output(service.capture_export_snapshot(sid))
    assert (after_output.data, after_output.companion_files) == (output.data, output.companion_files)


def test_nested_material_libraries_keep_same_named_textures_distinct_through_finish(editor, tmp_path):
    from io import BytesIO
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_mesh_rust_replacement import command

    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    target, context, model = material_fixture(tmp_path, snapshot)
    model.with_suffix(".mtl").unlink()
    source_files = [model]
    colors = ((210, 30, 60, 255), (20, 50, 210, 255))
    for name, color in zip(("red", "blue"), colors, strict=True):
        folder = tmp_path / name
        folder.mkdir()
        material, texture = folder / "shared.mtl", folder / "shared.dds"
        material.write_text(f"newmtl {name}\nKd 1 1 1\nmap_Kd shared.dds\n")
        Image.new("RGBA", (4, 4), color).save(texture)
        source_files.extend((material, texture))
    model.write_text("mtllib red/shared.mtl blue/shared.mtl\n"
        "v 12 3 7\nv 16 3 7\nv 12 5 7\nv -4 1 2\nv -2 1 2\nv -4 3 2\n"
        "vt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n"
        "o red\nusemtl red\nf 1/1/1 2/2/1 3/3/1\no blue\nusemtl blue\nf 4/1/1 5/2/1 6/3/1\n")
    keys = [part.part_id for part in initial_replacement_state(snapshot).parts]
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid),
                                           tmp_path / "host", process_generation=1)
    try:
        command(host, "replacement_choose", {"source_path": str(model), "_archive_entry": target, "_archive_dependencies": context})
        result = command(host, "replacement_apply", {"targets": keys, "materials": "imported"})
        material_key = result["state"]["archive_refit_materials"]["key"]
        staged = host.archive_refit_material_cache[material_key]["textures"]
        assert {index for row in staged for index in row["material_indices_by_lod"][0]} == {0, 1}
        output = prepare_replacement_output(host.shadow_service.capture_export_snapshot(host.shadow_session_id))
        files = {file.path: file.data for file in output.companion_files}
        assert len([path for path in files if path.endswith(".dds")]) == 2
        sidecar = next(file for file in output.companion_files if file.path.endswith(".pac_xml"))
        bindings = _parse_archive_model_sidecar_texture_bindings(sidecar.data.decode(), sidecar_path=sidecar.path)
        for index, color in enumerate(colors):
            binding = next(row for row in bindings if row.submesh_name == f"target{index}")
            with Image.open(BytesIO(files[binding.texture_path])) as decoded:
                assert decoded.convert("RGBA").getpixel((0, 0)) == pytest.approx(color, abs=4)
        for path in source_files:
            path.unlink()
        command(host, "undo")
        assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state is None
        assert command(host, "redo")["state"]["archive_refit_materials"]["key"] == material_key
        restored = prepare_replacement_output(host.shadow_service.capture_export_snapshot(host.shadow_session_id))
        assert (restored.data, restored.companion_files) == (output.data, output.companion_files)
        host.finish(_request(host, "finish_request", 99))
        finished = prepare_replacement_output(service.capture_export_snapshot(sid))
        assert (finished.data, finished.companion_files) == (output.data, output.companion_files)
    finally:
        if not host.closed:
            host.cancel()


@pytest.mark.parametrize("missing", ["library", "texture"])
def test_missing_material_dependencies_only_block_imported_materials(editor, tmp_path, missing):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    (model.with_suffix(".mtl") if missing == "library" else tmp_path / "color.dds").unlink()
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    with pytest.raises(ValueError, match=f"Missing imported {'material library' if missing == 'library' else 'texture'}"):
        prepare_imported_materials(pending, (key,), tmp_path)
    assert service.session_view(session_id).revision == snapshot.mesh_revision
    mesh, state = compose_import(pending, (key,), material_choice="original")
    assert [part.material for part in mesh.submeshes] == [part.material for part in snapshot.mesh.submeshes]
    assert list(mesh.submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
    assert list(mesh.submeshes[1].vertices) == list(snapshot.mesh.submeshes[1].vertices)
    assert not state.companion_files
    commit_replacement(service, snapshot, mesh, state, label="Keep original materials")
    rebuilt, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(session_id))
    from cdmw.modding.mesh_parser import parse_mesh
    assert report.validation_status == "passed"
    assert len(parse_mesh(rebuilt.data, state.target_path).submeshes) == 2


@pytest.mark.parametrize("changed", ["library", "texture", "geometry"])
def test_dependency_fingerprints_follow_material_choice(editor, tmp_path, changed):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    path = {"library": model.with_suffix(".mtl"), "texture": tmp_path / "color.dds", "geometry": model}[changed]
    path.write_bytes(path.read_bytes() + b"\nchanged")
    with pytest.raises(ValueError, match="dependency changed"):
        prepare_imported_materials(pending, (key,), tmp_path)
    if changed == "geometry":
        with pytest.raises(ValueError, match="dependency changed"):
            compose_import(pending, (key,))
    else:
        mesh, state = compose_import(pending, (key,))
        assert mesh.submeshes[0].material == snapshot.mesh.submeshes[0].material
        assert not state.companion_files
    assert service.session_view(session_id).revision == snapshot.mesh_revision


@pytest.mark.parametrize("extension", ["gltf", "glb"])
def test_missing_gltf_texture_is_optional_but_geometry_buffer_is_required(editor, tmp_path, extension):
    from tests.test_scene_import_normalization import _write_gltf
    from tests.test_scene_importer_gltf import _write_glb
    import json

    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    model = _write_gltf(tmp_path, positions=[(12, 3, 7), (16, 3, 7), (12, 5, 8)], indices=[0, 1, 2],
                        uvs=[(0, 0), (1, 0), (0, 1)],
                        material={"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}})
    if extension == "glb":
        document = json.loads(model.read_text())
        model = tmp_path / "external.glb"
        _write_glb(model, document, b"")
    (tmp_path / "texture.png").unlink()
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,))
    mesh, _ = compose_import(pending, (key,))
    assert mesh.submeshes[0].material == snapshot.mesh.submeshes[0].material
    with pytest.raises(ValueError, match="Missing imported dependency: texture.png"):
        prepare_imported_materials(pending, (key,), tmp_path)
    (tmp_path / "mesh.bin").unlink()
    with pytest.raises(ValueError, match="dependency changed"):
        compose_import(pending, (key,))
    with pytest.raises(ValueError, match="Missing imported dependency: mesh.bin"):
        prepare_import(snapshot, model, target_part_ids=(key,))


@pytest.mark.parametrize("extension", ["gltf", "glb"])
@pytest.mark.parametrize("change", ["modify", "delete"])
def test_external_geometry_buffer_changes_reject_pending_replacement(editor, tmp_path, extension, change):
    from tests.test_scene_import_normalization import _write_gltf
    from tests.test_scene_importer_gltf import _write_glb
    import json

    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    model = _write_gltf(tmp_path, positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                        uvs=[(0, 0), (1, 0), (0, 1)])
    if extension == "glb":
        document = json.loads(model.read_text())
        model = tmp_path / "external.glb"
        _write_glb(model, document, b"")
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,))
    buffer = tmp_path / "mesh.bin"
    if change == "modify":
        buffer.write_bytes(buffer.read_bytes() + b"changed")
    else:
        buffer.unlink()
    with pytest.raises(ValueError, match="dependency changed"):
        compose_import(pending, (key,))
    assert service.session_view(session_id).revision == snapshot.mesh_revision
    assert service.session_view(session_id).undo_count == 0


def test_repeated_imports_keep_other_materials_and_restore_original(editor, tmp_path):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    keys = [part.part_id for part in initial_replacement_state(snapshot).parts]
    for key in keys:
        snapshot = service.capture_export_snapshot(session_id)
        pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
        files = prepare_imported_materials(pending, (key,), tmp_path)
        mesh, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
        commit_replacement(service, snapshot, mesh, state, label="Import")
    assert len({file.path for file in files if file.path.endswith(".dds")}) == 2
    for key in keys:
        snapshot = service.capture_export_snapshot(session_id)
        pending = prepare_import(snapshot, model, target_part_ids=(key,))
        mesh, state = compose_import(pending, (key,))
        commit_replacement(service, snapshot, mesh, state, label="Original materials")
    assert state.companion_files == ()


@pytest.mark.parametrize("part_index", [0, 1])
@pytest.mark.parametrize("material_labels", [("target0", "target1"), ("target1", "target1"), ("target0", "target0")])
def test_material_preview_and_package_share_frozen_bundle(editor, tmp_path, part_index, material_labels, request):
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_rust_replacement import command
    import json
    service, session_id = editor
    snapshot = _snapshot_with_material_labels(service.capture_export_snapshot(session_id), material_labels)
    from cdmw.services.mesh_service import MeshService
    snapshot.mesh._cdmw_original_data = snapshot.original_data
    service = MeshService()
    session_id = service.open_edit_session(snapshot.mesh).session_id
    request.addfinalizer(lambda: service.close_edit_session(session_id))
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    sidecar_entry = context.entries_by_basename["replacement.pac_xml"][0]
    text = sidecar_entry.paz_file.read_text().replace(
        "<Material>", '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard">',
    ).replace("</Vector>", '<MaterialParameterTexture _name="_materialTexture" Index="1">'
              '<ResourceReferencePath_ITexture _path="character/texture/packed.dds"/>'
              '</MaterialParameterTexture></Vector>')
    prepared_sidecar = entry(tmp_path, sidecar_entry.path, text.encode())
    packed_path = tmp_path / "packed.dds"
    Image.new("RGBA", (4, 4), (128, 64, 192, 255)).save(packed_path)
    packed = entry(tmp_path, "character/texture/packed.dds", packed_path.read_bytes())
    for item in (prepared_sidecar, packed):
        context.entries_by_basename[Path(item.path).name.casefold()] = [item]
        context.entries_by_normalized_path[item.path.casefold()] = [item]
    sidecar = next(file for file in capture_replacement_dependencies(target, context) if file.path.endswith(".pac_xml"))
    bindings = _parse_archive_model_sidecar_texture_bindings(sidecar.data.decode(), sidecar_path=sidecar.path)
    # Archive preview retains the original parameter vector as well as textures.
    # Replacement must compile the new sidecar without those old DDS references.
    preview_parts = []
    for index, part in enumerate(snapshot.mesh.submeshes):
        binding = next(row for row in bindings if row.submesh_name == part.name and row.parameter_name == "_diffuseTexture")
        texture_path = context.entries_by_normalized_path[binding.texture_path][0].paz_file
        preview_parts.append(SimpleNamespace(source_submesh_index=index, material=part.material,
            preview_material_parameters=binding.material_parameters, preview_texture_dds_path=str(texture_path)))
    controller = SimpleNamespace(mesh_service=service, active_session_id=session_id,
        _cdmw_rust_mesh_preview_material_context=SimpleNamespace(
            preview_model=SimpleNamespace(path=snapshot.mesh.path, meshes=preview_parts)))
    host = RustMeshAuthoringSession.create(controller, tmp_path / "host", process_generation=1)
    try:
        chosen = command(host, "replacement_choose", {"scope": "selected", "part_ids": [initial_replacement_state(snapshot).parts[part_index].part_id],
                         "source_path": str(model), "_archive_entry": target, "_archive_dependencies": context})
        assert host.pending_replacement.snapshot.mesh.submeshes[part_index].preview_material_parameters
        key = chosen["state"]["replacement"]["pending"]["targets"][0]["id"]
        applied = command(host, "replacement_apply", {"targets": [key], "materials": "imported"})
        material_key = applied["state"]["archive_refit_materials"]["key"]
        assert material_key != "base"
        textures = host.archive_refit_material_cache[material_key]["textures"]
        assert textures and any(part_index in row["material_indices_by_lod"][0] for row in textures)
        texture = next(row for row in textures if row["role"] == "base_color"
                       and part_index in row["material_indices_by_lod"][0])
        with Image.open(host.root / texture["file"]["path"]) as image:
            assert image.convert("RGBA").getpixel((0, 0)) == (210, 30, 60, 255)
        assert command(host, "replacement_compare", {"mode": "original"})["state"]["archive_refit_materials"]["key"] == "base"
        assert command(host, "replacement_compare", {"mode": "output"})["state"]["archive_refit_materials"]["key"] == material_key
        command(host, "replacement_compare", {"mode": "edit"})
        command(host, "undo")
        assert command(host, "redo")["state"]["archive_refit_materials"]["key"] == material_key
        # Retry after the editor stopped: the folder rewritten for a new helper must be
        # one it opens (2026-11-24 audit: states piled up across Compare and Undo).
        from tests.editor_session_check import assert_editor_accepts
        host.rewrite_for_relaunch(3)
        assert_editor_accepts(host.manifest_path)
        # A Glow or colour edit stages a third material state (the file holds the edited
        # copy); the helper takes two, the original and the active one, so the third is
        # left out of the folder and forgotten, to be staged again when it is needed.
        from cdmw.services.mesh_rust_authoring import _atomic_write_payload
        extra_key = "f" * 32
        extra = {**host.archive_refit_material_cache[material_key], "key": extra_key}
        host.archive_refit_material_cache[extra_key] = extra
        host.archive_refit_material_references[extra_key] = _atomic_write_payload(
            host.root, f"material-state-{extra_key}.json", extra, data_type="mesh_materials_json",
            element_count=1, expected_root_identity=host.root_identity)
        host.rewrite_for_relaunch(4)
        assert_editor_accepts(host.manifest_path)
        assert {row["path"] for row in json.loads(host.manifest_path.read_text())["replacement_material_states"]} == {
            "material-state-base.json", f"material-state-{material_key}.json"}
        assert extra_key not in host.archive_refit_material_references
        assert not (host.root / f"material-state-{extra_key}.json").exists()
        from tests.test_mesh_rust_authoring_exact_output import _request
        host.finish(_request(host, "finish_request", 51))
        snapshot = service.capture_export_snapshot(session_id)
        bundle = service._replacement_output_for_snapshot(snapshot)
        # Output is self-contained after imported source files disappear.
        model.unlink()
        (tmp_path / "color.dds").unlink()
        draft = tmp_path / "draft" / "mesh_layers.json"
        service._session(session_id).mesh_layer_project_path = draft
        service.retry_mesh_layer_autosave(session_id)
        from cdmw.modding.mesh_parser import parse_mesh
        from cdmw.services.mesh_service import MeshService
        seed = parse_mesh(snapshot.original_data, snapshot.mesh.path)
        seed._cdmw_original_data = snapshot.original_data
        seed._cdmw_mesh_layer_project_path = str(draft)
        restored_service = MeshService()
        restored = restored_service.open_edit_session(seed)
        try:
            reopened = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=restored_service, active_session_id=restored.session_id),
                                                       tmp_path / "reopened-host", process_generation=2)
            try:
                # The editor checks the folder as CDMW leaves it before the editor starts.
                from tests.editor_session_check import assert_editor_accepts
                assert_editor_accepts(reopened.manifest_path)
                saved_key = reopened.state_payload()["archive_refit_materials"]["key"]
                assert saved_key == material_key
                assert reopened.archive_refit_material_cache[saved_key]["textures"]
                manifest = json.loads(reopened.manifest_path.read_text())
                assert manifest["textures"] == reopened.archive_refit_material_cache[saved_key]["textures"]
                assert manifest["material_presentations"] == reopened.archive_refit_material_cache[saved_key]["material_presentations"]
                references = manifest["replacement_material_states"]
                assert {row["path"] for row in references} == {
                    "material-state-base.json", f"material-state-{saved_key}.json"}
                import hashlib
                for row in references:
                    assert hashlib.sha256((reopened.root / row["path"]).read_bytes()).hexdigest().upper() == row["sha256"].upper()
                assert restored_service._replacement_output_for_snapshot(restored_service.capture_export_snapshot(restored.session_id)).data == bundle.data
            finally:
                reopened.cancel()
        finally:
            restored_service.close_edit_session(restored.session_id)
        worker = MeshDirectOutputWorker(1, service, session_id, target, kind="loose_mod", output_path=tmp_path / "mod")
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed
        assert (tmp_path / "mod" / target.path).read_bytes() == bundle.data
        for file in bundle.companion_files:
            assert (tmp_path / "mod" / file.path).read_bytes() == file.data
    finally:
        if not host.closed:
            host.cancel()


def test_replacement_build_button_and_companion_export_guard(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    from cdmw.domain.mesh.ui_state import MeshEditorUiState
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.ui.mesh_editor.tab import MeshEditorTab
    app = QApplication.instance() or QApplication([])
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    state = replace(initial_replacement_state(snapshot), companion_files=(ReplacementFile("object/test.pac_xml", b"<Root/>"),))
    service._session(session_id).replacement_state = state
    tab = MeshEditorTab(settings=owned_settings("ReplacementOutputControls"))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=session_id)
    tab.standalone_workspace.setEnabled(True)
    monkeypatch.setattr(tab, "_standalone_rebuild_allowed", lambda: True)
    try:
        tab._apply_mesh_editor_output_control_state(MeshEditorUiState(output_policy="replacement_game_asset"),
            has_standalone=True, has_archive_target=True, output_task_active=False)
        assert tab.standalone_build_mod_button.isEnabled()
        assert tab.standalone_run_validation_report_button.isEnabled()
        assert not tab.standalone_export_mesh_file_button.isEnabled()
        assert "companion" in tab.standalone_export_mesh_file_button.toolTip()
        service._session(session_id).replacement_state = replace(state, companion_files=())
        tab._apply_mesh_editor_output_control_state(MeshEditorUiState(output_policy="replacement_game_asset"),
            has_standalone=True, has_archive_target=True, output_task_active=False)
        assert tab.standalone_export_mesh_file_button.isEnabled()
        from cdmw.domain.mesh.physics_profile import PacPhysicsProfileRule
        rule = PacPhysicsProfileRule('0', 'Lower', 'character/descriptors/pbd/material/lower.xml',
                                     '0' * 64, (('Damping', 1.),))
        service._session(session_id).replacement_state = replace(state, companion_files=(),
            parts=tuple(replace(part, physics_profiles=(rule,)) for part in state.parts))
        tab._apply_mesh_editor_output_control_state(MeshEditorUiState(output_policy="replacement_game_asset"),
            has_standalone=True, has_archive_target=True, output_task_active=False)
        assert tab.standalone_build_mod_button.isEnabled()
        assert not tab.standalone_export_mesh_file_button.isEnabled()
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("shader", ["SkinnedMeshHair", "SkinnedMeshSkin", "SkinnedMeshAnisotropy"])
def test_untraced_creature_shaders_keep_the_mean_of_their_own_surface(editor, tmp_path, shader):
    """The import strips every material texture, so hair, skin and horse-coat parts
    read roughness 0. Their shaders are not traced, so they get their own game
    surface back as its R, G and B means, with the game row's ItemID."""
    pending, key = _surface_pending(editor, tmp_path, shader=shader, surface=(120, 57))
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    assert 'StringItemID="_materialTexture" ItemID="6"' in text.split('_subMeshName="target1"')[0]
    path, size, pixel = _surface_binding(files, "_materialTexture")
    assert path.endswith("_cdmw_surface_255_120_057_sp.dds") and pixel == (255, 120, 57, 255)


def test_imported_material_status_is_cached_per_pending_and_revision(monkeypatch):
    """The status parses the original PAC; UI refreshes reuse it until the import or mesh changes."""
    from types import SimpleNamespace
    import cdmw.services.mesh_rust_replacement as rust
    calls = []

    def build(pending):
        calls.append(pending.token)
        return {"error": "", "textures": 0, "helper_targets": ["a"]}

    monkeypatch.setattr(rust, "_build_imported_material_status", build)
    monkeypatch.setattr(rust, "_MATERIAL_STATUS_CACHE", {})
    pending = SimpleNamespace(token="t1", snapshot=SimpleNamespace(mesh_revision=1))
    first = rust.imported_material_status(pending)
    first["helper_targets"].append("mutated")
    assert rust.imported_material_status(pending)["helper_targets"] == ["a"]
    assert calls == ["t1"]
    rust.imported_material_status(SimpleNamespace(token="t1", snapshot=SimpleNamespace(mesh_revision=2)))
    rust.imported_material_status(SimpleNamespace(token="t2", snapshot=SimpleNamespace(mesh_revision=1)))
    assert calls == ["t1", "t1", "t2"]


@pytest.mark.parametrize("shader", ["SkinnedMeshCloth_Ver2", "SkinnedMeshStandard_Ver2"])
@pytest.mark.parametrize("surface", [None, (1.0, 0.0)])
def test_ver2_imports_bind_neutral_grey_detail_diffuse_for_overlay_colour(editor, tmp_path, shader, surface):
    """Ver2 shaders sample _detailDiffuseMaskR unconditionally before running
    _overlayColorTexture's overlay blend. When dropped it defaults to black,
    crushing dark/midtone pixels to black in game; neutral 0x80 grey keeps the
    imported colour uncrushed on both default and explicit surface exports."""
    pending, key = _surface_pending(editor, tmp_path, shader=shader)
    files = prepare_imported_materials(pending, (key,), tmp_path, surface=surface)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    replaced, untouched = text.split('_subMeshName="target1"')
    match = re.search(
        r'StringItemID="_detailDiffuseMaskR" ItemID="1028073018359806" _name="_detailDiffuseMaskR"[^>]*>'
        r'\s*<ResourceReferencePath_ITexture[^>]*_path="([^"]+)"',
        replaced,
    )
    assert match and match.group(1) == "texture/nonetexture0xff888888.dds"
    assert "_detailDiffuseMaskR" not in untouched


def test_ver2_neutral_diffuse_applies_only_to_ver2_variant_and_preserves_explicit_diffuse(editor, tmp_path):
    from cdmw.core.material_shader_controls import material_variant_blocks
    from cdmw.core.pac_xml_surface_layer import apply_surface_layer

    pending, key = _two_shader_variant_pending(editor, tmp_path, "SkinnedMeshStandard_Ver2", "SkinnedMeshStandard")
    files = prepare_imported_materials(pending, (key,), tmp_path)
    text = next(file for file in files if file.path.endswith(".pac_xml")).data.decode()
    variant0, variant1 = (block.group().split('_subMeshName="target1"')[0] for block in material_variant_blocks(text))
    assert "texture/nonetexture0xff888888.dds" in variant0 and "_detailDiffuseMaskR" in variant0
    assert "_detailDiffuseMaskR" not in variant1

    existing = (
        '<Root><SkinnedMeshMaterialWrapper _subMeshName="armour"><Material Name="_resourceMaterial" '
        '_materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
        '<MaterialParameterTexture StringItemID="_detailDiffuseMaskR" ItemID="1028073018359806" '
        '_name="_detailDiffuseMaskR" Index="0"><ResourceReferencePath_ITexture Name="_value" '
        '_path="character/texture/custom_diffuse.dds"/></MaterialParameterTexture>'
        '</Vector></Material></SkinnedMeshMaterialWrapper></Root>'
    )
    edited, changed = apply_surface_layer(existing, {"armour"}, "layer.dds", "material_sp.dds")
    assert changed == 1
    assert "character/texture/custom_diffuse.dds" in edited
    assert "texture/nonetexture0xff888888.dds" not in edited


@pytest.mark.parametrize("surface_args", [{}, {"roughness": 1.0, "metallic": 0.0}])
def test_ver2_replacement_apply_stages_preview_and_exports_with_neutral_diffuse(editor, tmp_path, surface_args, request):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.editor_session_check import assert_editor_accepts
    from tests.test_mesh_rust_replacement import command
    import json

    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot, shader="SkinnedMeshStandard_Ver2")
    sidecar_entry = context.entries_by_basename["replacement.pac_xml"][0]
    ver2_xml = sidecar_entry.paz_file.read_text().replace("_diffuseTexture", "_overlayColorTexture")
    prepared_sidecar = entry(tmp_path, sidecar_entry.path, ver2_xml.encode())
    context.entries_by_basename[Path(prepared_sidecar.path).name.casefold()] = [prepared_sidecar]
    context.entries_by_normalized_path[prepared_sidecar.path.casefold()] = [prepared_sidecar]

    host = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=session_id),
        tmp_path / "host",
        process_generation=1,
    )
    try:
        chosen = command(
            host,
            "replacement_choose",
            {
                "scope": "selected",
                "part_ids": [initial_replacement_state(snapshot).parts[0].part_id],
                "source_path": str(model),
                "_archive_entry": target,
                "_archive_dependencies": context,
            },
        )
        key = chosen["state"]["replacement"]["pending"]["targets"][0]["id"]
        applied = command(host, "replacement_apply", {"targets": [key], "materials": "imported", **surface_args})
        material_key = applied["state"]["archive_refit_materials"]["key"]
        assert material_key != "base"
        textures = host.archive_refit_material_cache[material_key]["textures"]
        base_texture = next(
            row for row in textures if row["role"] == "base_color" and 0 in row["material_indices_by_lod"][0]
        )
        with Image.open(host.root / base_texture["file"]["path"]) as image:
            assert image.convert("RGBA").getpixel((0, 0)) == (210, 30, 60, 255)

        assert command(host, "replacement_compare", {"mode": "original"})["state"]["archive_refit_materials"]["key"] == "base"
        assert command(host, "replacement_compare", {"mode": "output"})["state"]["archive_refit_materials"]["key"] == material_key
        command(host, "replacement_compare", {"mode": "edit"})
        command(host, "undo")
        assert command(host, "redo")["state"]["archive_refit_materials"]["key"] == material_key

        host.rewrite_for_relaunch(3)
        assert_editor_accepts(host.manifest_path)

        from tests.test_mesh_rust_authoring_exact_output import _request
        host.finish(_request(host, "finish_request", 51))
        snapshot = service.capture_export_snapshot(session_id)
        bundle = service._replacement_output_for_snapshot(snapshot)

        pac_xml_text = next(file for file in bundle.companion_files if file.path.endswith(".pac_xml")).data.decode()
        replaced_part, untouched_part = pac_xml_text.split('_subMeshName="target1"')
        assert '_name="_detailDiffuseMaskR"' in replaced_part
        assert "texture/nonetexture0xff888888.dds" in replaced_part
        assert "_detailDiffuseMaskR" not in untouched_part

        draft = tmp_path / "draft" / "mesh_layers.json"
        service._session(session_id).mesh_layer_project_path = draft
        service.retry_mesh_layer_autosave(session_id)
        seed = parse_mesh(snapshot.original_data, snapshot.mesh.path)
        seed._cdmw_original_data = snapshot.original_data
        seed._cdmw_mesh_layer_project_path = str(draft)
        restored_service = MeshService()
        restored = restored_service.open_edit_session(seed)
        try:
            reopened = RustMeshAuthoringSession.create(
                SimpleNamespace(mesh_service=restored_service, active_session_id=restored.session_id),
                tmp_path / "reopened-host",
                process_generation=2,
            )
            try:
                assert_editor_accepts(reopened.manifest_path)
                assert reopened.state_payload()["archive_refit_materials"]["key"] == material_key
                manifest = json.loads(reopened.manifest_path.read_text())
                assert {row["path"] for row in manifest["replacement_material_states"]} == {
                    "material-state-base.json",
                    f"material-state-{material_key}.json",
                }
            finally:
                reopened.cancel()
        finally:
            restored_service.close_edit_session(restored.session_id)

        mod_dir = tmp_path / "mod"
        worker = MeshDirectOutputWorker(1, service, session_id, target, kind="loose_mod", output_path=mod_dir)
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed
        assert (mod_dir / target.path).read_bytes() == bundle.data
        for file in bundle.companion_files:
            assert (mod_dir / file.path).read_bytes() == file.data
    finally:
        if not host.closed:
            host.cancel()
