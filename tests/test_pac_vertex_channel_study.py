from __future__ import annotations

import struct

import numpy as np
import pytest

from cdmw.domain.mesh.topology import validate_topology_provenance
from cdmw.modding.mesh_parser import SubMesh
from cdmw.modding.mesh_pac_topology_builder import (
    PROVEN_PAC_STRIDE,
    derived_skin_row,
    protected_byte_mask,
)
from tools import pac_vertex_channel_study as study


def _record(
    *,
    slots: tuple[int, ...] = (1, 2, 3, 0, 0, 0),
    weights: tuple[int, ...] = (200, 30, 25, 0, 0, 0),
    unknown_6_7: int = 0,
    unknown_12_15: int = 0,
    normal: int = 0,
    tail: bytes = b"\x00" * 6,
) -> bytes:
    record = bytearray(PROVEN_PAC_STRIDE)
    struct.pack_into("<H", record, 6, unknown_6_7)
    struct.pack_into("<I", record, 12, unknown_12_15)
    struct.pack_into("<I", record, 16, normal)
    for group, offset in enumerate((20, 24)):
        packed = 0
        for position in range(3):
            packed |= (slots[group * 3 + position] & 0x3FF) << (10 * position)
        struct.pack_into("<I", record, offset, packed)
    struct.pack_into("<6B", record, 28, *weights)
    record[34:40] = tail
    return bytes(record)


def _submesh(records: tuple[bytes, ...], faces: list[tuple[int, int, int]]) -> tuple[SubMesh, bytes]:
    payload = b"".join(records)
    submesh = SubMesh(
        name="part",
        vertices=[(float(index), 0.0, 0.0) for index in range(len(records))],
        faces=faces,
        source_vertex_offsets=[index * PROVEN_PAC_STRIDE for index in range(len(records))],
        source_vertex_stride=PROVEN_PAC_STRIDE,
        source_skin_weight_layout="pac_slot_u10x6",
        bone_indices=[(1, 2, 3)] * len(records),
        bone_weights=[(0.8, 0.12, 0.08)] * len(records),
    )
    return submesh, payload


# ── Candidate masks ──────────────────────────────────────────────────

def test_a_candidate_clears_only_the_bytes_it_names() -> None:
    base = protected_byte_mask(skinned=True)
    candidate = next(mask for mask in study.candidate_masks() if mask.name == "own_6_7")
    applied = candidate.applied_to(base)
    assert applied[6] == 0x00 and applied[7] == 0x00
    assert applied[12:16] == base[12:16]
    assert applied[19] == base[19] == 0xC0
    assert applied[34:40] == base[34:40]


def test_the_normal_candidate_clears_two_bits_and_not_the_whole_byte() -> None:
    base = protected_byte_mask(skinned=True)
    candidate = next(mask for mask in study.candidate_masks() if mask.name == "own_6_7_12_15_normal_top")
    applied = candidate.applied_to(base)
    # Byte 19 carries owned normal bits alongside the two protected ones, so a
    # candidate that owns those two must not be recorded as owning the byte.
    assert base[19] == 0xC0
    assert applied[19] == 0x00


def test_own_everything_leaves_nothing_protected() -> None:
    base = protected_byte_mask(skinned=True)
    candidate = next(mask for mask in study.candidate_masks() if mask.name == "own_everything")
    assert candidate.applied_to(base) == b"\x00" * PROVEN_PAC_STRIDE


# ── Edges and influence ──────────────────────────────────────────────

def test_shared_triangle_edges_are_counted_once() -> None:
    edges = study._unique_edges([(0, 1, 2), (1, 2, 3)], 4)
    assert [tuple(int(value) for value in row) for row in edges] == [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)]


