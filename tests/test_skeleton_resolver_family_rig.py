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
    # Both rigs resolve every palette bone: the resolver ties them.
    monkeypatch.setattr(skeleton_resolver, "pac_bone_palette_candidates", lambda _data: ((1, 2, 3),))
    monkeypatch.setattr(skeleton_resolver, "parse_pab", lambda _data, path: SimpleNamespace(bones=(1, 2, 3), path=path))
    monkeypatch.setattr(skeleton_resolver, "_skeleton_palette_hits", lambda *_args, **_kwargs: 3)


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
