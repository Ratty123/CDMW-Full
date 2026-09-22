"""Skin glow prepares equipment-compatible maps through the actual authoring routes."""
from collections import OrderedDict
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.emission import EmissionChoice, GlowAnimation, RgbGlow
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.domain.new_item.spec import GlowChoice
from cdmw.services import new_item_template_materials as baking
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_variants import xml_path
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_translucency import sidecar
from tests.test_pac_xml_standard_material import HEAD, TAIL, GLOWING, texture, wrapper
from tests.test_static_skin_weight_export import _skinned_pac


HAND = "cd_phm_00_nude_02_0001_hand_damian"
MODEL = "character/model/hand.pac"
COLOUR = "character/texture/hand_d.dds"
GLOW = "character/texture/hand_e.dds"


@pytest.fixture(autouse=True)
def isolated_bakes(monkeypatch):
    monkeypatch.setattr(baking, "_BAKE_CACHE", OrderedDict())


def skin_files(*, part=HAND, model=MODEL, shader="SkinnedMeshSkin", base="_diffuseTexture", emissive=False):
    files = {model: _skinned_pac()[0]}
    maps = [(base, COLOUR, (160, 60, 20)),
            ("_normalTexture", "character/texture/hand_n.dds", (128, 200, 232)),
            ("_materialTexture", "character/texture/hand_sp.dds", (30, 180, 240))]
    if emissive:
        maps.append(("_emissiveIntensityTexture", GLOW, (90, 150, 220)))
    params = ""
    for index, (parameter, path, colour) in enumerate(maps):
        pixels = Image.new("RGB", (16, 16), colour)
        if path == COLOUR:
            pixels.paste((20, 60, 160), (8, 0, 16, 16))
        stream = BytesIO()
        pixels.save(stream, format="DDS")
        files[path] = stream.getvalue()
        params += texture(parameter, str(index), path, index)
    files[xml_path(model)] = (HEAD + wrapper(part, shader, params) + GLOWING + TAIL).encode()
    return files


def pixel(data, x=1):
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGB").getpixel((x, 1))


@pytest.mark.parametrize("shader,base,animation,rgb", [
    ("SkinnedMeshSkin", "_diffuseTexture", GlowAnimation(), None),
    ("SkinnedMeshSkin_Ver2", "_diffuseTexture", GlowAnimation(pulse_frequency=2), None),
    ("SkinnedMeshSkin", "_baseColorTexture", GlowAnimation(flow_u=.5), RgbGlow(.7, .4, .2)),
])
def test_template_skin_glow_exports_real_surface_maps_without_translucency(shader, base, animation, rgb):
    files = skin_files(shader=shader, base=base, emissive=rgb is not None)
    original = dict(files)
    source = SimpleNamespace(has_entry=files.__contains__, payload=files.__getitem__)
    result = prepare_template_model(source, (MODEL,),
        glow=GlowChoice((HAND,), (.25, .5, 1), 6, animation, rgb))
    text = result.side_files[xml_path(MODEL)].decode("utf-8-sig")
    row = find_material_wrappers(text)[0]
    assert row.shader == "SkinnedMeshEmissive"
    assert row.value("_thickness") is None and row.value("_extinctionCoefficient") is None
    assert GLOWING in text
    assert float(row.value("_emissiveFlickeringFreq")) == animation.pulse_frequency
    assert row.value("_emissiveColor") == "#4080FFFF"
    colour = result.side_files[row.textures["_baseColorTexture"]]
    for actual, expected in ((pixel(colour), (160, 60, 20)), (pixel(colour, 14), (20, 60, 160))):
        assert all(abs(a - e) <= 8 for a, e in zip(actual, expected)), (actual, expected)
    normal = pixel(result.side_files[row.textures["_normalTexture"]])
    assert normal[1] > 180, "the exported normal must keep its DirectX orientation"
    surface = pixel(result.side_files[row.textures["_materialTexture"]])
    assert surface[0] > 245 and abs(surface[1] - 180) <= 8 and surface[2] <= 2, surface
    if rgb is not None:
        assert row.textures["_emissiveProgressTexture"] == GLOW
        assert source.payload(GLOW) == original[GLOW]
        assert float(row.value("_emissiveProgressGauge")) == rgb.reveal
    else:
        assert row.textures["_emissiveIntensityTexture"] in result.side_files
        assert float(row.value("_emissiveIntensity")) == 6
    assert result.pac_data == original[MODEL]
    assert files == original