def test_influence_union_agrees_with_the_shipping_derivation() -> None:
    fitting = (
        _record(slots=(1, 2, 3, 0, 0, 0), weights=(200, 30, 25, 0, 0, 0)),
        _record(slots=(3, 4, 5, 0, 0, 0), weights=(150, 55, 50, 0, 0, 0)),
    )
    overflowing = (
        _record(slots=(1, 2, 3, 4, 0, 0), weights=(100, 60, 50, 45, 0, 0)),
        _record(slots=(5, 6, 7, 8, 0, 0), weights=(100, 60, 50, 45, 0, 0)),
    )
    for records, expected in ((fitting, True), (overflowing, False)):
        live, empty = study._influence_columns(records)
        fits, unavailable = study._edge_influence_arrays(np.asarray([[0, 1]]), live, empty)
        assert bool(fits[0]) is expected
        assert bool(unavailable[0]) is False
        try:
            slots, _weights = derived_skin_row(records, (0.5, 0.5))
        except Exception:
            shipping_fits = False
        else:
            shipping_fits = len(slots) <= study.MAX_SKIN_INFLUENCES
        assert shipping_fits is expected


def test_a_parent_without_influence_is_reported_as_unavailable_not_as_fitting() -> None:
    records = (_record(), _record(weights=(0, 0, 0, 0, 0, 0)))
    live, empty = study._influence_columns(records)
    fits, unavailable = study._edge_influence_arrays(np.asarray([[0, 1]]), live, empty)
    assert bool(unavailable[0]) is True
    assert bool(fits[0]) is False


# ── The measured rule matches the shipping rule ──────────────────────

def test_the_vectorised_path_agrees_with_the_shipping_admission_rule() -> None:
    records = (
        _record(unknown_6_7=1),
        _record(unknown_6_7=2),
        _record(unknown_6_7=1),
    )
    edges = study._unique_edges([(0, 1, 2)], 3)
    matrix = np.frombuffer(b"".join(records), dtype=np.uint8).reshape(3, PROVEN_PAC_STRIDE)
    diff = matrix[edges[:, 0]] ^ matrix[edges[:, 1]]
    live, empty = study._influence_columns(records)
    fits, unavailable = study._edge_influence_arrays(edges, live, empty)
    import random

    result = study._verify_vectorised_path(
        records,
        edges,
        diff,
        fits,
        unavailable,
        protected_byte_mask(skinned=True),
        rng=random.Random(0),
        sample_size=len(edges),
    )
    assert result["agreed"] is True
    assert result["sampled_edges"] == len(edges)


# ── Subdivide replication ────────────────────────────────────────────

def test_subdividing_one_face_produces_four_faces_and_three_midpoints() -> None:
    records = tuple(_record() for _ in range(4))
    submesh, _payload = _submesh(records, [(0, 1, 2), (1, 2, 3)])
    edited, provenance = study._subdivide_edited_submesh(submesh, (0,))

    assert len(edited.faces) == 5  # one untouched face plus four children
    assert len(edited.vertices) == 7  # four originals plus three midpoints
    assert provenance.original_vertex_count == 4
    assert provenance.original_face_count == 2
    assert provenance.derived_vertex_count == 3
    # Every child triangle inherits the original face it came from, and the
    # untouched face keeps its own index.
    assert sorted(provenance.face_origins) == [0, 0, 0, 0, 1]
    assert not validate_topology_provenance(
        provenance, output_vertex_count=len(edited.vertices), output_face_count=len(edited.faces)
    )


def test_a_midpoint_is_shared_between_the_faces_that_meet_on_its_edge() -> None:
    records = tuple(_record() for _ in range(4))
    submesh, _payload = _submesh(records, [(0, 1, 2), (1, 2, 3)])
    edited, provenance = study._subdivide_edited_submesh(submesh, (0, 1))
    # Five unique edges across two triangles means five midpoints, not six.
    assert provenance.derived_vertex_count == 5
    assert len(edited.faces) == 8


# ── Operations, not edges ────────────────────────────────────────────

def _study_from_diff(diff: np.ndarray, faces: np.ndarray | None = None) -> study.SubmeshStudy:
    count = diff.shape[0]
    return study.SubmeshStudy(
        asset_path="synthetic",
        family="synthetic",
        submesh_index=0,
        submesh_name="part",
        vertex_count=count + 1,
        face_count=1,
        edge_count=count,
        edge_diff=diff,
        influence_fits=np.ones(count, dtype=bool),
        influence_unavailable=np.zeros(count, dtype=bool),
        face_edge_rows=faces,
    )


