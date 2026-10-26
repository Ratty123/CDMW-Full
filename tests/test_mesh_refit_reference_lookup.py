"""Finding the authored body for Fit to body from the session's archive Refit assets."""
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pytest

from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services import mesh_refit_reference_lookup as lookup
from cdmw.services.mesh_archive_refit import ArchiveRefitAsset, ArchiveRefitContext

PHM_NUDE = "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac"
PHW_NUDE = "character/model/1_pc/1_phw/nude/cd_phw_00_nude_00_0001.pac"
OUTFIT = "character/model/1_pc/1_phm/armor/cd_m0001_00_de_phm_ub_11002.pac"
DRIVER = "character/model/1_pc/1_phw/nude/cd_phw_00_nude_00_0001_damian.pac"
PHM_PAB = "character/model/1_pc/1_phm/phm_01.pab"
PHW_PAB = "character/model/1_pc/1_phw/phw_01.pab"


def _matrix(translation=(0., 0., 0.)):
    return (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., *translation, 1.)


def _skeleton(path, arm_height):
    return Skeleton(path=path, bones=[
        Bone(index=0, name="Bip01", parent_index=-1, bind_matrix=_matrix()),
        Bone(index=1, name="Bip01 Arm", parent_index=0, bind_matrix=_matrix((0., arm_height, 0.))),
    ])


SKELETONS = {PHM_PAB: _skeleton(PHM_PAB, 1.), PHW_PAB: _skeleton(PHW_PAB, 1.1)}
RIGS = {OUTFIT: PHM_PAB, DRIVER: PHW_PAB, PHM_NUDE: PHM_PAB, PHW_NUDE: PHW_PAB}


def _body():
    return SubMesh(name="nude", material="skin", texture="",
                   vertices=[(0., 1.5, 0.), (.1, 1.5, 0.), (0., .5, 0.)], faces=[(0, 1, 2)],
                   bone_indices=[(1,), (1,), (0,)], bone_weights=[(1.,), (1.,), (1.,)])


@dataclass
class _Dependencies:
    paths: tuple[str, ...]
    entries_by_basename: dict = field(default_factory=dict)

    @property
    def entries_by_normalized_path(self):
        return {path: (SimpleNamespace(path=path),) for path in self.paths}

    def entry_for_path(self, path):
        return SimpleNamespace(path=path) if path in self.paths else None


def _asset(path, parts, role, dependencies=None, appearance=None):
    return ArchiveRefitAsset(
        entry=SimpleNamespace(path=path), source=SimpleNamespace(original_data=path.encode()),
        part_indices=tuple(parts), role=role,
        preview_lease=SimpleNamespace(archive_dependencies=dependencies) if dependencies else None,
        neutral_appearance=appearance,
    )


@pytest.fixture
def archive(monkeypatch):
    reads = []

    def resolve(entry, **_kwargs):
        rig = RIGS.get(entry.path)
        return (SimpleNamespace(path=rig) if rig else None), SimpleNamespace(reason="no rig")

    monkeypatch.setattr("cdmw.core.skeleton_resolver.resolve_skeleton_for_model", resolve)
    monkeypatch.setattr(lookup, "parse_pab", lambda data, path: SKELETONS[path])
    monkeypatch.setattr(lookup, "parse_pac", lambda data, path: ParsedMesh(path=path, format="pac", submeshes=[_body()]))
    monkeypatch.setattr(lookup, "resolve_pac_bone_palette", lambda data, skeleton: (0, 1))
    lookup.clear_refit_reference_cache()
    yield lambda entry: reads.append(entry.path) or entry.path.encode(), reads
    lookup.clear_refit_reference_cache()


def _context(*assets):
    return ArchiveRefitContext(tuple(assets))


def test_phm_outfit_on_a_phw_driver_uses_the_retargeted_phm_nude_body(archive):
    read, reads = archive
    dependencies = _Dependencies((PHM_NUDE, PHW_NUDE, OUTFIT, DRIVER))
    context = _context(_asset(OUTFIT, (0, 1), "loaded"), _asset(DRIVER, (2,), "body", dependencies))
    found = lookup.find_refit_reference_body(context, (0, 1), (2,), read_entry=read)
    assert found.reason == "" and found.reference.label == PHM_NUDE
    # Arm vertices move with the taller target arm joint; the root vertex stays.
    np.testing.assert_allclose(found.reference.fitted_positions, [[0., 1.6, 0.], [.1, 1.6, 0.], [0., .5, 0.]])
    np.testing.assert_allclose(found.reference.source_positions, _body().vertices)
    count = len(reads)
    assert lookup.find_refit_reference_body(context, (0, 1), (2,), read_entry=read) is found
    assert len(reads) == count