@pytest.mark.parametrize("failure", ["missing", "decode"])
def test_skin_glow_texture_errors_name_the_part_and_texture_without_translucency(monkeypatch, failure):
    files = skin_files()
    if failure == "missing":
        del files[COLOUR]
    else:
        monkeypatch.setattr("cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs", lambda *_a, **_k: {})
    original = dict(files)
    with pytest.raises(ValueError) as error:
        prepare_template_model(SimpleNamespace(has_entry=files.__contains__, payload=files.__getitem__),
                               (MODEL,), glow=GlowChoice((HAND,)))
    assert HAND in str(error.value) and COLOUR in str(error.value)
    assert "translucency" not in str(error.value).lower()
    assert files == original


def test_mesh_skin_glow_command_reuses_bakes_and_round_trips_restore_history_draft_finish(tmp_path, monkeypatch):
    original, service, session = _open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        source = sidecar(snapshot)
        source_text = source.data.decode()
        old = find_material_wrappers(source_text)[0]
        files = skin_files(part=old.submesh_name, model=snapshot.mesh.path)
        skin_text = files[source.path].decode()
        skin = find_material_wrappers(skin_text)[0]
        files[source.path] = (source_text[:old.start] + skin_text[skin.start:skin.end] + source_text[old.end:]).encode()
        captured = tuple(ReplacementFile(path, data) for path, data in files.items() if path != snapshot.mesh.path)
        key = session.state_payload()["emission"]["parts"][0]["id"]
        glow = EmissionChoice((.25, .5, 1), 6, GlowAnimation(pulse_frequency=2))
        incomplete = tuple(file for file in captured if file.path != COLOUR)
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *_: incomplete)
        with pytest.raises(ValueError, match="cannot prepare glow; missing texture"):
            command(session, "replacement_emission", {"part_ids": [key], "emission": glow.to_dict()})
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state is None
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *_: captured)
        changed = command(session, "replacement_emission", {"part_ids": [key], "emission": glow.to_dict()})
        presentation = session.archive_refit_material_cache[changed["state"]["archive_refit_materials"]["key"]]
        assert presentation["material_presentations"][0]["emissive_intensity"] == 6
        assert presentation["material_presentations"][0]["emission_animation"] == list(glow.animation.factors())
        state = session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state
        directory = tmp_path / "generation"
        directory.mkdir()
        assert load_replacement_state(save_replacement_state(state, tmp_path, directory), tmp_path) == state
        monkeypatch.setattr(baking, "_bake_material_maps", lambda *_: pytest.fail("unchanged skin maps were baked again"))
        command(session, "replacement_emission", {"part_ids": [key], "emission": replace(glow, intensity=8).to_dict()})
        command(session, "undo")
        assert session.state_payload()["emission"]["parts"][0]["emission"] == glow.to_dict()
        command(session, "undo")
        assert session.state_payload()["emission"]["parts"][0]["emission"] is None
        command(session, "redo")
        command(session, "replacement_emission", {"part_ids": [key], "reset": True})
        assert not prepare_replacement_output(session.shadow_service.capture_export_snapshot(session.shadow_session_id)).companion_files
        command(session, "undo")
        session.finish(_request(session, "finish_request", 22))
        result = prepare_replacement_output(service.capture_export_snapshot(session.authoritative_session_id))
        output = {file.path: file.data for file in result.companion_files}
        text = output[source.path].decode("utf-8-sig")
        rows = find_material_wrappers(text)
        assert rows[0].shader == "SkinnedMeshEmissive"
        assert all(path in output for name, path in rows[0].textures.items() if name in {
            "_baseColorTexture", "_normalTexture", "_materialTexture", "_emissiveIntensityTexture"})
        assert result.data == original
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