def test_one_blocked_edge_refuses_the_whole_selection() -> None:
    # Nine edges agree on every protected byte and one does not. The edge rate
    # is 90%, and the plan is explicit that this must never be reported as the
    # operation rate: a Loop Cut over all ten is refused outright.
    diff = np.zeros((10, PROVEN_PAC_STRIDE), dtype=np.uint8)
    diff[7][6] = 0x01
    measured = _study_from_diff(diff)
    measured.ring_samples = {10: [np.arange(10)], 4: [np.arange(4)]}

    baseline = next(mask for mask in study.candidate_masks() if mask.name == "baseline")
    report = study._candidate_report(
        [measured], baseline, protected_byte_mask(skinned=True), ring_lengths=(4, 10), face_counts=()
    )
    rates = {row["selected_edges"]: row["admissible_percent"] for row in report["operations"]["loop_cut"]}
    assert report["edge_diagnostics"]["combined_eligible_percent"] == pytest.approx(90.0)
    assert rates[10] == pytest.approx(0.0)
    assert rates[4] == pytest.approx(100.0)


def test_owning_the_blocking_byte_admits_the_selection_that_it_blocked() -> None:
    diff = np.zeros((10, PROVEN_PAC_STRIDE), dtype=np.uint8)
    diff[7][6] = 0x01
    measured = _study_from_diff(diff)
    measured.ring_samples = {10: [np.arange(10)]}

    candidate = next(mask for mask in study.candidate_masks() if mask.name == "own_6_7")
    report = study._candidate_report(
        [measured], candidate, protected_byte_mask(skinned=True), ring_lengths=(10,), face_counts=()
    )
    rates = {row["selected_edges"]: row["admissible_percent"] for row in report["operations"]["loop_cut"]}
    assert rates[10] == pytest.approx(100.0)


def test_a_single_face_needs_all_three_of_its_edges() -> None:
    diff = np.zeros((6, PROVEN_PAC_STRIDE), dtype=np.uint8)
    diff[5][12] = 0x01
    faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
    measured = _study_from_diff(diff, faces)

    baseline = next(mask for mask in study.candidate_masks() if mask.name == "baseline")
    report = study._candidate_report(
        [measured], baseline, protected_byte_mask(skinned=True), ring_lengths=(), face_counts=()
    )
    exhaustive = report["operations"]["subdivide_single_face_exhaustive"]
    assert exhaustive["faces"] == 2
    assert exhaustive["admissible"] == 1
    assert exhaustive["admissible_percent"] == pytest.approx(50.0)


def test_a_patch_never_grows_into_a_face_whose_edge_was_rejected() -> None:
    # Face 1 shares edge 1 with face 0 but carries a rejected edge of its own.
    # Growing into it would put -1 in the selection, and numpy reads -1 as the
    # last edge, which would price the patch against an unrelated record pair.
    face_edge_rows = np.asarray([[0, 1, 2], [1, 3, -1]], dtype=np.int64)
    edge_faces = {0: [0], 1: [0, 1], 2: [0], 3: [1]}
    usable = (face_edge_rows >= 0).all(axis=1)

    assert study._face_patch(0, 1, face_edge_rows, edge_faces, usable) is not None
    assert study._face_patch(0, 2, face_edge_rows, edge_faces, usable) is None


def test_a_face_with_a_rejected_edge_is_never_priced() -> None:
    diff = np.zeros((3, PROVEN_PAC_STRIDE), dtype=np.uint8)
    faces = np.asarray([[0, 1, 2], [0, 1, -1]], dtype=np.int64)
    measured = _study_from_diff(diff, faces)

    baseline = next(mask for mask in study.candidate_masks() if mask.name == "baseline")
    report = study._candidate_report(
        [measured], baseline, protected_byte_mask(skinned=True), ring_lengths=(), face_counts=()
    )
    assert report["operations"]["subdivide_single_face_exhaustive"]["faces"] == 1
