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


def fixture(*, stem=STEM):
    mesh = MESH.replace(STEM, stem)
    record = PartPrefabRecord(stem, "1_pc/02_phw/head/hair", "", flag=0, parts=(PartPrefabPart("CD_Hair"),))
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


@pytest.mark.parametrize("character", ["Kliff", "Damiane", "Oongka"])
@pytest.mark.parametrize("player_variant", [True, False])
@pytest.mark.parametrize("slot_key", [b"Hair", b"hairShape"])
def test_registration_uses_selected_characters_barber_document(character, player_variant, slot_key):
    from cdmw.domain.hair_characters import hair_character
    from cdmw.services.hair_registration import prepare_hair_registration
    profile = hair_character(character)
    stem = STEM if character == "Damiane" else STEM.replace("phw", "phm")
    if not player_variant:
        stem = stem.removesuffix("_player")
    mesh = profile.hair_root + stem + ".pac"
    files = fixture()
    files[profile.mesh_param_path] = files.pop(DAMIANE_MESH_PARAM).replace(STEM.encode(), stem.encode())
    files[profile.mesh_param_path] = files[profile.mesh_param_path].replace(b'UIKey="hairShape"', b'UIKey="' + slot_key + b'"')
    record = PartPrefabRecord(stem, "1_pc/01_phm/head/hair" if character != "Damiane" else "1_pc/02_phw/head/hair",
                              "", flag=0, parts=(PartPrefabPart("CD_Hair"),))
    old_record = parse_pappt(files[PART_PREFAB_TABLE]).records[0]
    files.pop(old_record.prefab_path)
    files[PART_PREFAB_TABLE] = encode_pappt(PartPrefabTable((record,), tag_prefix=b"\x01"))
    files[record.prefab_path] = _build(mesh)
    for path in tuple(files):
        if MESH in path or STEM in path:
            value = files.pop(path)
            files[path.replace("2_phw", profile.hair_family).replace(STEM, stem)] = value
    plan = prepare_hair_registration(files, character=character, new_stem="my_added_hair", existing_paths=tuple(files))
    outputs = {item.path: item.data for item in plan.replacements}
    assert read_hair_choices(outputs[profile.mesh_param_path])[-1].prefab_stem == "my_added_hair"
    assert len(plan.additions) == 5


@pytest.mark.parametrize("filename,accepted", [
    ("cd_phw_00_hair_00_0001.pac", True),
    ("cd_phw_00_hair_00_0008_01_player.pac", True),
    ("my_authored_hair.pac", True),
    ("../head/other_player.pac", False),
    ("nested/other_player.pac", False),
    ("/other_player.pac", False),
    ("bad.pac:extra", False),
    ("hair.pam", False),
])
def test_hair_family_accepts_registered_variants_but_keeps_paths_contained(filename, accepted):
    from cdmw.domain.hair_characters import hair_character, unique_hair_character
    profile = hair_character("Damiane")
    path = profile.hair_root + filename
    assert profile.accepts_hair(path) == accepted
    assert profile.accepts_hair(path.upper().replace("/", "\\")) == accepted
    assert not hair_character("Kliff").accepts_hair(path)
    assert (unique_hair_character(path) is profile) == accepted


@pytest.mark.parametrize("character", ["Kliff", "Damiane", "Oongka"])
def test_non_player_donors_still_require_original_lod_and_skin_records(character):
    from cdmw.domain.hair_characters import hair_character
    from cdmw.modding.mesh_skinning import PAC_SKIN_WEIGHT_LAYOUT
    from cdmw.services.mesh_rust_hair import validate_hair_donor
    part = SimpleNamespace(name="hair", vertices=[(0., 0., 0.)], source_vertex_stride=40,
        source_skin_weight_layout=PAC_SKIN_WEIGHT_LAYOUT, bone_indices=[(0,)], bone_weights=[(1.,)])
    mesh = SimpleNamespace(path=hair_character(character).hair_root + "cd_custom_hair.pac",
                           submeshes=[part], lod_levels=[])
    validate_hair_donor(mesh, character)
    part.source_vertex_stride = 44
    with pytest.raises(ValueError, match="stride"):
        validate_hair_donor(mesh, character)
    part.source_vertex_stride = 40
    part.bone_weights = []
    with pytest.raises(ValueError, match="skin records"):
        validate_hair_donor(mesh, character)
    part.bone_weights = [(1.,)]
    mesh.lod_levels = [[], []]
    with pytest.raises(ValueError, match="additional PAC LODs"):
        validate_hair_donor(mesh, character)


@pytest.mark.parametrize("slot_key", [b"Hair", b"hairShape"])
def test_append_retains_every_source_byte_and_existing_option(slot_key):
    source = XML.replace(b'UIKey="hairShape"', b'UIKey="' + slot_key + b'"')
    result = append_hair_choice(source, template_index=0, prefab_stem=NEW, icon_path=ICON)
    assert result.data[:result.insertion_offset] + result.data[result.insertion_offset + len(result.inserted_bytes):] == source
    choices = read_hair_choices(result.data)
    assert choices[:-1] == read_hair_choices(source)
    assert choices[-1].index == 1 and choices[-1].prefab_stem == NEW
    node = ET.fromstring(result.data).findall("ParamDesc")[1][-1]
    assert node.get("FutureField") == "keep"
    assert node.get("DecorationParamIndex") == "0 1" and node.get("MinValue") == "40 50"


