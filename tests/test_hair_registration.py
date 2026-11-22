"""Additive registration and opaque clone preservation, without game assets."""

from dataclasses import replace
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord, PartPrefabTable, encode_pappt, parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.hair_registration import HairRegistrationError, append_hair_choice, read_hair_choices
from cdmw.services.hair_registration import DAMIANE_MESH_PARAM, PART_PREFAB_TABLE, prepare_damiane_hair_registration
from tests.test_prefab_binary_edit import _build
from tools.dotnet_archive_backend.probe_hair_registration import collect_lookup_entries, select_active_entry


STEM = "cd_phw_00_hair_00_0008_01_player"
NEW = "cd_phw_00_hair_00_9000_01_player"
MESH = f"character/model/1_pc/2_phw/head/hair/{STEM}.pac"
ICON = "ui/texture/image/customizeimage/hair.dds"
XML = (b'\xef\xbb\xbf<!-- retained </ParamDesc> comment -->\r\n<MeshParam>\r\n'
       b'<ParamDesc Index="0" Default="0" />\r\n'
       b'<ParamDesc Index="2" Default="0" UIKey="hairShape">\r\n'
       b'<MeshSet Index="0" DecorationParamIndex="0 1" MinValue="40 50" FutureField="keep">'
       + f'<MeshList MeshFileName="{STEM}" IconPath="{ICON}"/></MeshSet>\r\n'.encode()
       + b'</ParamDesc>\r\n<ParamDesc Index="3" Default="0" /></MeshParam>')


def fixture(*, stem=STEM, slot="CD_Hair"):
    mesh = MESH.replace(STEM, stem)
    record = PartPrefabRecord(stem, "1_pc/02_phw/head/hair", "", flag=0, parts=(PartPrefabPart(slot),))
    table = PartPrefabTable((record,), tag_prefix=b"\x01")
    files = {
        DAMIANE_MESH_PARAM: XML.replace(STEM.encode(), stem.encode()),
        PART_PREFAB_TABLE: encode_pappt(table),
        record.prefab_path: _build(mesh),
        mesh: b"opaque source mesh with all LODs and skin lanes",
        mesh.replace("character/model/", "character/modelproperty/") + "_xml": b"authored material, opacity and PBD binding",
        mesh.replace("character/model/", "character/bin__/meshphysics/")[:-4] + ".hkx": b"opaque physics",
        ICON: b"authored DDS",
    }
    return files


@pytest.mark.parametrize("resources,reason", [([MESH, MESH.replace("00_0008", "uptail_0008")], "multiple PAC"),
                                            ([MESH.replace("_player.pac", ".pac")], "different PAC")])
def test_prefab_donor_gate_explains_multi_mesh_and_alias_choices(monkeypatch, resources, reason):
    from cdmw.services import hair_registration
    monkeypatch.setattr(hair_registration, "decode_prefab_binary", lambda data:
        SimpleNamespace(resource_strings=lambda: [SimpleNamespace(text=path) for path in resources]))
    with pytest.raises(HairRegistrationError, match=reason):
        hair_registration.validate_hair_prefab_donor(b"prefab", MESH)


@pytest.mark.parametrize("slot", ["Hair", "CD_Hair"])
def test_the_hair_slot_is_accepted_in_both_namings_and_cloned_as_spelled(slot):
    # `Hair` since the October 2026 update, `CD_Hair` in tables extracted before it.
    plan = prepare_damiane_hair_registration(fixture(slot=slot), new_stem=NEW, existing_paths=())
    table = parse_pappt(dict((item.path, item.data) for item in plan.replacements)[PART_PREFAB_TABLE])
    assert [part.name for part in table.records[-1].parts] == [slot]
    assert table.records[-1].stem == NEW


def test_a_template_in_another_slot_is_refused():
    with pytest.raises(HairRegistrationError, match="one Hair prefab record"):
        prepare_damiane_hair_registration(fixture(slot="Hair_Tail"), new_stem=NEW, existing_paths=())


# The game's own tables as found on 1.0.0.3663: the hair slot carries no
# Default, hairstyles the barber hides are marked ShowInGame="False" and have no
# icon, and two of Damiane's hidden names are written in mixed case.
OTHER = "phw_00_hair_00_0507_player"
OTHER_ICON = "ui/texture/image/customizeimage/CD_Itemicon_Barbershop_cd_phw_00_hair_00_0507.dds"


def shown(index, stem=OTHER, icon=OTHER_ICON):
    return (f'<MeshSet Index="{index}" DecorationParamIndex="0" MinValue="70">\r\n'
            f'<MeshList MeshFileName="{stem}" IconPath="{icon}"/>\r\n</MeshSet>\r\n')


def hidden(index, stem):
    return (f'<MeshSet Index="{index}" DecorationParamIndex="0" MinValue="100" ShowInGame="False">\r\n'
            f'<MeshList MeshFileName="{stem}"/>\r\n</MeshSet>\r\n')


def game_table(*sets, slot='Index="2" UIKey="Hair" Category="Hair" Match="_hair_"'):
    return ('﻿<!-- 2: Hair </ParamDesc> -->\r\n<MeshParam>\r\n<ParamDesc Index="0" UIKey="Body"></ParamDesc>\r\n'
            f'<ParamDesc {slot}>\r\n' + "".join(sets) + '</ParamDesc>\r\n'
            '<ParamDesc Index="3" UIKey="Beard"></ParamDesc>\r\n</MeshParam>').encode("utf-8")


