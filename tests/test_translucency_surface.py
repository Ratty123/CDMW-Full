"""Real DDS output for surface edits, shared by template/import and Mesh Editor."""

from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import struct
import threading

from PIL import Image
import pytest

from cdmw.core.pac_xml_standard_material import PlainMaterial, plain_material_xml, find_material_wrappers
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh.translucency import translucency_surface_values
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_translucency import apply_prebuilt_translucency, selected_translucency
from cdmw.services.new_item_materials import SourceMaterialTextures, route_plain_pbr
from cdmw.services.translucency_surface import apply_translucency_surface

PAC = "character/model/surface_test.pac"
XML = "character/modelproperty/surface_test.pac_xml"
SP = "character/texture/shared_sp.dds"


def source_files():
    image = Image.new("RGBA", (8, 8), (80, 50, 220, 190))
    image.paste((160, 100, 120, 220), (4, 0, 8, 8))
    stream = BytesIO()
    image.save(stream, format="DDS")
    xml = "<root>" + "".join(
        f'<SkinnedMeshMaterialWrapper _subMeshName="{name}">' + plain_material_xml(PlainMaterial(
            base="character/texture/base.dds", normal="character/texture/normal.dds", material=SP,
            emissive_texture="character/texture/glow.dds", emissive_color="#12AAFFFF", emissive_intensity=4))
        + '</SkinnedMeshMaterialWrapper>' for name in ("Blade", "Gem")) + "</root>"
    return ModelFiles(pac_data=b"untouched PAC", side_files={XML: xml.encode(), SP: stream.getvalue(),
        "character/texture/base.dds": stream.getvalue(), "character/texture/normal.dds": stream.getvalue(),
        "character/texture/glow.dds": stream.getvalue()})


@pytest.mark.parametrize("route", ["template", "prebuilt", "import"])
def test_export_surface_is_private_keeps_other_inputs_and_matches_channels(route, tmp_path):
    files = source_files()
    choice = TranslucencyChoice.from_settings({"Blade": (.4, .6)}, {"Blade": (.9, 0.0)})
    original = dict(files.side_files)
    expected = files
    if route == "template":
        snapshot = SimpleNamespace(payload=lambda path: files.pac_data if path == PAC else files.side_files[path],
                                   has_entry=files.side_files.__contains__)
        output = prepare_template_model(snapshot, (PAC,), translucency=choice)
    elif route == "prebuilt":
        output = apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, choice)
    else:
        source = tmp_path / "surface.png"
        Image.open(BytesIO(files.side_files[SP])).save(source)
        sources = {name.casefold(): SourceMaterialTextures(name, material=source) for name in ("Blade", "Gem")}
        expected = route_plain_pbr(files, sources=sources).files
        output = route_plain_pbr(files, translucency=choice, sources=sources).files
    before = find_material_wrappers(expected.side_files[XML].decode())
    after = find_material_wrappers(output.side_files[XML].decode())
    assert output.pac_data == files.pac_data
    assert files.side_files == original
    assert after[0].shader == "SkinnedMeshTranslucent"
    assert after[0].value("_thickness") == "0.400000"
    assert after[0].value("_extinctionCoefficient") == "0.600000"
    for key in ("_baseColorTexture", "_emissiveIntensityTexture"):
        if key not in before[0].textures:
            assert key not in after[0].textures
            continue
        assert after[0].textures[key] == before[0].textures[key]
        assert output.side_files.get(after[0].textures[key], original[after[0].textures[key]]) == original[before[0].textures[key]]
    assert after[0].value("_emissiveColor") == before[0].value("_emissiveColor")
    assert after[0].value("_emissiveIntensity") == before[0].value("_emissiveIntensity")
    path = after[0].textures["_materialTexture"]
    assert path != after[1].textures["_materialTexture"] and "/texture/" in path
    if route != "import":
        text = output.side_files[XML].decode()
        assert text[after[1].start:after[1].end] == files.side_files[XML].decode()[before[1].start:before[1].end]
        assert output.side_files.get(SP, original[SP]) == original[SP]
    payload = output.side_files[path]
    assert struct.unpack_from("<I", payload, 28)[0] == 4  # complete 8x8 mip chain
    with Image.open(BytesIO(payload)) as image:
        for point in ((1, 1), (6, 1)):
            pixel = image.getpixel(point)
            assert abs(pixel[1] - 230) <= 2 and pixel[2] <= 2