@pytest.mark.parametrize("data", [
    XML.replace(b'MeshSet Index="0"', b'MeshSet Index="1"'),
    XML.replace(b'Index="2" Default="0"', b'Index="2" Default="5"'),
    XML.replace(b'</MeshSet>', b'<MeshList MeshFileName="another"/></MeshSet>'),
    b'<!DOCTYPE MeshParam [<!ENTITY x "x">]><MeshParam/>',
    XML.replace(b'</MeshParam>', b'<ParamDesc Index="2" UIKey="hairShape"/></MeshParam>'),
    XML.replace(b'UIKey="hairShape"', b'UIKey="Beard"'),
    XML.replace(b'Index="2"', b'Index="7"').replace(b'UIKey="hairShape"', b'UIKey="Hair"'),
    XML.replace(b'</MeshParam>', b'<ParamDesc Index="7" UIKey="Hair"/></MeshParam>'),
    XML.replace(b'</MeshParam>', b'<ParamDesc Index="2" UIKey="Beard"/></MeshParam>'),
])
def test_ambiguous_or_unsupported_slots_are_rejected(data):
    with pytest.raises(HairRegistrationError):
        append_hair_choice(data, template_index=0, prefab_stem=NEW, icon_path=ICON)


@pytest.mark.parametrize("stem,icon,index", [("../hair", ICON, 0), (NEW, "ui/texture/../bad.dds", 0),
                                                (STEM, ICON, 0), (NEW, ICON, -1), (NEW, ICON, True)])
def test_invalid_new_choice_is_rejected(stem, icon, index):
    with pytest.raises(HairRegistrationError):
        append_hair_choice(XML, template_index=index, prefab_stem=stem, icon_path=icon)


def test_plan_clones_geometry_physics_material_and_icon_without_changing_sources():
    files = fixture()
    original = dict(files)
    plan = prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=tuple(files))
    assert files == original
    assert plan.choice_index == 1
    assert len(plan.replacements) == 2 and len(plan.additions) == 5
    output = {item.path: item.data for item in (*plan.replacements, *plan.additions)}
    old_table = parse_pappt(files[PART_PREFAB_TABLE])
    new_table = parse_pappt(output[PART_PREFAB_TABLE])
    assert new_table.records[:-1] == old_table.records
    assert new_table.head_records == old_table.head_records
    assert new_table.tag_prefix == old_table.tag_prefix
    for item in plan.additions:
        if item.path.endswith(".prefab"):
            assert [r.text for r in decode_prefab_binary(item.data).resource_strings()] == [MESH.replace(STEM, NEW)]
        elif item.path.endswith(".dds"):
            assert item.data == files[ICON]
        else:
            assert item.data == files[item.path.replace(NEW, STEM)]
    plan.check_sources(files)
    changed = dict(files)
    changed[PART_PREFAB_TABLE] += b"changed"
    with pytest.raises(HairRegistrationError, match="source changed"):
        plan.check_sources(changed)


def test_case_insensitive_path_and_table_conflicts_block_addition():
    files = fixture()
    with pytest.raises(HairRegistrationError, match="overwrite"):
        prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=(MESH.replace(STEM, NEW).upper(),))
    table = parse_pappt(files[PART_PREFAB_TABLE])
    files[PART_PREFAB_TABLE] = encode_pappt(replace(table, records=table.records + (table.records[0].cloned(NEW.upper()),)))
    with pytest.raises(HairRegistrationError, match="already exists"):
        prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=())


def test_missing_physics_and_ambiguous_source_ownership_are_blocked():
    files = fixture()
    physics = next(path for path in files if path.endswith(".hkx"))
    del files[physics]
    with pytest.raises(HairRegistrationError, match="Missing hair registration dependency"):
        prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=())
    files = fixture()
    files[MESH.upper()] = files[MESH]
    with pytest.raises(HairRegistrationError, match="Ambiguous source ownership"):
        prepare_damiane_hair_registration(files, new_stem=NEW, existing_paths=())


def test_mounted_prefab_table_wins_over_shadowed_original():
    original = SimpleNamespace(path=PART_PREFAB_TABLE, is_active_override=False, override_state="Shadowed original")
    mounted = SimpleNamespace(path=PART_PREFAB_TABLE, is_active_override=True, override_state="Active original")
    assert select_active_entry((original, mounted), PART_PREFAB_TABLE) is mounted
    with pytest.raises(HairRegistrationError, match="shadowed"):
        select_active_entry((original,), PART_PREFAB_TABLE)
    with pytest.raises(HairRegistrationError, match="Expected one"):
        select_active_entry((mounted, mounted), PART_PREFAB_TABLE)


def test_streamed_lookup_entries_are_collected_before_resolving_sources():
    entries = (SimpleNamespace(entry_id=11), SimpleNamespace(entry_id=12))
    batch = SimpleNamespace(session_id="source", entries=entries, total_matches=2, truncated=False)
    final = SimpleNamespace(session_id="source", entries=(), total_matches=2, truncated=False)
    waiter = SimpleNamespace(batches={"request": [batch]}, wait=lambda _: final)
    assert collect_lookup_entries(waiter, "request") == entries
    assert waiter.batches == {}
    with pytest.raises(HairRegistrationError, match="incomplete"):
        collect_lookup_entries(waiter, "request")


@pytest.mark.parametrize("change, message", [
    ({"truncated": True}, "truncated"),
    ({"session_id": "stale"}, "different source"),
    ({"entries": (SimpleNamespace(entry_id=11), SimpleNamespace(entry_id=11))}, "duplicate"),
])
def test_incomplete_or_stale_lookup_evidence_is_rejected(change, message):
    batch = SimpleNamespace(session_id="source", entries=(SimpleNamespace(entry_id=11),), total_matches=2, truncated=False)
    batch.__dict__.update(change)
    final = SimpleNamespace(session_id="source", entries=(), total_matches=2, truncated=False)
    waiter = SimpleNamespace(batches={"request": [batch]}, wait=lambda _: final)
    with pytest.raises(HairRegistrationError, match=message):
        collect_lookup_entries(waiter, "request")
