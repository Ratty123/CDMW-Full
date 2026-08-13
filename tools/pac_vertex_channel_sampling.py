"""Per-submesh sampling for the PAC vertex channel study.

Split out of :mod:`tools.pac_vertex_channel_study` to keep both files inside the
repository's owned-file size ratchet. This half holds one submesh's measurement
state and the geometry that selects what to measure: unique edges, influence
columns, straight chains, face patches, and the sampling that feeds them. The
admission rule still comes from
:mod:`cdmw.modding.mesh_pac_topology_builder` rather than a private copy, and
the vectorised path is still checked against it here.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

import numpy as np

from cdmw.domain.mesh.topology import (
    TOPOLOGY_PROTECTED_BYTES_DIVERGE,
    TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,
    SubmeshTopologyProvenance,
    VertexOrigin,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_pac_topology_builder import (
    PROVEN_PAC_STRIDE,
    PacTopologyRebuildBlocked,
    _decoded_live_slots,
    _masked,
    _original_records,
    _submesh_is_proven_layout,
    _submesh_is_skinned,
    derived_skin_row,
    protected_byte_mask,
    topology_rebuild_blockers,
)

MAX_SKIN_INFLUENCES = 6


# ── Per-submesh measurement ──────────────────────────────────────────

@dataclass
class SubmeshStudy:
    """Everything Phase 0 needs from one proven LOD0 submesh."""

    asset_path: str
    family: str
    submesh_index: int
    submesh_name: str
    vertex_count: int
    face_count: int
    edge_count: int
    #: (E, 40) uint8 of the XOR between the two parents of every unique edge.
    edge_diff: np.ndarray
    #: Per edge, whether the merged influence union fits six palette slots.
    influence_fits: np.ndarray
    #: Per edge, whether a parent carried no positive influence at all.
    influence_unavailable: np.ndarray
    #: Sampled operation selections, as arrays of edge indices.
    ring_samples: dict[int, list[np.ndarray]] = field(default_factory=dict)
    patch_samples: dict[int, list[np.ndarray]] = field(default_factory=dict)
    whole_submesh_edges: np.ndarray | None = None
    agreement_check: dict[str, object] = field(default_factory=dict)
    #: (F, 3) of edge indices per face, or -1 where the edge was rejected.
    face_edge_rows: np.ndarray | None = None


def _unique_edges(faces: Sequence[Sequence[int]], vertex_count: int) -> np.ndarray:
    """Unique undirected edges as an (E, 2) int64 array with ``a < b``."""
    if not faces:
        return np.zeros((0, 2), dtype=np.int64)
    tri = np.asarray(faces, dtype=np.int64)
    if tri.ndim != 2 or tri.shape[1] != 3:
        return np.zeros((0, 2), dtype=np.int64)
    pairs = np.concatenate((tri[:, (0, 1)], tri[:, (1, 2)], tri[:, (2, 0)]), axis=0)
    pairs = np.sort(pairs, axis=1)
    valid = (
        (pairs[:, 0] >= 0)
        & (pairs[:, 1] < vertex_count)
        & (pairs[:, 0] != pairs[:, 1])
    )
    pairs = pairs[valid]
    if pairs.size == 0:
        return np.zeros((0, 2), dtype=np.int64)
    return np.unique(pairs, axis=0)


def _influence_columns(records: Sequence[bytes]) -> tuple[list[frozenset[int]], np.ndarray]:
    """Live palette slots per vertex, and which vertices carry none."""
    live: list[frozenset[int]] = []
    empty = np.zeros(len(records), dtype=bool)
    for index, record in enumerate(records):
        slots, weights = _decoded_live_slots(record)
        if not slots or math.fsum(float(value) for value in weights) <= 0.0:
            empty[index] = True
            live.append(frozenset())
            continue
        live.append(frozenset(int(slot) for slot in slots))
    return live, empty


def _edge_influence_arrays(
    edges: np.ndarray,
    live: Sequence[frozenset[int]],
    empty: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    fits = np.zeros(len(edges), dtype=bool)
    unavailable = np.zeros(len(edges), dtype=bool)
    for index, (left, right) in enumerate(edges):
        if empty[left] or empty[right]:
            unavailable[index] = True
            continue
        fits[index] = len(live[left] | live[right]) <= MAX_SKIN_INFLUENCES
    return fits, unavailable


def _straightest_chain(
    seed: int,
    length: int,
    edges: np.ndarray,
    positions: np.ndarray,
    vertex_edges: Sequence[Sequence[int]],
) -> np.ndarray | None:
    """Grow an edge chain the way a user drags out a loop selection.

    This is a proxy, and the report says so. The native Loop Cut takes whatever
    edge set the user selected, and the editor has no ring-propagation command,
    so there is no ground-truth ring to measure. Straightest continuation is the
    standard heuristic for what an edge loop looks like, and it at least selects
    connected, geometrically coherent edges rather than scattered ones.
    """
    left, right = int(edges[seed][0]), int(edges[seed][1])
    chain = [seed]
    used = {seed}
    previous, current = left, right
    while len(chain) < length:
        incoming = positions[current] - positions[previous]
        norm = float(np.linalg.norm(incoming))
        if norm <= 0.0:
            return None
        incoming = incoming / norm
        best_edge = -1
        best_next = -1
        best_dot = -2.0
        for candidate in vertex_edges[current]:
            if candidate in used:
                continue
            a, b = int(edges[candidate][0]), int(edges[candidate][1])
            following = b if a == current else a
            if following == previous:
                continue
            outgoing = positions[following] - positions[current]
            out_norm = float(np.linalg.norm(outgoing))
            if out_norm <= 0.0:
                continue
            dot = float(np.dot(incoming, outgoing / out_norm))
            if dot > best_dot:
                best_dot = dot
                best_edge = candidate
                best_next = following
        if best_edge < 0:
            return None
        chain.append(best_edge)
        used.add(best_edge)
        previous, current = current, best_next
    return np.asarray(chain, dtype=np.int64)


def _face_patch(
    seed: int,
    count: int,
    face_edge_rows: np.ndarray,
    edge_faces: Mapping[int, Sequence[int]],
    usable: Sequence[bool] | np.ndarray,
) -> np.ndarray | None:
    """A connected patch of ``count`` faces, as the union of their edge indices.

    The patch refuses to grow into a face carrying an edge the unique-edge pass
    rejected. Such a face contributes ``-1``, which numpy would happily read as
    the last edge in the submesh and quietly price the selection against the
    wrong record pair.
    """
    order: list[int] = [seed]
    seen = {seed}
    cursor = 0
    while len(order) < count and cursor < len(order):
        for edge_index in face_edge_rows[order[cursor]]:
            for neighbour in edge_faces.get(int(edge_index), ()):
                if neighbour in seen or not bool(usable[neighbour]):
                    continue
                seen.add(neighbour)
                order.append(neighbour)
                if len(order) >= count:
                    break
            if len(order) >= count:
                break
        cursor += 1
    if len(order) < count:
        return None
    patch = np.unique(face_edge_rows[np.asarray(order, dtype=np.int64)].reshape(-1))
    if patch.size and int(patch[0]) < 0:
        return None
    return patch


def _sample_selections(
    study: SubmeshStudy,
    edges: np.ndarray,
    faces: Sequence[Sequence[int]],
    positions: np.ndarray,
    *,
    ring_lengths: Sequence[int],
    face_counts: Sequence[int],
    samples: int,
    rng: random.Random,
) -> None:
    edge_count = len(edges)
    face_count = len(faces)
    if edge_count <= 0 or face_count <= 0:
        return

    vertex_edges: list[list[int]] = [[] for _ in range(int(positions.shape[0]))]
    for index, (left, right) in enumerate(edges):
        vertex_edges[int(left)].append(index)
        vertex_edges[int(right)].append(index)

    edge_lookup = {(int(left), int(right)): index for index, (left, right) in enumerate(edges)}
    face_edge_rows = np.full((face_count, 3), -1, dtype=np.int64)
    edge_faces: dict[int, list[int]] = defaultdict(list)
    for face_index, face in enumerate(faces):
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        for slot, (left, right) in enumerate(((a, b), (b, c), (c, a))):
            key = (left, right) if left < right else (right, left)
            found = edge_lookup.get(key, -1)
            face_edge_rows[face_index][slot] = found
            if found >= 0:
                edge_faces[found].append(face_index)
    # A face with an edge the unique-edge pass rejected (degenerate or out of
    # range) cannot be priced honestly, so it is never a patch seed.
    usable_mask = (face_edge_rows >= 0).all(axis=1)
    usable_faces = np.flatnonzero(usable_mask)
    study.face_edge_rows = face_edge_rows

    for length in ring_lengths:
        collected: list[np.ndarray] = []
        attempts = 0
        limit = samples * 8
        while len(collected) < samples and attempts < limit:
            attempts += 1
            seed = rng.randrange(edge_count)
            chain = _straightest_chain(seed, int(length), edges, positions, vertex_edges)
            if chain is not None:
                collected.append(chain)
        study.ring_samples[int(length)] = collected

    for count in face_counts:
        collected = []
        attempts = 0
        limit = samples * 8
        while len(collected) < samples and attempts < limit and usable_faces.size:
            attempts += 1
            seed = int(usable_faces[rng.randrange(usable_faces.size)])
            patch = _face_patch(seed, int(count), face_edge_rows, edge_faces, usable_mask)
            if patch is not None:
                collected.append(patch)
        study.patch_samples[int(count)] = collected

    if usable_faces.size == face_count and face_count > 0:
        study.whole_submesh_edges = np.arange(edge_count, dtype=np.int64)


def _verify_vectorised_path(
    records: Sequence[bytes],
    edges: np.ndarray,
    diff: np.ndarray,
    fits: np.ndarray,
    unavailable: np.ndarray,
    mask: bytes,
    *,
    rng: random.Random,
    sample_size: int,
) -> dict[str, object]:
    """Prove the numpy path agrees with the shipping admission rule.

    The rest of this tool works on an XOR matrix for speed. That is only a valid
    stand-in for the serializer if it produces the same verdict, so a random
    sample of edges is put through the imported rule as well, against the exact
    arrays the report will summarise. Any disagreement fails the run.
    """
    if len(edges) == 0:
        return {"sampled_edges": 0, "protected_disagreements": 0, "influence_disagreements": 0, "agreed": True}
    count = min(int(sample_size), len(edges))
    picks = rng.sample(range(len(edges)), count)
    mask_array = np.frombuffer(mask, dtype=np.uint8)
    protected_mismatch = 0
    influence_mismatch = 0
    for index in picks:
        left, right = int(edges[index][0]), int(edges[index][1])
        shipping_agrees = _masked(records[left], mask) == _masked(records[right], mask)
        if shipping_agrees != (not bool(np.any(diff[index] & mask_array))):
            protected_mismatch += 1
        try:
            slots, _weights = derived_skin_row((records[left], records[right]), (0.5, 0.5))
        except PacTopologyRebuildBlocked:
            shipping_fits = False
        else:
            shipping_fits = len(slots) <= MAX_SKIN_INFLUENCES
        if shipping_fits != (bool(fits[index]) and not bool(unavailable[index])):
            influence_mismatch += 1
    return {
        "sampled_edges": count,
        "protected_disagreements": int(protected_mismatch),
        "influence_disagreements": int(influence_mismatch),
        "agreed": protected_mismatch == 0 and influence_mismatch == 0,
    }


def _subdivide_edited_submesh(
    original: SubMesh,
    face_indices: Sequence[int],
) -> tuple[SubMesh, SubmeshTopologyProvenance]:
    """The exact result the native midpoint Subdivide produces for a selection.

    Replicated from ``run_subdivide_edit_for_submesh``: every selected triangle
    becomes four, each of its three edges gets one midpoint, midpoints are shared
    by edge key, and every child triangle inherits its parent's original face
    index.
    """
    vertices = [tuple(float(value) for value in position) for position in original.vertices]
    origins: list[VertexOrigin] = [VertexOrigin((index,), (1.0,)) for index in range(len(vertices))]
    midpoints: dict[tuple[int, int], int] = {}

    def midpoint(left: int, right: int) -> int:
        key = (left, right) if left < right else (right, left)
        found = midpoints.get(key)
        if found is not None:
            return found
        first, second = vertices[key[0]], vertices[key[1]]
        index = len(vertices)
        vertices.append(tuple((first[axis] + second[axis]) * 0.5 for axis in range(3)))
        origins.append(VertexOrigin(key, (0.5, 0.5)))
        midpoints[key] = index
        return index

    selected = {int(value) for value in face_indices}
    faces: list[tuple[int, int, int]] = []
    face_origins: list[int] = []
    for face_index, face in enumerate(original.faces):
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        if face_index not in selected:
            faces.append((a, b, c))
            face_origins.append(face_index)
            continue
        ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
        faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        face_origins.extend((face_index,) * 4)

    provenance = SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=len(original.vertices),
        original_face_count=len(original.faces),
        vertex_origins=tuple(origins),
        face_origins=tuple(face_origins),
    )
    edited = replace(original, vertices=vertices, faces=faces, topology_provenance=provenance)
    return edited, provenance


def _blocker_path_crosscheck(
    mesh: ParsedMesh,
    payload: bytes,
    studies: Sequence[SubmeshStudy],
    baseline_eligible: Mapping[int, np.ndarray],
    face_edge_rows: Mapping[int, np.ndarray],
    *,
    samples: int,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Run real selections through ``topology_rebuild_blockers`` and compare.

    The fast path above measures a rule; this measures the gate. They must agree
    on whether a given selection is admissible, and if the gate refuses these
    assets for some structural reason the fast path never models, the eligibility
    numbers would be beside the point, so the full blocker set is recorded.
    """
    rows: list[dict[str, object]] = []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    for study in studies:
        if study.submesh_index >= len(submeshes):
            continue
        eligible = baseline_eligible.get(study.submesh_index)
        rows_for_edges = face_edge_rows.get(study.submesh_index)
        if eligible is None or rows_for_edges is None or rows_for_edges.size == 0:
            continue
        original = submeshes[study.submesh_index]
        usable = np.flatnonzero((rows_for_edges >= 0).all(axis=1))
        if usable.size == 0:
            continue
        # Random faces mostly land on refusals, so deliberately include faces
        # whose own edges are already eligible. Without them the admissible
        # branch of the gate might never be exercised and the check would prove
        # only that both sides can say no.
        admissible_faces = usable[np.asarray([bool(eligible[rows_for_edges[face]].all()) for face in usable])]
        picks: list[int] = []
        for _ in range(int(samples)):
            picks.append(int(usable[rng.randrange(usable.size)]))
        if admissible_faces.size:
            for _ in range(int(samples)):
                picks.append(int(admissible_faces[rng.randrange(admissible_faces.size)]))

        for face_index in picks:
            edited_submesh, _provenance = _subdivide_edited_submesh(original, (face_index,))
            edited_list = list(submeshes)
            edited_list[study.submesh_index] = edited_submesh
            edited_mesh = replace(mesh, submeshes=edited_list)
            try:
                blockers = topology_rebuild_blockers(mesh, edited_mesh, payload)
            except Exception as error:  # pragma: no cover - defensive, reported
                rows.append(
                    {
                        "submesh_index": study.submesh_index,
                        "face_index": int(face_index),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            derivation_blocked = bool(
                {TOPOLOGY_PROTECTED_BYTES_DIVERGE, TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED} & set(blockers)
            )
            simulated_admissible = bool(eligible[rows_for_edges[face_index]].all())
            rows.append(
                {
                    "submesh_index": study.submesh_index,
                    "face_index": int(face_index),
                    "simulated_admissible": simulated_admissible,
                    "gate_derivation_blocked": derivation_blocked,
                    "agreed": simulated_admissible == (not derivation_blocked),
                    "gate_blockers": list(blockers),
                }
            )
    return rows
