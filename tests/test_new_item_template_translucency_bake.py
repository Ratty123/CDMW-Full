"""Layered template exports use real colours and maps, never a mask as albedo."""

from dataclasses import replace
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


def layered_inputs():
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
    files[PAC_XML] = (HEAD + wrapper(BLADE, "SkinnedMeshStandard_Ver2", params) + GLOWING + TAIL).encode()
    return files


@pytest.mark.parametrize("variant", [False, True])
def test_build_plan_bakes_layered_template_and_keeps_other_materials(tmp_path, variant):
    files = layered_inputs()
    original = dict(files)
    service = NewItemService()
    entries = parse_archive_pamt(build_package(tmp_path / "game", files))
    snapshot = service.build_snapshot(entries, read_entry=_read)
    choice = replace(spec(), translucency=TranslucencyChoice((BLADE,), 0.4, 0.6))
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
    assert left[1] < right[1] - 100 and left[2] > right[2] + 100
    assert plan.loose_files[output] == original[PAC]
    assert any("layered template" in line for line in plan.summary_lines)
    for path, data in original.items():
        assert snapshot.payload(path) == data


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


def test_missing_layer_texture_reports_part_and_path_without_changing_source():
    files = layered_inputs()
    del files[MASK]
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=files.__contains__)
    with pytest.raises(NewItemPlanError, match=f"{BLADE}:.*missing texture {MASK}"):
        prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)))


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
