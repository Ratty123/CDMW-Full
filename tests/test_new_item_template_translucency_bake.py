"""Layered template exports use real colours and maps, never a mask as albedo."""

from dataclasses import replace
from collections import OrderedDict
from io import BytesIO
from types import SimpleNamespace
import threading
import struct

from PIL import Image
import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.spec import GlowChoice
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_planning import NewItemPlanError
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_variants import xml_path
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import PAC, PAC_XML, _read, build_package
from tests.test_new_item_variant_authoring import selections
from tests.test_pac_xml_standard_material import HEAD, TAIL, GLOWING, texture, wrapper
from tests.test_static_skin_weight_export import _skinned_pac


BLADE = "cd_phm_02_sword_0003"
MASK = "character/texture/template_ma.dds"


@pytest.fixture(autouse=True)
def isolated_template_bakes(monkeypatch):
    from cdmw.services import new_item_template_materials
    monkeypatch.setattr(new_item_template_materials, "_BAKE_CACHE", OrderedDict())


def layered_inputs(shader="SkinnedMeshStandard_Ver2"):
    files = current_files()
    files[PAC] = _skinned_pac()[0]
    maps = [("_colorBlendingMaskTexture", MASK, (255, 0, 0)),
            ("_detailMaskTexture", "character/texture/template_mg.dds", (255, 0, 0)),
            ("_detailDiffuseMaskR", "character/texture/red_layer.dds", (200, 200, 200)),
            ("_detailDiffuseMaskB", "character/texture/blue_layer.dds", (200, 200, 200)),
            ("_detailMaterialMaskR", "character/texture/red_sp.dds", (255, 50, 240)),
            ("_detailMaterialMaskB", "character/texture/blue_sp.dds", (255, 200, 10)),
            ("_normalTexture", "character/texture/template_n.dds", (128, 200, 232)),
            ("_emissiveIntensityTexture", "character/texture/template_emi.dds", (64, 64, 64))]
    params = ""
    for index, (name, path, color) in enumerate(maps):
        image = Image.new("RGB", (16, 16), color)
        if name in {"_colorBlendingMaskTexture", "_detailMaskTexture"}:
            image.paste((0, 0, 255), (8, 0, 16, 16))
        stream = BytesIO()
        image.save(stream, format="DDS")
        files[path] = stream.getvalue()
        params += texture(name, str(index), path, index)
    for index, (kind, name, value) in enumerate([
        ("Color", "_dyeingDetailLayerColorMaskR", "#FF2020FF"),
        ("Color", "_dyeingDetailLayerColorMaskB", "#2020FFFF"),
        ("BitFlag32", "_colorBlendingFlag", "4095"),
        ("Byte4", "_dyeingGlobalOpacity", "16777215"),
        ("Color", "_emissiveColor", "#30CCFFFF"),
        ("Float", "_emissiveIntensity", "4"),
    ], len(maps)):
        params += f'<MaterialParameter{kind} StringItemID="{name}" ItemID="{index}" _name="{name}" _value="{value}" Index="{index}"/>\r\n'
    files[PAC_XML] = (HEAD + wrapper(BLADE, shader, params) + GLOWING + TAIL).encode()
    return files


@pytest.mark.parametrize("shader", [
    "SkinnedMeshStandard_Ver2", "SkinnedMeshEmissive_Ver2",
    "SkinnedMeshCloth_Ver2", "SkinnedMeshCloth", "SkinnedMeshFur_Ver2", "SkinnedMeshFur",
])
@pytest.mark.parametrize("variant,low_shine", [(False, False), (True, False), (False, True), (True, True)])
def test_build_plan_bakes_layered_template_and_keeps_other_materials(tmp_path, variant, low_shine, shader):
    files = layered_inputs(shader)
    original = dict(files)
    service = NewItemService()
    entries = parse_archive_pamt(build_package(tmp_path / "game", files))
    snapshot = service.build_snapshot(entries, read_entry=_read)
    choice = replace(spec(), translucency=TranslucencyChoice((BLADE,), 0.4, 0.6,
        surface_settings=((BLADE, 0.9, 0.0),) if low_shine else ()))
    if variant:
        binding = next(item for item in selections(snapshot) if item.model_path == PAC)
        choice = replace(choice, variants=(replace(binding, translucency=choice.translucency),))
    plan = service.plan(choice, snapshot)
    output = next(path for path in plan.loose_files if path.endswith(".pac"))
    xml = plan.loose_files[xml_path(output)].decode("utf-8-sig")
    row = find_material_wrappers(xml)[0]
    assert row.shader == "SkinnedMeshTranslucent"
    assert (float(row.value("_thickness")), float(row.value("_extinctionCoefficient"))) == (0.4, 0.6)
    assert GLOWING in xml
    assert row.textures["_emissiveIntensityTexture"] == "character/texture/template_emi.dds"
    assert row.value("_emissiveColor") == "#30CCFFFF"
    assert float(row.value("_emissiveIntensity")) == 4.0
    decoded = {}
    for role, param in (("base", "_baseColorTexture"), ("normal", "_normalTexture"), ("material", "_materialTexture")):
        data = plan.loose_files[row.textures[param]]
        with Image.open(BytesIO(data)) as image:
            decoded[role] = image.convert("RGB")
        assert data.startswith(b"DDS ")
        assert struct.unpack_from("<I", data, 28)[0] > 1
    base = decoded["base"]
    left, right = base.getpixel((1, 1)), base.getpixel((base.width - 2, 1))
    assert left[0] > left[2] + 50 and right[2] > right[0] + 50
    assert decoded["normal"].getpixel((1, 1))[1] > 180, "export restores DirectX normal orientation"
    surface = decoded["material"]
    left, right = surface.getpixel((1, 1)), surface.getpixel((surface.width - 2, 1))
    assert left[0] > 245 and right[0] > 245
    if low_shine:
        assert all(abs(pixel[1] - 230) <= 2 and pixel[2] <= 2 for pixel in (left, right))
    else:
        assert left[1] < right[1] - 100 and left[2] > right[2] + 100
    assert plan.loose_files[output] == original[PAC]
    assert any("layered template" in line for line in plan.summary_lines)
    for path, data in original.items():
        assert snapshot.payload(path) == data


