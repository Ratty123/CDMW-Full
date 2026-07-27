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

**Only the primary influence is usable, and the slot table is derived, not read.**

`mesh_parser` documents that a PAC vertex's four influence slots are not four bone indices:
only slot 0 decodes, and bytes 21-23 are a packed field. Reading all four is what made the
index space look 253 wide with nonsense bones attached — the primary slot alone tops out at
74 on the body meshes, and every value lands on an anatomically sensible bone.

The slot table itself is not in these files. The parser's note says a PAC holds a palette of
`.pab` bone-name hashes near the start; that is not true of the 1_pc body meshes, where a
scan finds *zero* aligned `.pab` hashes anywhere. `SubMesh.source_bone_palette` is a
four-entry `(0, 1, 2, 3)` influence-slot descriptor, not a bone table.

So the mapping is recovered from geometry instead: cluster the vertices a slot drives, and
match that cluster to the bone whose bind position it sits on. That is checkable rather than
assumed — `dominant_bone_drift` reports 0.046 m and 0.059 m on the two body meshes, against
0.46 m for every ordering that was wrong. `MAX_DRIFT` refuses anything worse, so a mesh this
heuristic cannot place is skipped rather than deformed into a guess.

Worth stating plainly: with one influence per vertex the skin is **rigid**, not smoothly
blended. Joints crease where a real four-bone blend would round. The body follows the
animation, which is the point; it will not match the game's own deformation.
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
    base = 0
    for submesh in parsed.submeshes:
        if not submesh.vertices or not submesh.faces:
            continue
        count = len(submesh.vertices)
        for index in range(count):
            x, y, z = submesh.vertices[index]
            rest.append((x, y, z, 1.0))
            slots = submesh.bone_indices[index] if index < len(submesh.bone_indices) else ()
            # Primary influence only: slots 1-3 are a packed field, not bone indices.
            primary.append(int(slots[0]) if slots else 0)
        for a, b, c in submesh.faces:
            faces.append((a + base, b + base, c + base))
        base += count

    if not rest or not faces:
        return None
    rest_array = np.asarray(rest, dtype=np.float64)
    mapping = derive_bone_map(rest_array[:, :3], primary, skeleton)
    column = np.asarray([mapping.get(slot, 0) for slot in primary], dtype=np.int32)
    mesh = SkinnedMesh(
        name=name,
        rest=rest_array,
        faces=np.asarray(faces, dtype=np.int32),
        bones=np.repeat(column[:, None], 4, axis=1),
        weights=np.tile(np.asarray([1.0, 0.0, 0.0, 0.0]), (len(primary), 1)),
        source_path=path,
    )
    if dominant_bone_drift(mesh, skeleton) > MAX_DRIFT:
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
