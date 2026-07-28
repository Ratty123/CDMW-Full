"""Skin `.pac` character geometry to the animated skeleton.

A `.pac` vertex carries four bone influences and four `u8` weights; each submesh holds a
`source_bone_palette` mapping those influence slots onto skeleton bone indices. With the
`.pab`'s inverse bind matrices that is everything needed to deform the body and its armour
with the pose, so the meshes move with the animation instead of standing frozen at bind
while the skeleton walks out of them.

The maths is the standard linear blend, in the row-vector convention the rest of the studio
uses:

    v' = sum_i  w_i * ( v * inverse_bind[b_i] * world[b_i] )

NumPy does the per-vertex work; a pure-Python loop over ~30,000 vertices per frame is not a
viable option at playback rates.

**Only the primary influence is usable, but the slot table is read, not derived.**

`mesh_parser` documents that a PAC vertex's four influence slots are not four bone indices:
only slot 0 decodes, and bytes 21-23 are a packed field. Reading all four is what made the
index space look 253 wide with nonsense bones attached — the primary slot alone tops out at
74 on the body meshes, and every value lands on an anatomically sensible bone.

This file used to claim the slot table was absent and had to be recovered from geometry, by
clustering the vertices a slot drives and matching the cluster to the nearest bone. That was
wrong, and the earlier scan that seemed to prove it only looked at the first 4 KB. Searched
whole, **every** mesh carries a palette of `.pab` bone-name hashes that resolves against the
rig exactly: 189 bones in Kliff's body, 206 in Damian's, 77 in a coat, 20 in a boot — and in
each file exactly one of the thousands of byte runs that merely *look* like a palette resolves
completely, so there is nothing to guess between.

The guess held up only while the body was a coat and a pair of trousers. A whole anatomy has
fifteen bones inside a hand, and nearest-centroid pairs fingers with the wrong knuckles: the
mesh tore itself apart the moment a pose moved. `derive_bone_map` survives as the fallback for
a file whose palette will not resolve, guarded by `MAX_DRIFT` — but note that drift is *its*
metric, which it minimises by construction, so it is not applied to an exact palette.

**Two of the four influences are usable, so joints bend rather than crease.**

The skin used to be rigid — one bone per vertex — and it looked it: an elbow's vertices snapped
to either the upper arm or the forearm with nothing between them, so every joint tore open
instead of bending. The file has four weights, descending and summing to 255, and the second
bone is at byte 24 of the vertex record. It is a real bone: where the second weight is zero,
byte 24 is zero 99.3% of the time, and where it is set it resolves to a bone a median 0.15 m
from the primary against 0.65 m for a random one.

Bytes 32 and 33 track the third and fourth weights just as tightly but are *not* bone indices —
read as palette slots they land 0.44 m away, worse than chance — so influences 3 and 4 are
left undecoded rather than guessed at. A two-bone blend is not the game's four-bone one, and
tight creases will still be shallower here than in game.

A blend is only taken between bones that are near each other; see `_neighbouring`. Without any
gate the far pairs stretch their triangles into slivers, which showed up as fresh tearing across
a coat's shoulder. Gating on the *hierarchy* alone was the opposite error — it kept only 15.8%
of the vertices the file offers a second bone for, so joints stayed nearly as stiff as before.

The second bone keeps its true share of 255 rather than being renormalised against the primary;
`_second_influence` records what that measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from .model import Vec3

#: Armour and body slots worth drawing on the rig, in the order they should stack.
WEARABLE_SLOTS = (
    "1_head", "2_hair", "3_face", "8_neck",
    "9_upperbody", "10_lowerbody", "11_hand", "12_foot",
)


class SkinError(RuntimeError):
    """Raised when geometry cannot be skinned to the given skeleton."""


@dataclass(slots=True)
class SkinnedMesh:
    """Geometry plus the influences that let it follow a pose."""

    name: str
    #: (N, 4) homogeneous rest positions.
    rest: np.ndarray
    #: (T, 3) triangle indices.
    faces: np.ndarray
    #: (N, 4) skeleton bone indices, and (N, 4) weights that sum to 1.
    bones: np.ndarray
    weights: np.ndarray
    source_path: str = ""

    @property
    def vertex_count(self) -> int:
        return int(self.rest.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.faces.shape[0])

    @property
    def empty(self) -> bool:
        return self.vertex_count == 0 or self.triangle_count == 0


def _matrix_array(matrices: Sequence[Sequence[float]]) -> np.ndarray:
    return np.asarray(matrices, dtype=np.float64).reshape(-1, 4, 4)


#: Refuse a mesh whose slots cannot be placed this close to a bone. Correct mappings sit at a
#: few centimetres; a wrong one is half the height of the character.
MAX_DRIFT = 0.18

#: The record's marker for an influence slot that is not used.
PAC_UNUSED_SLOT = 0xFF

#: How far apart two bones may sit and still be blended between, in metres. Bones that meet at
#: a joint are accepted whatever their length; this only widens that to the helper bones packed
#: around a joint, whose median separation from the bone they assist is 0.15 m. Beyond it a
#: pairing reaches across the body, and blending towards it stretches the triangle into a
#: sliver — which is what tore a coat's shoulder open when both influences were first used.
NEAR_BONE = 0.25


def derive_bone_map(points: np.ndarray, slots: Sequence[int], skeleton) -> dict:
    """Match each influence slot to the bone its vertices are clustered on.

    The file does not carry the table, but the geometry does: vertices driven by a bone sit
    on that bone. Ambiguity between a bone and its `_sub` twin barely matters — they share a
    position, so a rigid skin bound to either lands in the same place.
    """

    origins = np.asarray([
        (b.bind_matrix[12], b.bind_matrix[13], b.bind_matrix[14])
        if len(b.bind_matrix) == 16 else (1e6, 1e6, 1e6)
        for b in skeleton.bones
    ], dtype=np.float64)
    grouped: dict[int, List[int]] = {}
    for index, slot in enumerate(slots):
        grouped.setdefault(int(slot), []).append(index)
    mapping: dict[int, int] = {}
    for slot, members in grouped.items():
        centre = points[members].mean(axis=0)
        mapping[slot] = int(np.argmin(np.linalg.norm(origins - centre, axis=1)))
    return mapping


def _resolved_palette(data: bytes, skeleton) -> tuple:
    """The file's bone palette, mapped onto this rig by name hash.

    The shared resolver only looks at the first 4 KB, which is where a body keeps its palette.
    Armour keeps it further in — a coat, a boot and a helmet all came back with nothing, and
    every one of them resolves once the whole file is searched. So the cheap scan runs first and
    the wide one is the fallback, which costs 0.15–0.6 s and only on a piece being worn.

    A candidate has to resolve *completely*: every hash a bone this rig actually has. That is a
    strong enough filter to be unambiguous in practice — of the 2,226 tables that merely look
    like a palette in a body mesh, exactly one resolves.
    """

    from cdmw.modding.mesh_parser import (
        pac_bone_palette_candidates,
        resolve_pac_bone_palette,
    )

    palette = resolve_pac_bone_palette(data, skeleton)
    if palette:
        return palette
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    if not bones:
        return ()
    by_hash: dict = {}
    for position, bone in enumerate(bones):
        try:
            by_hash.setdefault(int(getattr(bone, "name_hash", 0)), position)
        except (TypeError, ValueError):
            continue
    best: tuple = ()
    for candidate in pac_bone_palette_candidates(data, search_limit=len(data)):
        if len(candidate) <= len(best):
            continue
        resolved = tuple(by_hash.get(value, -1) for value in candidate)
        if all(index >= 0 for index in resolved):
            best = resolved
    return best


#: Where the second influence lives in the 40-byte PAC vertex record, and where the four
#: weights live. Byte 20 is the primary bone, byte 24 the second; both index the file's palette.
_SECOND_BONE = 24
_WEIGHTS = 28


def _second_influence(data: bytes, offset: int):
    """The second bone driving a vertex, and how much of it, as a palette slot and 0..1 share.

    A vertex carries four weights — they descend, they sum to 255, and the primary averages
    68% — but the file was being read as though only one bone existed, which is why every joint
    creased instead of bending: an elbow's vertices snapped rigidly to either the upper arm or
    the forearm with nothing in between.

    Only two of the four influences are actually indexable. Byte 20 and byte 24 both land inside
    the palette and behave like bones: when the second weight is zero, byte 24 is zero 99.3% of
    the time, and where it is set it resolves to a bone a median 0.15 m from the primary, with
    74% inside 20 cm — against 0.65 m and 6% for a random bone. Bytes 32 and 33 track the third
    and fourth weights just as tightly but are *not* bones: read as palette slots they sit
    0.44 m away, worse than chance. So they are left alone rather than guessed at.

    A zero slot is treated as absent. It is legitimately palette entry 0, but including those
    vertices drops the adjacency from 74% to 50% — the blend they would produce reaches across
    the body, so a rigid vertex is the better error.
    """

    if offset < 0 or offset + _WEIGHTS + 2 > len(data):
        return 0, 0.0
    slot = data[offset + _SECOND_BONE]
    if slot == 0 or slot == PAC_UNUSED_SLOT:
        return 0, 0.0
    second = data[offset + _WEIGHTS + 1]
    if second == 0:
        return 0, 0.0
    # The second bone keeps its true share of the whole 255, and what the two undecoded
    # influences were carrying stays on the primary. Renormalising over w0+w1 instead — giving
    # the second bone the missing weight in proportion — over-rotates the vertex: measured
    # across six poses on both characters it raised the badly-stretched face count on five of
    # them, worse than the rigid skin it replaced, while this reduced peak stretch on all six.
    # It is the better approximation because influences three and four sit near the primary.
    return int(slot), second / 255.0


def _neighbouring(skeleton, first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Whether two bones are joined in the rig — parent, child, or sharing a parent.

    A blend is only meaningful between bones that meet at a joint. Most pairs in the file are:
    the second bone sits a median 0.15 m from the primary, 74% of them within 20 cm. The rest
    are not, and blending a vertex towards a bone on the other side of the body stretches its
    triangles into long slivers — which is what showed up as fresh tearing across a coat's
    shoulder the first time both influences were used.

    Hierarchy alone is too strict to use by itself. This rig has 434 bones, most of them
    helpers — roll bones, `_sub` twins — sitting between the ones an animator would name, so a
    vertex routinely blends between two bones that are near neighbours in space without being
    parent, child or sibling. Gating on the hierarchy only kept 15.8% of the vertices the file
    offers a second bone for, and threw away 32.2% whose median separation was 0.153 m: real
    joints, discarded, which is why joints still creased after both influences were read.

    So proximity is admitted as well, bounded. It cannot stand alone — a thigh is 0.4 m end to
    end, and any threshold loose enough to keep it also admits unrelated bones — but as a
    *widening* of an exact test it only ever adds pairs that are already close together.
    """

    bones = getattr(skeleton, "bones", ()) or ()
    if not len(bones):
        return np.zeros(len(first), dtype=bool)
    parents = np.asarray(
        [int(getattr(bone, "parent_index", -1)) for bone in bones], dtype=np.int64
    )
    # -1 is "no parent"; pointing it at itself keeps the comparisons below in bounds without
    # making two root-parented bones look like siblings of each other.
    safe = np.clip(first, 0, len(parents) - 1), np.clip(second, 0, len(parents) - 1)
    parent_of_first = parents[safe[0]]
    parent_of_second = parents[safe[1]]
    joined = (
        (parent_of_second == safe[0])
        | (parent_of_first == safe[1])
        | ((parent_of_first == parent_of_second) & (parent_of_first >= 0))
    )
    origins = np.asarray([
        (b.bind_matrix[12], b.bind_matrix[13], b.bind_matrix[14])
        if len(b.bind_matrix) == 16 else (1e6, 1e6, 1e6)
        for b in bones
    ], dtype=np.float64)
    gap = np.linalg.norm(origins[safe[0]] - origins[safe[1]], axis=1)
    return joined | (gap <= NEAR_BONE)