@pytest.mark.parametrize("variant", [False, True])
def test_plan_reuses_template_maps_when_only_translucency_strength_changes(tmp_path, monkeypatch, variant):
    from cdmw.services import new_item_template_materials
    files = layered_inputs()
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "game", files)), read_entry=_read)
    choice = replace(spec(), translucency=TranslucencyChoice((BLADE,), 0.1, 0.3))
    if variant:
        binding = next(item for item in selections(snapshot) if item.model_path == PAC)
        choice = replace(choice, variants=(replace(binding, translucency=choice.translucency),))
    progress = []
    plan = service.plan(choice, snapshot, on_progress=lambda *values: progress.append(values))
    assert any("Compressing colour texture" in detail for _, _, detail in progress)
    assert any((current, total) == (1, 1) for current, total, _ in progress)
    assert progress[-1][2] == "Planning texture registry..."

    monkeypatch.setattr(new_item_template_materials, "_bake_material_maps",
        lambda *args, **kwargs: pytest.fail("an unchanged material was baked again"))
    glass = TranslucencyChoice((BLADE,), 0.8, 0.2)
    changed = replace(choice, translucency=glass,
        variants=(replace(choice.variants[0], translucency=glass),) if variant else None)
    progress.clear()
    rebuilt = service.plan(changed, snapshot, on_progress=lambda *values: progress.append(values))
    assert {p: v for p, v in plan.loose_files.items() if p.endswith(".dds")} == {
        p: v for p, v in rebuilt.loose_files.items() if p.endswith(".dds")}
    xml = next(data.decode("utf-8-sig") for path, data in rebuilt.loose_files.items() if path.endswith(".pac_xml"))
    row = find_material_wrappers(xml)[0]
    assert (float(row.value("_thickness")), float(row.value("_extinctionCoefficient"))) == (0.8, 0.2)
    assert any("Reusing prepared textures" in detail for _, _, detail in progress)
    assert snapshot.payload(PAC_XML) == files[PAC_XML]


