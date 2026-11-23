"""Palette ties between humanoid rigs settled by the player family's prefab descriptors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core import skeleton_resolver
from cdmw.models import ArchiveEntry

PHM = "character/model/1_pc/1_phm/phm_01.pab"
PHW = "character/model/1_pc/2_phw/phw_01.pab"
GOBLIN_HEAD = "character/model/1_pc/9_pgm/head/head/cd_pgm_00_head_00_4001.pac"
GOBLIN_NUDE = "character/prefab/1_pc/09_pgm/nude/cd_pgm_00_nude_00_0001.prefabdata_xml"
CREATURE_HEAD = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_knight/cd_m0001_00_knight_head_0001.pac"
CREATURE_NUDE = "character/prefab/2_mon/cd_m0001_00_twofeet/cd_m0001_00_knight/cd_m0001_00_knight_nude_0001.prefabdata_xml"


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0000/0.pamt"), Path("0000/0.paz"), 0, 1, 1, 0, 0)


def _nude(skeleton: str) -> bytes:
    return f'<PrefabData><SkeletonName FileName="{skeleton}"/></PrefabData>'.encode()


@pytest.fixture
def tied_rigs(monkeypatch):
    # Both rigs resolve every palette bone: the resolver ties them. A head's palette is
    # long; one shorter than eight entries does not count for a rig in another folder tree.
    palette = tuple(range(1, 10))
    monkeypatch.setattr(skeleton_resolver, "pac_bone_palette_candidates", lambda _data: (palette,))
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, path: SimpleNamespace(bones=palette, path=path))
    monkeypatch.setattr(skeleton_resolver, "_skeleton_palette_hits", lambda *_args, **_kwargs: len(palette))


def _resolve(model: str, descriptors: dict[str, bytes]):
    # As in the game, a head's own descriptor names its variation but no skeleton.
    stem = Path(model).stem
    variation = f"character/binary/skeletonvariation/{stem}.pabc"
    own = model.replace("/model/", "/prefab/").replace(f"{stem}.pac", f"{stem}.prefabdata_xml")
    descriptors = {own: f'<HeadPrefabData><SkeletonVariationName FileName="{stem}.pabc"/></HeadPrefabData>'.encode(),
                   **descriptors}
    entries = [_entry(path) for path in (model, PHM, PHW, variation, *descriptors)]
    by_path = {entry.path: (entry,) for entry in entries}
    by_basename = {Path(entry.path).name: (entry,) for entry in entries}
    reads = []

    def read(entry: ArchiveEntry) -> bytes:
        reads.append(entry.path)
        return descriptors.get(entry.path, b"PAR ")

    selected, report = skeleton_resolver.resolve_skeleton_for_model(
        entries[0], (), archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_basename,
        pac_data=b"PAR \x00", read_entry_data=read)
    return selected, report, reads


def test_a_goblin_head_takes_the_rig_its_family_prefabs_name(tied_rigs):
    # Prefab folders pad the family number (09_pgm) that model folders do not (9_pgm).
    selected, report, reads = _resolve(GOBLIN_HEAD, {GOBLIN_NUDE: _nude("1_pc/1_phm/phm_01.pab")})

    assert selected is not None and selected.path == PHM
    assert report.confidence == "family_descriptor" and not report.blocking_errors
    assert GOBLIN_NUDE in reads


@pytest.mark.parametrize("descriptors", [
    {},
    # Disagreeing families stay refused.
    {GOBLIN_NUDE: _nude("1_pc/1_phm/phm_01.pab"),
     "character/prefab/1_pc/09_pgm/nude/cd_pgm_00_nude_00_0002.prefabdata_xml": _nude("1_pc/2_phw/phw_01.pab")},
    # Another family's prefabs are not evidence.
    {"character/prefab/1_pc/05_pom/nude/cd_pom_00_nude_00_0001.prefabdata_xml": _nude("1_pc/1_phm/phm_01.pab")},
])
def test_a_tie_without_one_family_answer_stays_refused(tied_rigs, descriptors):
    selected, report, _reads = _resolve(GOBLIN_HEAD, descriptors)

    assert selected is None and report.confidence == "ambiguous_palette"
    assert report.blocking_errors == ("Multiple skeleton candidates scored equally; select a skeleton explicitly.",)


def test_creature_families_keep_their_tie_for_refit_to_settle(tied_rigs):
    selected, report, _reads = _resolve(CREATURE_HEAD, {CREATURE_NUDE: _nude("1_pc/1_phm/phm_01.pab")})

    assert selected is None and report.confidence == "ambiguous_palette"


@pytest.mark.parametrize("dlc_first", [False, True])
def test_a_dlc_copy_of_a_rig_wins_over_the_base_copy_it_shadows(dlc_first):
    # dlc_01 ships its own copy of a base group folder, whose files replace the base
    # files at the same path. Candidates were deduplicated by path in arrival order,
    # and a basename group may list the base copy first.
    def at(path, pamt, offset=0):
        return ArchiveEntry(path, Path(pamt), Path(pamt).with_name("0.paz"), offset, 1, 1, 0, 0)

    model = at("character/model/owned/body.pac", "game/0009/0.pamt")
    base = at("character/model/owned/body.pab", "game/0009/0.pamt", 64)
    dlc = at("character/model/owned/body.pab", "game/dlc/dlc_01/0009/0.pamt")
    group = (dlc, base) if dlc_first else (base, dlc)
    selected, report = skeleton_resolver.resolve_skeleton_for_model(
        model, (), archive_entries_by_normalized_path={}, archive_entries_by_basename={"body.pab": group})
    assert selected is dlc, report
    assert len(report.candidates) == 1


NPC_HUMAN_TOP = "character/model/3_npc/1_nhm/armor_south/9_upperbody/cd_nhm_00_so_ub_10109.pac"
NPC_DWARF_TOP = "character/model/3_npc/7_ndm/armor_south/9_upperbody/cd_ndm_00_so_ub_10001.pac"
DWARF_NUDE = "character/prefab/1_pc/07_pdm/nude/cd_pdm_00_nude_00_0001.prefabdata_xml"


def test_npc_armor_names_the_player_rig_of_its_race():
    from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames

    assert "phm_01.pab" in iter_pab_candidate_basenames(NPC_HUMAN_TOP)
    assert "phw_01.pab" in iter_pab_candidate_basenames(NPC_HUMAN_TOP.replace("1_nhm", "2_nhw").replace("_nhm_", "_nhw_"))
    assert "phm_01.pab" not in iter_pab_candidate_basenames(GOBLIN_HEAD.replace("9_pgm", "9_xgm"))


def test_a_human_npc_armor_piece_takes_the_player_male_rig(tied_rigs):
    # NPC armor ships no .pab and its prefabs name no skeleton; every humanoid rig resolves its palette.
    selected, report, _reads = _resolve(NPC_HUMAN_TOP, {})

    assert selected is not None and selected.path == PHM
    assert not report.blocking_errors


def test_a_dwarf_npc_armor_piece_takes_the_rig_its_player_family_prefabs_name(tied_rigs):
    selected, report, reads = _resolve(NPC_DWARF_TOP, {DWARF_NUDE: _nude("1_pc/1_phm/phm_01.pab")})

    assert selected is not None and selected.path == PHM
    assert report.confidence == "family_descriptor" and DWARF_NUDE in reads


def test_npc_families_without_a_player_twin_use_the_body_their_appearances_wear():
    from cdmw.modding.skeleton_parser import npc_player_family

    assert npc_player_family("nhm") == "phm" and npc_player_family("ntm") == "ptm"
    assert npc_player_family("ndem") == "phm" and npc_player_family("ntw") == "phw"
    assert npc_player_family("") == "" and npc_player_family("phm") == ""


NPC_DEMON_TOP = "character/model/3_npc/18_ndem/armor_south/9_upperbody/cd_ndem_00_so_ub_20003.pac"
PPDM = "character/model/1_pc/19_ppdm/ppdm_01.pab"
FAIRY = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_bd_forestfairy/cd_m0001_00_bd_forestfairy.pab"
HUMAN_MALE_NUDE = "character/prefab/1_pc/01_phm/nude/phm_00_nude_00_0001.prefabdata_xml"


def _resolve_palette(model: str, rigs: dict[str, tuple[int, ...]], palette: tuple[int, ...],
                     descriptors: dict[str, bytes], monkeypatch):
    """Resolve with per-rig bone hashes, as the worker's bounded set delivers them."""
    monkeypatch.setattr(skeleton_resolver, "pac_bone_palette_candidates", lambda _data: (palette,))
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, path: SimpleNamespace(
        bones=tuple(SimpleNamespace(name_hash=value) for value in rigs[path]), path=path))
    entries = [_entry(path) for path in (model, *rigs, *descriptors)]
    by_path = {entry.path: (entry,) for entry in entries}
    by_basename = {Path(entry.path).name: (entry,) for entry in entries}
    return skeleton_resolver.resolve_skeleton_for_model(
        entries[0], (), archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_basename,
        pac_data=b"PAR \x00", read_entry_data=lambda entry: descriptors.get(entry.path, b"PAR "))