def _bone_column(palette: tuple, primary, rest_array, skeleton):
    """Which skeleton bone drives each vertex.

    A `.pac` influence slot is not a bone index — it indexes the file's own palette of bone
    name *hashes*. The palette can be read and resolved against the rig exactly, which is what
    `resolve_pac_bone_palette` does.

    Matching by proximity instead — assume each slot belongs to whichever bone sits nearest the
    average of the vertices using it — was what this did before, and it held up only while the
    body was a coat and a pair of trousers. On a whole anatomy it does not: a hand has fifteen
    bones inside a few centimetres, so the nearest-centroid guess pairs fingers with the wrong
    knuckles and the mesh tears itself apart the moment a pose moves. The proximity map stays as
    the fallback for a file whose palette will not resolve, because a slightly wrong body still
    beats no body at all.
    """

    if palette:
        column = [palette[slot] if 0 <= slot < len(palette) else 0 for slot in primary]
        return np.asarray(column, dtype=np.int32), True
    mapping = derive_bone_map(rest_array[:, :3], primary, skeleton)
    return np.asarray([mapping.get(slot, 0) for slot in primary], dtype=np.int32), False


def load_skinned(data: bytes, path: str, skeleton) -> Optional[SkinnedMesh]:
    """Decode a `.pac` and bind its primary influences onto `skeleton`.

    Returns None when the file carries no skin data, or when the derived mapping cannot place
    the slots near a bone — a mesh silently bound to bone zero follows the root around the map.
    """

    from cdmw.modding.mesh_parser import parse_mesh

    name = path.rsplit("/", 1)[-1]
    parsed = parse_mesh(data, name)
    if not parsed.submeshes or not parsed.has_bones:
        return None

    rest: List[tuple] = []
    faces: List[tuple] = []
    primary: List[int] = []
    secondary: List[int] = []
    blend: List[float] = []
    base = 0
    for submesh in parsed.submeshes:
        if not submesh.vertices or not submesh.faces:
            continue
        count = len(submesh.vertices)
        offsets = getattr(submesh, "source_vertex_offsets", None) or ()
        for index in range(count):
            x, y, z = submesh.vertices[index]
            rest.append((x, y, z, 1.0))
            slots = submesh.bone_indices[index] if index < len(submesh.bone_indices) else ()
            # The parser's tuple is bytes 20-23 of the record, and only the first of those is a
            # bone. The *second* bone is at byte 24 — see `_second_influence`.
            primary.append(int(slots[0]) if slots else 0)
            slot, weight = _second_influence(
                data, offsets[index] if index < len(offsets) else -1
            )
            secondary.append(slot)
            blend.append(weight)
        for a, b, c in submesh.faces:
            faces.append((a + base, b + base, c + base))
        base += count

    if not rest or not faces:
        return None
    rest_array = np.asarray(rest, dtype=np.float64)
    # Resolved once. The wide scan behind it walks the whole file, so asking twice — once for
    # the primary bone and again for the second — doubled the cost of loading a character.
    try:
        palette = _resolved_palette(data, skeleton)
    except Exception:  # noqa: BLE001 - an unreadable palette is a fallback, not a failure
        palette = ()
    column, exact = _bone_column(palette, primary, rest_array, skeleton)
    # The second influence indexes the same palette, so it only means anything when the palette
    # resolved. Under the proximity fallback the slot is not a bone at all and blending towards
    # it would smear the mesh, so that path stays rigid — as it always was.
    second_column = column
    share = np.zeros(len(primary), dtype=np.float64)
    if exact:
        second_column = np.asarray(
            [palette[s] if 0 <= s < len(palette) else 0 for s in secondary], dtype=np.int32
        )
        share = np.asarray(blend, dtype=np.float64)
        share[second_column == column] = 0.0
        share[~_neighbouring(skeleton, column, second_column)] = 0.0
    mesh = SkinnedMesh(
        name=name,
        rest=rest_array,
        faces=np.asarray(faces, dtype=np.int32),
        bones=np.stack((column, second_column, column, column), axis=1),
        weights=np.stack(
            (1.0 - share, share, np.zeros_like(share), np.zeros_like(share)), axis=1
        ),
        source_path=path,
    )
    # The drift guard exists to catch the *guess* going wrong. A hash-resolved palette is not a
    # guess, and it scores worse by construction — `derive_bone_map` picks whichever bone is
    # nearest, so it minimises this number even when the pairing it invents is nonsense. Judging
    # the exact binding by the heuristic's own metric would throw away correct armour.
    if not exact and dominant_bone_drift(mesh, skeleton) > MAX_DRIFT:
        return None
    return mesh


