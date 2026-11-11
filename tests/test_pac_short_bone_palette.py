"""A PAC's bone palette is read in place, so a short one still names its skeleton.

A helmet follows the head bone alone: its palette is one or two entries. A byte
scan needs eight to tell a table from chance, and embedded collision data alone
looks like dozens of longer tables, so the scan found no skeleton for it.
"""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core import skeleton_resolver
from cdmw.modding import mesh_parser
from cdmw.modding.mesh_parser import (
    decoded_pac_bone_palette,
    pac_bone_palette_candidates,
    resolve_pac_bone_palette,
)
from cdmw.models import ArchiveEntry
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac

HEAD, NECK, SPINE, WEAPON = 0xA23A288E, 0x5C1D2B77, 0x7E9911C3, 0xB20719D4
#: Eight distinct large values behind a count, as collision data offers by chance.
CHANCE_TABLE = struct.pack("<H8I", 8, *(0x6D315453 + 0x01010101 * i for i in range(8)))

HELMET = "character/model/1_pc/2_phw/armor/13_hel/cd_phw_00_hel_00_0151.pac"
PHW = "character/model/1_pc/2_phw/phw_01.pab"
PHM = "character/model/1_pc/1_phm/phm_01.pab"
DESCRIPTOR = "character/prefab/1_pc/02_phw/armor/13_hel/cd_phw_00_hel_00_0151.prefabdata_xml"


def _rig(*hashes: int):
    return SimpleNamespace(bones=tuple(SimpleNamespace(name=f"bone{i}", name_hash=value)
                                       for i, value in enumerate(hashes)))


def _helmet(palette=(HEAD, NECK)) -> bytes:
    return guide_free_pac(palette=palette, extra=CHANCE_TABLE)


def test_a_short_palette_is_read_in_place():
    pac = _helmet()
    # The scan sees only the chance table: the real one is below its eight-entry floor.
    assert [len(table) for table in mesh_parser._pac_bone_palette_candidates(pac)] == [8]
    assert decoded_pac_bone_palette(pac) == (HEAD, NECK)
    assert pac_bone_palette_candidates(pac) == ((HEAD, NECK),)
    assert resolve_pac_bone_palette(pac, _rig(SPINE, NECK, HEAD)) == (2, 1)


def test_a_one_bone_palette_resolves():
    assert resolve_pac_bone_palette(_helmet((HEAD,)), _rig(SPINE, HEAD)) == (1,)


def test_a_palette_naming_a_bone_the_rig_lacks_resolves_nothing():
    assert resolve_pac_bone_palette(_helmet(), _rig(SPINE, HEAD)) == ()


def test_a_decoded_palette_outranks_a_chance_table_the_rig_happens_to_hold():
    chance = struct.unpack("<8I", CHANCE_TABLE[2:])
    assert resolve_pac_bone_palette(_helmet(), _rig(HEAD, NECK, *chance)) == (0, 1)


def test_an_undecoded_layout_still_uses_the_scan():
    pac = guide_free_pac(flags=0x20)  # the embedded bone-group branch is not decoded
    assert decoded_pac_bone_palette(pac) is None
    assert pac_bone_palette_candidates(pac) == (PALETTE,)
    assert resolve_pac_bone_palette(pac, _rig(*PALETTE)) == tuple(range(8))


def test_a_palette_naming_the_models_own_embedded_bone_is_no_evidence_for_a_rig():
    from tests.test_mesh_weapon_collisions import weapon_fixture

    # A weapon's palette is its embedded B_Weapon_0001 root. One creature rig has a
    # bone of that name; it is not the weapon's skeleton.
    pac = weapon_fixture()
    assert decoded_pac_bone_palette(pac) is None
    assert pac_bone_palette_candidates(pac) == ()
    assert resolve_pac_bone_palette(pac, _rig(PALETTE[0])) == ()


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0009/0.pamt"), Path("0009/0.paz"), 0, 1, 1, 0, 0)


