"""Material colours: editing the colour rows a PAC material wrapper already declares."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.material_colours import rewrite_material_colours, wrapper_colours
from cdmw.domain.mesh.material_colours import material_colour_label, normalize_material_colours
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart
from cdmw.domain.mesh.shader_controls import ShaderControls
from cdmw.domain.pac_xml_editor import decode_pac_xml_payload

FIXTURE = (Path(__file__).parent / "fixtures/new_item_golden/character/modelproperty/1_pc/1_phm/weapon/"
           "1_onehandweapon/cd_phm_01_sword_0109.pac_xml")
TARGET = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0109.pac"
SIDECAR = "character/modelproperty/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0109.pac_xml"
HANDLE = "cd_phm_01_sword_handle_0109"
GUARD = "cd_phm_01_sword_guard_0109"


def _text():
    text, _ = decode_pac_xml_payload(FIXTURE.read_bytes())
    return text


def _two_variants(text):
    block = re.search(r"<ModelProperty\b[^>]*>.*?</ModelProperty>", text, re.S).group()
    second = block.replace('Index="0"', 'Index="1"', 1).replace('_value="#f7c6acff" Index="16"', '_value="#11223344" Index="16"', 1)
    return text.replace(block, block + "\n" + second, 1)


def test_only_the_rgb_of_the_named_rows_changes_and_alpha_case_and_bytes_are_kept():
    text = _text()
    edited = rewrite_material_colours(text, {HANDLE: {"_tintColorR": "#1A2B3C", "_tintColorG": "#000000"}})
    # The file writes lower-case hex; the alpha byte (eb on G) is kept.
    assert '_name="_tintColorR" _value="#1a2b3cff"' in edited
    assert '_name="_tintColorG" _value="#000000eb"' in edited
    changed = [(a, b) for a, b in zip(text.splitlines(), edited.splitlines()) if a != b]
    assert len(changed) == 2 and len(text) == len(edited)
    # The guard wrapper shares row names but is another material.
    assert wrapper_colours(edited)[0][GUARD.casefold()] == wrapper_colours(text)[0][GUARD.casefold()]


def test_every_model_variant_with_the_row_changes():
    text = _two_variants(_text())
    edited = rewrite_material_colours(text, {HANDLE: {"_tintColorR": "#ABCDEF"}})
    variants = wrapper_colours(edited)
    assert [variant[HANDLE.casefold()]["_tintColorR"] for variant in variants] == ["#abcdefff", "#abcdef44"]


def test_a_missing_row_or_wrapper_is_refused_and_no_row_is_added():
    text = _text()
    with pytest.raises(ValueError, match="no colour row named _overlayColor"):
        rewrite_material_colours(text, {HANDLE: {"_overlayColor": "#FFFFFF"}})
    with pytest.raises(ValueError, match="no wrapper for"):
        rewrite_material_colours(text, {"not_a_part": {"_tintColorR": "#FFFFFF"}})
    assert rewrite_material_colours(text, {}) == text


def test_colour_edits_are_validated_and_sorted():
    assert normalize_material_colours({"_tintColorG": "#abcdef", "_tintColorB": "#000000"}) == (
        ("_tintColorB", "#000000"), ("_tintColorG", "#ABCDEF"))
    for bad, message in (({"_tintColorR": "#ABCDEFFF"}, "#RRGGBB"), ({"_emissiveColor": "#FFFFFF"}, "Glow"),
                         ({"bad name": "#FFFFFF"}, "parameter"), ({}, "at least one"),
                         ([("_tintColorR", "#000000"), ("_TINTCOLORR", "#000000")], "twice")):
        with pytest.raises(ValueError, match=message):
            normalize_material_colours(bad)
    assert material_colour_label("_tintColorR") == "Tint (red mask)"
    assert material_colour_label("_customColour") == "_customColour"


def _state(**part):
    data = FIXTURE.read_bytes()
    parts = (ReplacementPart("p0", 0, **part), ReplacementPart("p1", 1))
    return MeshReplacementState(TARGET, "0" * 64, parts, dependencies=(ReplacementFile(SIDECAR, data),))


def _original():
    return SimpleNamespace(format="pac", submeshes=[SimpleNamespace(name=HANDLE, material=HANDLE),
                                                    SimpleNamespace(name=GUARD, material=GUARD)])


def test_build_mod_writes_the_colours_into_the_sidecar_with_its_bom():
    from cdmw.services.mesh_material_colours import build_material_colour_files

    state = _state(material_colours=(("_tintColorB", "#FF0000"),))
    files = build_material_colour_files(state, _original(), ())
    (sidecar,) = files
    assert sidecar.path.casefold() == SIDECAR.casefold() and sidecar.data.startswith(b"\xef\xbb\xbf")
    text, _ = decode_pac_xml_payload(sidecar.data)
    assert wrapper_colours(text)[0][HANDLE.casefold()]["_tintColorB"] == "#ff0000ff"
    assert b"\r\n" in sidecar.data


@pytest.mark.parametrize(("part", "message"), [
    ({"material_choice": "imported"}, "imported material"),
    ({"shader_controls": ShaderControls("SkinnedMeshGlass", rebuild=True)}, "rewrite"),
])
def test_conflicting_material_edits_are_refused(part, message):
    from cdmw.services.mesh_material_colours import material_colour_settings

    with pytest.raises(ValueError, match=message):
        material_colour_settings(_state(material_colours=(("_tintColorR", "#000000"),), **part), _original())


def test_parts_that_share_a_material_must_agree():
    from cdmw.services.mesh_material_colours import material_colour_settings

    state = _state(material_colours=(("_tintColorR", "#000000"),))
    shared = SimpleNamespace(format="pac", submeshes=[SimpleNamespace(name=HANDLE, material=HANDLE)] * 2)
    with pytest.raises(ValueError, match="same material colours"):
        material_colour_settings(state, shared)
    agreeing = replace(state, parts=tuple(replace(part, material_colours=(("_tintColorR", "#000000"),)) for part in state.parts))
    assert material_colour_settings(agreeing, shared) == {HANDLE.casefold(): {"_tintColorR": "#000000"}}


def test_the_draft_keeps_material_colours(tmp_path):
    from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state

    state = _state(material_colours=(("_tintColorR", "#123456"),))
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = save_replacement_state(state, tmp_path, generation)
    assert payload["version"] == 18 and payload["parts"][0]["material_colours"] == {"_tintColorR": "#123456"}
    assert load_replacement_state(payload, tmp_path).parts[0].material_colours == (("_tintColorR", "#123456"),)
    payload["version"] = 17
    with pytest.raises(ValueError, match="version 18"):
        load_replacement_state(payload, tmp_path)


def test_the_preview_retints_only_the_layers_the_edited_row_feeds():
    from cdmw.services.mesh_material_colours import recolour_preview_graph

    def layer(role, channel):
        return {"layer_role": role, "mask_channel": channel, "tint": [0.5, 0.5, 0.5, 0.25]}

    payload = {"preview_core_material_graph": {"materials": [
        {"lod_index": 0, "material_index": 0, "layers": [
            layer("grime", "r"), layer("detail", "r"), layer("detail", "g"), layer("base", "")]},
        {"lod_index": 0, "material_index": 1, "layers": [layer("grime", "r")]}]},
        "material_presentations": []}
    payload["preview_core_material_graph"]["materials"][0]["layers"][1]["scratch_tint"] = [0.0, 0.0, 0.0, 0.5]
    present = {"handle": ("_tintColorR", "_tintColorG", "_dyeingDetailLayerColorMaskG", "_scratchTintColorR")}
    recolour_preview_graph(payload, {(0, 0): "handle"}, present,
                           {"handle": {"_tintColorR": "#FF0000", "_tintColorG": "#00FF00", "_scratchTintColorR": "#0000FF"}})
    grime, detail_r, detail_g, base = payload["preview_core_material_graph"]["materials"][0]["layers"]
    assert grime["tint"] == [1.0, 0.0, 0.0, 0.25]
    # A detail layer reads the detail dye before the tint, so only R (no dye) follows it.
    assert detail_r["tint"] == [1.0, 0.0, 0.0, 0.25] and detail_r["scratch_tint"] == [0.0, 0.0, 1.0, 0.5]
    assert detail_g["tint"] == [0.5, 0.5, 0.5, 0.25]
    assert base["tint"] == [0.5, 0.5, 0.5, 0.25]  # "tintcolor" without a channel is not present
    assert payload["preview_core_material_graph"]["materials"][1]["layers"][0]["tint"] == [0.5, 0.5, 0.5, 0.25]


def test_panel_lists_each_parts_colour_rows_its_sharers_and_why_it_is_blocked():
    from cdmw.services.mesh_material_colours import material_colours_ui_state

    state = _state(material_choice="imported")
    session = SimpleNamespace(mesh_format="pac", hair_state=None, replacement_state=state)
    authoring = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(_session=lambda _id: session))
    replacement = {"reason": "", "parts": [{"index": 0, "id": "p0", "name": HANDLE}, {"index": 1, "id": "p1", "name": GUARD},
                                           {"index": 2, "id": "p2", "name": "copy"}]}
    rows = [{"kind": "Color", "name": "_tintColorG", "value": "#5f5858eb"},
            {"kind": "Color", "name": "_emissiveColor", "value": "#ffffffff"},
            {"kind": "Texture", "name": "_maskTexture", "value": "a.dds"},
            {"kind": "", "name": "_tintColorR", "value": "#f7c6acff"}]
    shader = {"parts": [{"id": "p0", "source": {"part": "handle"}, "authored": [{"rows": rows}]},
                        {"id": "p1", "source": {"part": "guard"}, "authored": []},
                        {"id": "p2", "source": {"part": "handle"}, "authored": [{"rows": rows}]}]}
    ui = material_colours_ui_state(authoring, replacement, shader)
    first, second, third = ui["parts"]
    assert ui["available"] is True
    # Known tints first, in R, G, B order; Glow's colour and textures are not listed.
    assert first["rows"] == [{"name": "_tintColorR", "label": "Tint (red mask)", "original": "#F7C6AC", "alpha": 255},
                             {"name": "_tintColorG", "label": "Tint (green mask)", "original": "#5F5858", "alpha": 235}]
    assert first["shared"] == ["p0", "p2"] and second["shared"] == ["p1"] and second["rows"] == []
    assert "imported materials" in first["blocked"] and second["blocked"] == "" and third["material_colours"] is None
    session.mesh_format = "pam"
    assert material_colours_ui_state(authoring, replacement, shader)["reason"].startswith("Material colours require a PAC")