def test_demon_npc_armor_offers_the_demon_player_rig_too():
    from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames

    names = iter_pab_candidate_basenames(NPC_DEMON_TOP)
    assert "phm_01.pab" in names and "ppdm_01.pab" in names
    assert "ppdm_01.pab" not in iter_pab_candidate_basenames(NPC_HUMAN_TOP)


def test_demon_npc_armor_with_demon_calves_takes_the_demon_rig(monkeypatch):
    # The PDEM calf bones are only in ppdm_01 and in one creature's rig. The demon rig
    # is a named candidate of the family, so it wins the full-palette tie.
    body, calves = tuple(range(1, 74)), (901, 902)
    selected, report = _resolve_palette(
        NPC_DEMON_TOP, {PHM: body, PPDM: body + calves, FAIRY: body + calves}, body + calves,
        {HUMAN_MALE_NUDE: _nude("1_pc/1_phm/phm_01.pab")}, monkeypatch)

    assert selected is not None and selected.path == PPDM, report
    assert not report.blocking_errors


def test_ordinary_demon_npc_armor_keeps_the_body_its_appearances_wear(monkeypatch):
    # Both player rigs hold every bone; the human male body descriptor settles the tie.
    body = tuple(range(1, 74))
    selected, report = _resolve_palette(
        NPC_DEMON_TOP.replace("20003", "20001"), {PHM: body, PPDM: body + (901, 902)}, body,
        {HUMAN_MALE_NUDE: _nude("1_pc/1_phm/phm_01.pab")}, monkeypatch)

    assert selected is not None and selected.path == PHM, report
    assert report.confidence == "family_descriptor"