def test_the_reference_takes_each_assets_character_appearance(archive):
    read, _reads = archive
    dependencies = _Dependencies((PHM_NUDE, OUTFIT, DRIVER))
    garment_look = NeutralMeshAppearance("outfit.pabc", (0, 1), (_matrix(), _matrix((.01, 0., 0.))))
    driver_look = NeutralMeshAppearance("damian.pabc", (0, 1), (_matrix((0., 0., .02)), _matrix()))
    context = _context(_asset(OUTFIT, (0,), "loaded", appearance=garment_look),
                       _asset(DRIVER, (1,), "body", dependencies, appearance=driver_look))
    found = lookup.find_refit_reference_body(context, (0,), (1,), read_entry=read)
    np.testing.assert_allclose(found.reference.source_positions, [[.01, 1.5, 0.], [.11, 1.5, 0.], [0., .5, 0.]])
    np.testing.assert_allclose(found.reference.fitted_positions, [[0., 1.6, 0.], [.1, 1.6, 0.], [0., .5, .02]])


@pytest.mark.parametrize("case,reason", [
    ("plain", "not loaded from the game archive"),
    ("same body", "authored on this body"),
    ("no index", "archive index is not available"),
    ("no nude", "no nude body was found"),
    ("no rig", "no skeleton was found for cd_m0001_00_de_phm_ub_11002.pac (no rig)"),
    ("shared", "come from the same PAC"),
])
def test_fit_to_the_driver_alone_says_why(archive, case, reason):
    read, _reads = archive
    dependencies = _Dependencies((PHM_NUDE, OUTFIT, DRIVER))
    garments, driver = (0,), (1,)
    if case == "plain":
        context = None
    elif case == "same body":
        context = _context(_asset(OUTFIT, (0,), "loaded"), _asset(PHM_NUDE, (1,), "body", dependencies))
    elif case == "no index":
        context = _context(_asset(OUTFIT, (0,), "loaded"), _asset(DRIVER, (1,), "body"))
    elif case == "no nude":
        context = _context(_asset(OUTFIT, (0,), "loaded"), _asset(DRIVER, (1,), "body", _Dependencies((OUTFIT, DRIVER))))
    elif case == "no rig":
        RIGS.pop(OUTFIT)
        context = _context(_asset(OUTFIT, (0,), "loaded"), _asset(DRIVER, (1,), "body", dependencies))
    else:
        context = _context(_asset(OUTFIT, (0, 1), "loaded"), _asset(DRIVER, (2,), "body", dependencies))
        driver = (1,)
    try:
        found = lookup.find_refit_reference_body(context, garments, driver, read_entry=read)
    finally:
        RIGS[OUTFIT] = PHM_PAB
    assert found.reference is None and reason in found.reason


def test_bounded_archive_sets_find_the_authored_body_once_its_nude_folder_is_supplied(archive, monkeypatch):
    read, _reads = archive

    def resolve(entry, *, archive_entries_by_normalized_path, **_kwargs):
        rig = RIGS.get(entry.path)
        found = rig in archive_entries_by_normalized_path
        return (SimpleNamespace(path=rig) if found else None), SimpleNamespace(reason="not in this set")

    monkeypatch.setattr("cdmw.core.skeleton_resolver.resolve_skeleton_for_model", resolve)
    # The editor's sets are bounded per opened PAC: each names its own skeleton, none a nude body.
    context = _context(_asset(OUTFIT, (0,), "loaded"), _asset(DRIVER, (1,), "body", _Dependencies((DRIVER, PHW_PAB))))
    alone = lookup.find_refit_reference_body(context, (0,), (1,), read_entry=read)
    assert alone.reference is None and "no skeleton was found" in alone.reason
    prepared = _Dependencies((OUTFIT, PHM_PAB, DRIVER, PHW_PAB, PHM_NUDE))
    found = lookup.find_refit_reference_body(context, (0,), (1,), read_entry=read, dependencies=prepared)
    assert found.reason == "" and found.reference.label == PHM_NUDE


