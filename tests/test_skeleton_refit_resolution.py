from __future__ import annotations

import struct
from pathlib import PurePosixPath

import pytest

from cdmw.core.skeleton_resolver import (
    _descriptor_model_identity_compatible,
    resolve_skeleton_for_model,
)
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette
from tests.test_release_inspired_improvements import _entry, _pab_payload
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames


HASHES = tuple(0xABCDEF00 + index for index in range(8))
MODEL = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_02_phw/armor_south/9_upperbody/cd_m0001_00_so_phw_ub_22002.pac"


@pytest.mark.parametrize("family", ["phw", "phm", "ptm", "ppdm"])
def test_npc_equipment_retains_its_embedded_player_rig_candidate(family):
    assert f"{family}_01.pab" in iter_pab_candidate_basenames(MODEL.replace("phw", family))


def _pab(hashes):
    header = bytearray(_pab_payload()[:0x16])
    struct.pack_into("<H", header, 0x14, len(hashes))
    return bytes(header) + b"".join(
        _pab_payload(name=f"Bone{index}", name_hash=value)[0x16:]
        for index, value in enumerate(hashes)
    )


def _resolve(payloads):
    model = _entry(MODEL)
    entries = tuple(_entry(path, data=data) for path, data in payloads.items())
    paths = {entry.path.lower(): (entry,) for entry in entries}
    names = {}
    for entry in entries:
        names.setdefault(PurePosixPath(entry.path).name.lower(), []).append(entry)
    return resolve_skeleton_for_model(
        model, entries,
        archive_entries_by_normalized_path=paths,
        archive_entries_by_basename=names,
        pac_data=_with_resolvable_bone_palette(_pac_fixture(skinned=True), HASHES),
        read_entry_data=lambda entry: payloads[entry.path],
    )


@pytest.mark.parametrize("model_prefix,descriptor_prefix", [("cd_", ""), ("", "cd_"), ("", ""), ("cd_", "cd_")])
def test_legacy_prefix_cannot_join_unrelated_named_npc_families(model_prefix, descriptor_prefix):
    assert not _descriptor_model_identity_compatible(
        f"{model_prefix}m0001_00_so_phw_ub_22002.pac",
        f"{descriptor_prefix}m0001_00_bear_nude_0002.prefabdata_xml",
    )
    assert _descriptor_model_identity_compatible(
        f"{model_prefix}m0001_00_bear_head_0002.pac",
        f"{descriptor_prefix}m0001_00_bear_head_0002.prefabdata_xml",
    )


@pytest.mark.parametrize("shared_hashes", [0, 7])
def test_descriptor_cannot_override_complete_palette_evidence(shared_hashes):
    correct = "character/model/1_pc/2_phw/phw_01.pab"
    wrong = "character/model/2_mon/wrong.pab"
    descriptor = MODEL.replace("/model/", "/prefab/").replace(".pac", ".prefabdata_xml")
    selected, report = _resolve({
        descriptor: f'<PrefabData><SkeletonName FileName="{wrong}" /></PrefabData>'.encode(),
        wrong: _pab((*HASHES[:shared_hashes], *(0xBEEEEE00 + i for i in range(8 - shared_hashes)))),
        correct: _pab(HASHES),
    })
    assert selected.path == correct
    assert report.confidence == "palette"
    assert report.descriptor_path == ""
    assert report.skeleton_variation_path == ""


def test_matching_descriptor_keeps_its_authoritative_context():
    correct = "character/model/1_pc/2_phw/phw_01.pab"
    descriptor = MODEL.replace("/model/", "/prefab/").replace(".pac", ".prefabdata_xml")
    selected, report = _resolve({
        descriptor: f'<PrefabData><SkeletonName FileName="{correct}" /></PrefabData>'.encode(),
        correct: _pab(HASHES),
    })
    assert selected.path == correct
    assert report.confidence == "descriptor"
    assert report.descriptor_path == descriptor


def test_partial_palette_match_is_reported_as_unresolved():
    selected, report = _resolve({"character/model/wrong.pab": _pab(HASHES[:-1])})
    assert selected is None
    assert "palette" in report.blocking_errors[0]


def test_equal_complete_palettes_require_a_distinguishing_identity():
    selected, report = _resolve({
        "character/skeleton/a.pab": _pab(HASHES),
        "character/skeleton/b.pab": _pab(HASHES),
    })
    assert selected is None
    assert report.confidence == "ambiguous_palette"