@pytest.mark.parametrize("shader,parameter", [
    ("SkinnedMeshStandard", "_diffuseTexture"),
    ("SkinnedMeshCloth", "_diffuseTexture"),
    ("SkinnedMeshSkin", "_diffuseTexture"),
    ("SkinnedMeshHairStandard", "_diffuseTexture"),
    ("SkinnedMeshFur", "_albedoTexture"),
    ("SkinnedMeshEmissive", "_colorTexture"),
    ("StaticMeshStandard", "_diffuseTexture"),
    ("EquipmentSurface", "_albedoTexture"),
])
def test_template_bake_uses_declared_colour_inputs_across_shader_families(shader, parameter):
    files = layered_inputs()
    colour_path = "character/texture/template_colour.dds"
    colour = Image.new("RGBA", (16, 16), (160, 60, 20, 70))
    colour.paste((20, 60, 160, 210), (8, 0, 16, 16))
    stream = BytesIO()
    colour.save(stream, format="DDS")
    files[colour_path] = stream.getvalue()
    params = texture(parameter, "0", colour_path, 0)
    params += texture("_normalTexture", "1", "character/texture/template_n.dds", 1)
    params += texture("_emissiveIntensityTexture", "2", "character/texture/template_emi.dds", 2)
    part = "cd_m0001_00_death_knight_hel_0001_02"
    files[PAC_XML] = (HEAD + wrapper(part, shader, params) + GLOWING + TAIL).encode()
    original = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)

    result = prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((part,), 0.4, 0.6))

    xml = result.side_files[PAC_XML].decode("utf-8-sig")
    row = find_material_wrappers(xml)[0]
    assert row.shader == "SkinnedMeshTranslucent"
    assert GLOWING in xml
    assert row.textures["_emissiveIntensityTexture"] == "character/texture/template_emi.dds"
    data = result.side_files[row.textures["_baseColorTexture"]]
    assert data[84:88] == b"DX10" and struct.unpack_from("<I", data, 128)[0] == 98, "BC7_UNORM"
    with Image.open(BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        for actual, expected in ((rgba.getpixel((1, 1)), (160, 60, 20, 70)),
                                 (rgba.getpixel((rgba.width - 2, 1)), (20, 60, 160, 210))):
            assert all(abs(a - e) <= 8 for a, e in zip(actual, expected)), (actual, expected)
    assert result.pac_data == original[PAC]
    assert files == original


def test_cloth_template_bakes_authored_layers_when_base_is_a_placeholder():
    files = layered_inputs("SkinnedMeshCloth_Ver2")
    placeholder = texture("_baseColorTexture", "100", "engine/texture/NoneTexture.dds", 100)
    files[PAC_XML] = files[PAC_XML].replace(b'<Vector Name="_parameters">',
        b'<Vector Name="_parameters">' + placeholder.encode(), 1)
    original = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)

    result = prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)))

    xml = result.side_files[PAC_XML].decode("utf-8-sig")
    row = find_material_wrappers(xml)[0]
    assert row.shader == "SkinnedMeshTranslucent"
    assert row.textures["_baseColorTexture"] in result.side_files
    with Image.open(BytesIO(result.side_files[row.textures["_baseColorTexture"]])) as image:
        red, _, blue, _ = image.convert("RGBA").getpixel((1, 1))
        assert red > blue + 50
    assert GLOWING in xml
    assert files == original


@pytest.mark.parametrize("enabled", [False, True])
def test_template_without_colour_inputs_is_only_blocked_for_selected_translucency(enabled):
    files = layered_inputs("SkinnedMeshCloth_Ver2")
    params = texture("_normalTexture", "0", "character/texture/template_n.dds", 0)
    files[PAC_XML] = (HEAD + wrapper(BLADE, "SkinnedMeshCloth_Ver2", params) + GLOWING + TAIL).encode()
    original = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)

    if enabled:
        with pytest.raises(NewItemPlanError, match=f"{BLADE}:.*could not produce a base colour texture"):
            prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)))
    else:
        result = prepare_template_model(snapshot, [PAC])
        assert result.pac_data == original[PAC]
        assert result.side_files == {}
    assert files == original


def test_baked_template_glow_override_retains_source_mask():
    files = layered_inputs()
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)
    result = prepare_template_model(snapshot, [PAC],
        translucency=TranslucencyChoice((BLADE,)), glow=GlowChoice((BLADE,), (1, 0, 0), 7))
    row = find_material_wrappers(result.side_files[PAC_XML].decode("utf-8-sig"))[0]
    assert row.shader == "SkinnedMeshTranslucent"
    assert row.textures["_emissiveIntensityTexture"] == "character/texture/template_emi.dds"
    assert row.value("_emissiveColor").lower() == "#ff0000ff"
    assert float(row.value("_emissiveIntensity")) == 7


@pytest.mark.parametrize("shader", ["SkinnedMeshStandard_Ver2", "SkinnedMeshCloth_Ver2"])
def test_missing_layer_texture_reports_part_and_path_without_changing_source(shader):
    files = layered_inputs(shader)
    del files[MASK]
    original = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)
    with pytest.raises(NewItemPlanError, match=f"{BLADE}:.*missing texture {MASK}"):
        prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)))
    assert files == original


def test_cancelled_template_bake_does_not_read_archives():
    stop = threading.Event()
    stop.set()
    snapshot = SimpleNamespace(payload=lambda _: pytest.fail("cancelled plan read the archives"))
    with pytest.raises(RunCancelled):
        prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)), stop_event=stop)


@pytest.mark.parametrize("failure", ["decode", "encode"])
def test_texture_failure_reports_the_affected_part(monkeypatch, failure):
    from cdmw.core import texture_native

    files = layered_inputs()
    original = dict(files)
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)
    if failure == "decode":
        monkeypatch.setattr(texture_native, "ensure_directxtex_dds_preview_pngs", lambda *_args, **_kwargs: {})
        expected = f"{BLADE}: cannot decode translucency texture {MASK}"
    else:
        monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", lambda *_args, **_kwargs: None)
        expected = f"{BLADE}: could not encode the base texture"
    with pytest.raises(NewItemPlanError, match=expected):
        prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)))
    assert files == original