BOSS_OUTFIT = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_knight/cd_m0001_00_knight_ub_0001.pac"
PHW_NPC_OUTFIT = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_02_phw/armor/cd_m0001_00_phw_ub_0001.pac"
BOSS_NUDE_PREFAB = "character/prefab/2_mon/cd_m0001_00_twofeet/cd_m0001_00_knight/cd_m0001_00_knight_nude_0001.prefabdata_xml"
FAMILY_NUDE_PREFAB = "character/prefab/2_mon/cd_m0001_00_twofeet/cd_m0001_00_imp/cd_m0001_00_imp_nude_0001.prefabdata_xml"
BOSS_PAB = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_artis/cd_m0001_00_artis.pab"


@pytest.mark.parametrize("outfit,prefab,named,body", [
    (BOSS_OUTFIT, BOSS_NUDE_PREFAB, "1_pc/1_phm/phm_01.pab", PHM_NUDE),
    # A character without a nude prefab of its own: its family's.
    (BOSS_OUTFIT, FAMILY_NUDE_PREFAB, "1_pc/1_phm/phm_01.pab", PHM_NUDE),
    # ... unless its path names a tied player rig (a female NPC folder).
    (PHW_NPC_OUTFIT, FAMILY_NUDE_PREFAB, "1_pc/1_phm/phm_01.pab", PHW_NUDE),
    # Not among the tied skeletons, or no nude prefab at all: the tie stays refused.
    (BOSS_OUTFIT, BOSS_NUDE_PREFAB, "1_pc/3_pgm/pgm_01.pab", None),
    (BOSS_OUTFIT, None, None, None),
])
def test_a_palette_tie_takes_the_skeleton_the_characters_nude_prefab_names(archive, monkeypatch, outfit, prefab, named, body):
    read, _reads = archive
    # Humanoid skeletons share bone names: a boss skeleton of the family outscores
    # the player rigs by path, and the resolver refuses the palette tie.
    candidates = (SimpleNamespace(path=BOSS_PAB, palette_hits=40, score=342), SimpleNamespace(path=PHW_PAB, palette_hits=40, score=336),
                  SimpleNamespace(path=PHM_PAB, palette_hits=40, score=336),
                  SimpleNamespace(path="character/model/1_pc/3_pgm/pgm_01.pab", palette_hits=12, score=300))

    def resolve(entry, **_kwargs):
        if entry.path == outfit:
            return None, SimpleNamespace(confidence="ambiguous_palette", reason="tied", candidates=candidates)
        return SimpleNamespace(path=RIGS[entry.path]), SimpleNamespace(reason="")

    def read_prefab(entry):
        return f'<Prefab><SkeletonName FileName="{named}"/></Prefab>'.encode() if entry.path == prefab else read(entry)

    monkeypatch.setattr("cdmw.core.skeleton_resolver.resolve_skeleton_for_model", resolve)
    paths = (outfit, DRIVER, BOSS_PAB, PHM_PAB, PHW_PAB, PHM_NUDE, PHW_NUDE, *((prefab,) if prefab else ()))
    context = _context(_asset(outfit, (0,), "loaded"), _asset(DRIVER, (1,), "body", _Dependencies(paths)))
    found = lookup.find_refit_reference_body(context, (0,), (1,), read_entry=read_prefab)
    if body:
        assert found.reason == "" and found.reference.label == body
    else:
        assert found.reference is None and "no skeleton was found for cd_m0001_00_knight_ub_0001.pac (tied)" in found.reason
    assert lookup.character_prefab_folders(BOSS_OUTFIT) == (
        "character/prefab/2_mon/cd_m0001_00_twofeet/cd_m0001_00_knight", "character/prefab/2_mon/cd_m0001_00_twofeet")


def test_a_prepared_archive_ticket_stops_waiting_when_cancelled_or_late():
    ticket = lookup.PreparedRefitReferenceArchive()
    late = ticket.wait(timeout_seconds=0.)
    assert late.dependencies is None and "in time" in late.reason

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        ticket.wait(cancelled)
    ticket.settle("set", "")
    ticket.settle(None, "ignored once finished")
    assert ticket.wait() == lookup.RefitReferenceArchive("set", "")