@pytest.mark.parametrize(("model", "descriptor", "rig"), [
    # Orc, dwarf and goblin NPCs wear the human rigs; only the player family's body
    # descriptor names them, so the worker delivers that descriptor with the rig.
    ("character/model/3_npc/5_nom/armor_south/9_upperbody/cd_nom_00_so_ub_00001.pac",
     "character/prefab/1_pc/05_pom/nude/pom_00_nude_00_0001.prefabdata_xml", PHM),
    ("character/model/3_npc/8_ndw/armor_south/9_upperbody/cd_ndw_00_so_ub_00001.pac",
     "character/prefab/1_pc/08_pdw/nude/cd_pdw_00_nude_00_0001.prefabdata_xml", PHW),
    ("character/model/3_npc/15_ntw/armor_south/9_upperbody/cd_ntw_00_so_ub_10001.pac",
     "character/prefab/1_pc/02_phw/nude/phw_00_nude_00_0001.prefabdata_xml", PHW),
])
def test_npc_armor_resolves_in_the_workers_bounded_set(monkeypatch, model, descriptor, rig):
    # The bounded set holds the named rig and identityskeleton, never every PAB.
    body = tuple(range(1, 40))
    identity = "character/identityskeleton.pab"
    selected, report = _resolve_palette(
        model, {rig: body, identity: (1, 2)}, body, {descriptor: _nude(rig.removeprefix("character/model/"))}, monkeypatch)

    assert selected is not None and selected.path == rig, report
    assert not report.blocking_errors