def skin_matrices(skeleton, world: Sequence[Sequence[float]]) -> np.ndarray:
    """`inverse_bind * world` per bone — what takes a rest vertex to its posed position."""

    inverse = _matrix_array([
        bone.inv_bind_matrix if len(bone.inv_bind_matrix) == 16 else _IDENTITY
        for bone in skeleton.bones
    ])
    posed = _matrix_array(list(world))
    if inverse.shape[0] != posed.shape[0]:
        raise SkinError("skeleton and pose disagree on bone count")
    return inverse @ posed


_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def deform(mesh: SkinnedMesh, matrices: np.ndarray) -> np.ndarray:
    """Linear blend skin. Returns (N, 3) world positions."""

    out = np.zeros((mesh.vertex_count, 3), dtype=np.float64)
    for slot in range(mesh.bones.shape[1]):
        weight = mesh.weights[:, slot]
        if not np.any(weight):
            continue
        picked = matrices[mesh.bones[:, slot]]           # (N, 4, 4)
        moved = np.einsum("nj,njk->nk", mesh.rest, picked)[:, :3]
        out += weight[:, None] * moved
    return out


def dominant_bone_drift(mesh: SkinnedMesh, skeleton) -> float:
    """Median distance from a vertex to the bind position of its heaviest bone.

    A wrong palette mapping still produces unit weights and a plausible-looking mesh, so the
    check that matters is spatial: vertices have to sit near the bone that drives them. On a
    correct mapping this is centimetres; on a scrambled one it is the size of the character.
    """

    heaviest = np.argmax(mesh.weights, axis=1)
    bone_index = mesh.bones[np.arange(mesh.vertex_count), heaviest]
    origins = np.asarray([
        (bone.bind_matrix[12], bone.bind_matrix[13], bone.bind_matrix[14])
        if len(bone.bind_matrix) == 16 else (0.0, 0.0, 0.0)
        for bone in skeleton.bones
    ], dtype=np.float64)
    return float(np.median(np.linalg.norm(mesh.rest[:, :3] - origins[bone_index], axis=1)))


def to_vec3_list(points: np.ndarray) -> List[Vec3]:
    return [Vec3(float(x), float(y), float(z)) for x, y, z in points]
