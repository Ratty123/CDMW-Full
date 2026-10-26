"""Fit to body's skin weight table: driver bones onto each garment palette, and which Parts take part."""
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import (
    PAC_SKIN_GATE_DISABLED,
    PAC_SKIN_GATE_OFFSET,
    PAC_SKIN_WEIGHT_LAYOUT,
    SubMesh,
)
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services import mesh_refit_weights as weights
from cdmw.services.mesh_archive_refit import ArchiveRefitAsset

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def _skeleton(*bones):
    return Skeleton(path="rig.pab", bones=[
        Bone(index=index, name=name, parent_index=parent, bind_matrix=IDENTITY)
        for index, (name, parent) in enumerate(bones)])


# The driver has a chest helper the garment's rig lacks, and a hand its palette does not use.
DRIVER = _skeleton(("Root", -1), ("Spine", 0), ("L Chest", 1), ("L Arm", 1), ("L Hand", 3))
GARMENT = _skeleton(("Root", -1), ("Spine", 0), ("L Arm", 1))


def test_each_driver_bone_lands_on_its_named_slot_or_its_nearest_named_ancestor():
    # Garment palette: slot 0 is the arm, slot 1 the spine.
    assert weights.driver_bone_slots(DRIVER, GARMENT, (2, 1)) == (-1, 1, 1, 0, 0)


def _part(gates, *, layout=PAC_SKIN_WEIGHT_LAYOUT):
    count = len(gates)
    return SubMesh(
        name="cloth", material="cloth", texture="", vertices=[(float(i), 0., 0.) for i in range(count)],
        faces=[(0, 1, 2)], bone_indices=[(0,)] * count, bone_weights=[(1.,)] * count,
        source_vertex_map=list(range(count)), source_vertex_offsets=[40 * i for i in range(count)],
        source_vertex_stride=40, source_skin_weight_layout=layout,
    )


def _data(gates):
    data = bytearray(40 * len(gates))
    for vertex, gate in enumerate(gates):
        data[40 * vertex + PAC_SKIN_GATE_OFFSET] = gate
    return bytes(data)


def _asset(path, parts, indices, role, gates=(), appearance=None):
    return ArchiveRefitAsset(
        entry=SimpleNamespace(path=path),
        source=SimpleNamespace(original_data=_data(gates), mesh=SimpleNamespace(submeshes=parts)),
        part_indices=tuple(indices), role=role, preview_lease=None, neutral_appearance=appearance,
    )


def test_only_parts_the_exact_writer_can_store_take_the_body_weights(monkeypatch):
    # Slots resolve to the arm and spine for garments, to all driver bones for the body.
    monkeypatch.setattr(weights, "resolve_pac_bone_palette",
                        lambda data, skeleton: (2, 1) if skeleton is GARMENT else (0, 1, 2, 3, 4))
    gates = (PAC_SKIN_GATE_DISABLED, 5, PAC_SKIN_GATE_DISABLED)
    good, foreign = _part(gates), _part(gates, layout="other")
    driver = _asset("body.pac", [], (3,), "body")
    table, reason = weights.build_refit_weight_transfer(DRIVER, GARMENT, driver, (
        _asset("outfit.pac", [good, foreign], (0, 1), "loaded", gates),
        _asset("hood.pac", [_part(gates)], (2,), "loaded", gates, appearance=object()),
    ), lambda entry: b"body", reference=([_part(gates)], (1, 2)))
    assert reason == ""
    assert table.garment_slots == {0: (-1, 1, 1, 0, 0)}
    # How the garment and its authored body move in each design pose (none of
    # these bones is a Biped bone, so nothing moves here).
    poses = len(weights.DESIGN_POSES)
    assert table.garment_motion[0].shape == (3, poses, 3) and table.reference_motion.shape == (3, poses, 3)
    # Cloth-simulated records hold four influences.
    assert table.capacities == {0: (6, 4, 6)} and table.palette_sizes == {0: 2}
    assert table.driver_bones == {3: (0, 1, 2, 3, 4)}
    assert any("hood.pac is shown in a character appearance" in item for item in table.kept)
    assert any("cannot have its weights written in place" in item for item in table.kept)
    payload = table.payload()
    assert payload["garments"] == [{"submesh_index": 0, "slots": [-1, 1, 1, 0, 0], "capacities": [6, 4, 6],
                                    "motion": [0.] * (3 * poses * 3)}]
    assert payload["motion_poses"] == poses and payload["reference_motion"] == [0.] * (3 * poses * 3)


def test_no_table_without_a_resolvable_body_palette(monkeypatch):
    monkeypatch.setattr(weights, "resolve_pac_bone_palette", lambda data, skeleton: ())
    table, reason = weights.build_refit_weight_transfer(
        DRIVER, GARMENT, _asset("body.pac", [], (1,), "body"), (), lambda entry: b"")
    assert table is None and reason == "the body's bones do not match its skeleton"


@pytest.mark.parametrize("gate,capacity", [(PAC_SKIN_GATE_DISABLED, 6), (0, 4)])
def test_record_capacity_follows_its_cloth_gate(gate, capacity):
    from cdmw.modding.mesh_pac_skin_contract import pac_skin_row_capacity

    assert pac_skin_row_capacity(_data((gate,)), 0) == capacity