def _resolve(monkeypatch, pac: bytes, *, descriptor: bool):
    rigs = {PHW: _rig(SPINE, NECK, HEAD), PHM: _rig(SPINE, HEAD)}
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, path: rigs[path])
    files = {DESCRIPTOR: b'<PrefabData><SkeletonName FileName="1_pc/2_phw/PHW_01.pab"/></PrefabData>'} if descriptor else {}
    entries = [_entry(path) for path in (HELMET, PHW, PHM, *files)]
    by_path = {entry.path: (entry,) for entry in entries}
    by_basename = {Path(entry.path).name: (entry,) for entry in entries}
    return skeleton_resolver.resolve_skeleton_for_model(
        entries[0], (), archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_basename,
        pac_data=pac, read_entry_data=lambda entry: files.get(entry.path, b""))


@pytest.mark.parametrize("descriptor", [True, False])
def test_a_helmet_finds_the_rig_that_holds_its_short_palette(monkeypatch, descriptor):
    selected, report = _resolve(monkeypatch, _helmet(), descriptor=descriptor)
    assert selected is not None and selected.path == PHW, report.blocking_errors
    assert report.confidence == ("descriptor" if descriptor else report.confidence)
    assert not report.blocking_errors


def test_one_attachment_bone_does_not_bind_a_player_model_to_another_groups_rig(monkeypatch):
    # cd_phm_01_sword_0288.pac names B_Weapon_0001 and embeds no bone; of every rig in
    # the game only a creature's has a bone of that name.
    sword = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0288.pac"
    creature = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_hexe_soldier/cd_m0001_00_hexe_soldier.pab"
    rigs = {PHM: _rig(SPINE, HEAD), creature: _rig(SPINE, WEAPON)}
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, path: rigs[path])
    entries = [_entry(path) for path in (sword, PHM, creature)]
    selected, report = skeleton_resolver.resolve_skeleton_for_model(
        entries[0], (), archive_entries_by_normalized_path={entry.path: (entry,) for entry in entries},
        archive_entries_by_basename={Path(entry.path).name: (entry,) for entry in entries},
        pac_data=_helmet((WEAPON,)), read_entry_data=lambda _entry: b"")
    assert selected is None
    assert report.blocking_errors == ("No candidate skeleton resolves the PAC bone palette.",)


@pytest.mark.parametrize("rig, found", [
    ("character/model/4_riding/cd_r0039_00_warrobot/cd_r0039_00_warrobot.pab", True),
    ("character/model/4_riding/cd_r0012_00_carriage/cd_r0012_00_carriage_0001_vehicle.pab", False),
])
def test_outside_the_player_folder_a_short_palette_counts_only_for_a_rig_above_the_model(monkeypatch, rig, found):
    # "Bone001" is in a carriage's rig too; that does not make it a war robot part's skeleton.
    part = "character/model/4_riding/cd_r0039_00_warrobot/cd_r0039_00_warrobot_arm_0001/cd_r0039_00_warrobot_arm_0001.pac"
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, _path: _rig(SPINE, WEAPON))
    entries = [_entry(path) for path in (part, rig)]
    selected, _report = skeleton_resolver.resolve_skeleton_for_model(
        entries[0], (), archive_entries_by_normalized_path={entry.path: (entry,) for entry in entries},
        archive_entries_by_basename={Path(entry.path).name: (entry,) for entry in entries},
        pac_data=_helmet((WEAPON,)), read_entry_data=lambda _entry: b"")
    assert (selected is not None and selected.path == rig) == found


def test_a_palette_no_rig_holds_is_still_refused(monkeypatch):
    selected, report = _resolve(monkeypatch, _helmet((HEAD, 0x11223344)), descriptor=True)
    assert selected is None
    assert report.blocking_errors == ("No candidate skeleton resolves the PAC bone palette.",)