def test_partial_override_keeps_unedited_channels_and_never_mutates_shared_map():
    files = source_files()
    text, generated = apply_translucency_surface(files.side_files[XML].decode(), {"blade": (.1, .3)},
        {"Blade": (.8, None)}, PAC, files.side_files.get)
    row = find_material_wrappers(text)[0]
    with Image.open(BytesIO(generated[row.textures["_materialTexture"]])) as image, Image.open(BytesIO(files.side_files[SP])) as source:
        for point in ((1, 1), (6, 1)):
            actual, before = image.getpixel(point), source.getpixel(point)
            assert abs(actual[1] - 204) <= 2
            assert all(abs(actual[i] - before[i]) <= 3 for i in (0, 2, 3))


def test_mesh_editor_f32_and_new_item_decimal_encode_the_same_surface():
    files = source_files()
    outputs = []
    for roughness in (.9, struct.unpack("<f", struct.pack("<f", .9))[0]):
        _, generated = apply_translucency_surface(files.side_files[XML].decode(), {"Blade": (.4, .6)},
            {"Blade": (roughness, 0)}, PAC, files.side_files.get)
        outputs.append(next(iter(generated.values())))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("value", [[True, 0], [-1, 0], [None, 2], [float("nan"), 0], ["0.9", 0], [], [0.5]])
def test_invalid_surface_values_rejected(value):
    with pytest.raises(ValueError, match="surface requires"):
        translucency_surface_values(value)


def test_source_surface_needs_no_texture_work_and_failures_are_specific():
    files = source_files()
    original = files.side_files[XML].decode()
    def no_read(_):
        pytest.fail("surface defaults must not decode or re-encode textures")
    _, generated = apply_translucency_surface(original, {"Blade": (.1, .3)}, {}, PAC, no_read)
    assert generated == {}
    with pytest.raises(ValueError, match="Blade:.*missing material texture"):
        apply_translucency_surface(original, {"Blade": (.1, .3)}, {"Blade": (.9, 0)}, PAC, lambda _: None)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        apply_translucency_surface(original, {"Blade": (.1, .3)}, {"Blade": (.9, 0)}, PAC, no_read, stop_event=stop)


def test_surface_conflicts_in_shared_atlas_are_rejected():
    choice = TranslucencyChoice.from_settings({"Blade": (.1, .3), "Gem": (.1, .3)}, {"Blade": (.9, 0)})
    atlas = SourceMaterialTextures("Combined", atlas_sources=(SourceMaterialTextures("Blade"), SourceMaterialTextures("Gem")))
    with pytest.raises(ValueError, match="different surface settings"):
        selected_translucency(choice, "Combined", atlas)


@pytest.mark.parametrize("prebuilt", [False, True])
def test_import_surface_cancellation_reaches_the_conversion_boundary(monkeypatch, prebuilt):
    import cdmw.services.new_item_materials as materials
    files = source_files()
    stop = threading.Event()
    choice = TranslucencyChoice.from_settings({"Blade": (.1, .3)}, {"Blade": (.9, 0)})
    def no_encode(*args, **kwargs):
        pytest.fail("A cancelled surface operation must not reach the encoder")
    monkeypatch.setattr("cdmw.services.translucency_surface._encode_surface", no_encode)
    if prebuilt:
        stop.set()
        with pytest.raises(RunCancelled):
            apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, choice, stop_event=stop)
    else:
        finish = materials._finish_plain_pbr_route
        def cancel_after_route(**kwargs):
            result = finish(**kwargs)
            stop.set()
            return result
        monkeypatch.setattr(materials, "_finish_plain_pbr_route", cancel_after_route)
        with pytest.raises(RunCancelled):
            route_plain_pbr(files, translucency=choice, stop_event=stop)


def test_rgb_glow_encoding_receives_the_cancel_event(tmp_path, monkeypatch):
    from cdmw.services.new_item_materials import encode_rgb_emissive
    source = tmp_path / "glow.png"
    Image.new("RGBA", (4, 4), (255, 30, 10, 255)).save(source)
    stop = threading.Event()
    def encode(*args, stop_event=None, **kwargs):
        assert stop_event is stop
        stop.set()
        raise RunCancelled()
    monkeypatch.setattr("cdmw.core.texture_native.encode_dds_with_directxtex", encode)
    with pytest.raises(RunCancelled):
        encode_rgb_emissive(source, stop_event=stop)
