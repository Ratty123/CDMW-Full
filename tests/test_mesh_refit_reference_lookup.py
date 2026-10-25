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