def test_hairstyles_the_barber_hides_have_no_icon_and_are_still_listed():
    slot = 'Index="2" Default="0" UIKey="Hair"'
    choices = read_hair_choices(game_table(shown(0), hidden(1, "phw_00_hair_00_0001"), slot=slot))
    assert [(c.index, c.prefab_stem, c.icon_path, c.shown_in_game) for c in choices] == [
        (0, OTHER, OTHER_ICON, True), (1, "phw_00_hair_00_0001", "", False)]
    assert all(choice.usable for choice in choices)


def test_a_hair_slot_without_a_default_is_read():
    choices = read_hair_choices(game_table(shown(0), shown(1, "phw_00_hair_00_0018_player")))
    assert [choice.prefab_stem for choice in choices] == [OTHER, "phw_00_hair_00_0018_player"]
    with pytest.raises(HairRegistrationError, match="default hairstyle"):
        read_hair_choices(game_table(shown(0), slot='Index="2" Default="4" UIKey="Hair"'))


def test_a_mixed_case_name_is_read_as_the_lower_case_file_it_names():
    slot = 'Index="2" Default="0" UIKey="Hair"'
    choices = read_hair_choices(game_table(shown(0), shown(1, "PHW_00_Hair_00_0521"), slot=slot))
    assert choices[1].prefab_stem == "phw_00_hair_00_0521" and choices[1].usable


def test_one_unusable_hairstyle_does_not_hide_the_rest_and_cannot_be_copied():
    double = ('<MeshSet Index="1"><MeshList MeshFileName="phw_a" IconPath="' + OTHER_ICON + '"/>'
              '<MeshList MeshFileName="phw_b"/></MeshSet>\r\n')
    data = game_table(shown(0), double, shown(2, "bad name"))
    choices = read_hair_choices(data)
    assert [choice.usable for choice in choices] == [True, False, False]
    assert "more than one mesh" in choices[1].problem and "file name" in choices[2].problem
    with pytest.raises(HairRegistrationError, match="more than one mesh"):
        append_hair_choice(data, template_index=1, prefab_stem=NEW, icon_path=ICON)
    with pytest.raises(HairRegistrationError, match="Hairstyle 2 .*out of order"):
        read_hair_choices(game_table(shown(0), shown(3)))


def test_a_copy_of_a_hidden_hairstyle_is_offered_by_the_barber_with_a_borrowed_icon():
    files = fixture()
    source = game_table(shown(0), hidden(1, STEM.upper()))
    files[DAMIANE_MESH_PARAM] = source
    files[OTHER_ICON] = b"another authored DDS"
    plan = prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=(), template_index=1)
    written = dict((item.path, item.data) for item in (*plan.replacements, *plan.additions))
    added = ET.fromstring(written[DAMIANE_MESH_PARAM]).find("ParamDesc[@UIKey='Hair']")[-1]
    assert added.get("Index") == "2" and added.get("ShowInGame") is None and added.get("MinValue") == "100"
    new_icon = OTHER_ICON.rsplit("/", 1)[0].lower() + f"/{NEW}.dds"
    assert added[0].attrib == {"MeshFileName": NEW, "IconPath": new_icon}
    assert plan.icon_donor == OTHER_ICON.lower() and written[new_icon] == b"another authored DDS"
    # Everything the game wrote is still there, byte for byte, around the one insertion.
    appended = append_hair_choice(source, template_index=1, prefab_stem=NEW, icon_path=new_icon)
    assert appended.data == written[DAMIANE_MESH_PARAM]
    assert appended.data[:appended.insertion_offset] + appended.data[appended.insertion_offset + len(appended.inserted_bytes):] == source
    assert read_hair_choices(appended.data)[:-1] == read_hair_choices(source)


def test_hair_stem_from_style_name_generates_character_stems_and_fallbacks():
    from cdmw.domain.hair_registration import hair_stem_from_style_name
    assert hair_stem_from_style_name("Silver Waves 02!", "Damiane") == "cd_phw_00_hair_00_silver_waves_02_player"
    assert hair_stem_from_style_name("Long Mane", "Kliff") == "cd_phm_00_hair_00_long_mane_player"
    assert hair_stem_from_style_name("Wild Mane", "Oongka") == "cd_phm_00_hair_00_wild_mane_player"
    assert hair_stem_from_style_name("!!!", "Damiane", fallback_stem=NEW) == NEW
    with pytest.raises(HairRegistrationError, match="ASCII"):
        hair_stem_from_style_name("!!!", "Damiane")


@pytest.mark.parametrize("slot_key", [b"Hair", b"hairShape"])
def test_build_and_apply_hair_choice_xml_patch_for_both_slot_keys(slot_key):
    from cdmw.domain.hair_registration import apply_hair_choice_xml_patch, build_hair_choice_xml_patch
    source = game_table(shown(0), slot=f'Index="2" UIKey="{slot_key.decode()}" Category="Hair"')
    appended = append_hair_choice(source, template_index=0, prefab_stem=NEW, icon_path=OTHER_ICON)
    patch = build_hair_choice_xml_patch(source, appended.data)
    assert b'into="ParamDesc"' in patch and b'match-Index="2"' in patch
    assert f'match-UIKey="{slot_key.decode()}"'.encode() in patch
    replayed = apply_hair_choice_xml_patch(source, patch)
    assert read_hair_choices(replayed) == read_hair_choices(appended.data)
    # Uniqueness check rejects ambiguous targets.
    start = source.index(b'<ParamDesc Index="2"')
    end = source.index(b"</ParamDesc>", start) + len(b"</ParamDesc>")
    duplicated = source[:end] + source[start:end] + source[end:]
    with pytest.raises(HairRegistrationError, match="1 matching"):
        apply_hair_choice_xml_patch(duplicated, patch)