def test_a_refused_lookup_says_which_rigs_it_checked_and_what_they_lack(monkeypatch):
    # Eight human NPC pieces name a bone or two that no rig in the game holds. The
    # refusal names the rigs actually checked and how close each came, not every
    # file name the lookup searched for, most of which do not exist.
    from cdmw.core.archive_mesh_export import _checked_skeletons_detail

    body = tuple(range(1, 67))
    identity = "character/identityskeleton.pab"
    selected, report = _resolve_palette(
        NPC_HUMAN_TOP, {PHM: body[:-2], identity: (1, 2)}, body,
        {HUMAN_MALE_NUDE: _nude("1_pc/1_phm/phm_01.pab")}, monkeypatch)

    assert selected is None
    by_path = {candidate.path: candidate for candidate in report.candidates}
    assert (by_path[PHM].palette_misses, by_path[PHM].palette_size) == (2, 66)
    assert _checked_skeletons_detail(report) == (
        "\nSkeletons checked: phm_01.pab (lacks 2 of the model's 66 bones), "
        "identityskeleton.pab (lacks 64 of the model's 66 bones)")


def test_a_model_its_nearest_rig_almost_fits_is_told_it_has_no_rig(monkeypatch):
    # Those eight pieces are refused, and the message says why: the model has no rig.
    from cdmw.core import archive_mesh_export

    body = tuple(range(1, 67))
    report = _resolve_palette(NPC_HUMAN_TOP, {PHM: body[:-2], "character/identityskeleton.pab": (1, 2)}, body,
                              {}, monkeypatch)
    monkeypatch.setattr(archive_mesh_export, "resolve_skeleton_for_model", lambda *a, **k: report)
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda *_a, **_k: (b"", False, ""))
    selected, detail, _attempted, _report = archive_mesh_export._find_matching_skeleton_entry(_entry(NPC_HUMAN_TOP))

    assert selected is None
    assert detail == (
        "This model has no rig: no skeleton holds all of the bones it is skinned to. "
        "The closest, phm_01.pab, lacks 2 of its 66 bones. "
        "It can be exported only without a skeleton, so it will have no skin weights.")


def test_a_rig_that_was_not_found_is_not_called_missing(monkeypatch):
    # Only a far-off skeleton was checked: the model's own rig was not in the set,
    # which is a lookup failure, not proof that the model has no rig.
    from cdmw.core import archive_mesh_export

    body = tuple(range(1, 67))
    report = _resolve_palette(NPC_HUMAN_TOP, {"character/identityskeleton.pab": (1, 2)}, body, {}, monkeypatch)
    monkeypatch.setattr(archive_mesh_export, "resolve_skeleton_for_model", lambda *a, **k: report)
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda *_a, **_k: (b"", False, ""))
    _selected, detail, _attempted, _report = archive_mesh_export._find_matching_skeleton_entry(_entry(NPC_HUMAN_TOP))

    assert detail.startswith("No candidate skeleton resolves the PAC bone palette.")
    assert "no rig" not in detail
    assert "identityskeleton.pab (lacks 64 of the model's 66 bones)" in detail


def test_a_lookup_that_found_no_rig_file_says_what_it_looked_for():
    from cdmw.core.archive_mesh_export import _checked_skeletons_detail
    from cdmw.core.skeleton_resolver import SkeletonResolveReport

    report = SkeletonResolveReport(model_path=NPC_HUMAN_TOP, attempted_paths=("a.pab", "b.pab"))
    assert _checked_skeletons_detail(report) == "\nNo skeleton file was found. Looked for: a.pab, b.pab"
