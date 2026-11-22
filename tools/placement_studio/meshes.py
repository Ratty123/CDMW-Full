"""Mesh loading and clipping measurement.

The plan called for driving the resident D3D11 preview to see weapon and body together. That
turned out to be unnecessary: `cdmw.modding.mesh_parser` decodes `.pac` geometry **in process**,
and the vertices arrive in bind/model space already. So this module parses meshes directly and
the viewport draws them itself — no second process, and therefore none of the documented
embedded-preview freeze risk. See §5.8.

More importantly, it turns "judge the clipping by eye" into a number. A ray-cast inside test
counts how many weapon vertices are actually *inside* the body surface, so a bad placement is
reported rather than argued about. The render then confirms the number instead of being the only
evidence.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from threading import Lock
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .model import Vec3
from .skeleton import Matrix, transform_point

Triangle = Tuple[int, int, int]


class MeshError(RuntimeError):
    """Raised when geometry cannot be decoded or measured."""


@dataclass(frozen=True, slots=True)
class Mesh:
    """Decoded geometry in a single space, with its triangles."""

    name: str
    vertices: tuple[Vec3, ...] = field(default=())
    triangles: tuple[Triangle, ...] = field(default=())
    source_path: str = ""

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def empty(self) -> bool:
        return not self.vertices

    def bounds(self) -> Tuple[Vec3, Vec3]:
        if not self.vertices:
            return (Vec3(), Vec3())
        xs = [v.x for v in self.vertices]
        ys = [v.y for v in self.vertices]
        zs = [v.z for v in self.vertices]
        return (Vec3(min(xs), min(ys), min(zs)), Vec3(max(xs), max(ys), max(zs)))

    def centre(self) -> Vec3:
        low, high = self.bounds()
        return Vec3((low.x + high.x) / 2, (low.y + high.y) / 2, (low.z + high.z) / 2)

    def transformed(self, matrix: Matrix, *, name: str = "") -> "Mesh":
        """Place the mesh in another space — how a weapon reaches its attachment point."""

        if not self.vertices:
            return Mesh(
                name=name or self.name,
                vertices=(),
                triangles=self.triangles,
                source_path=self.source_path,
            )
        pts = _vertices_array(self)
        mat = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
        moved = pts @ mat[:3, :3] + mat[3, :3]
        return Mesh(
            name=name or self.name,
            vertices=tuple(Vec3(x, y, z) for x, y, z in moved.tolist()),
            triangles=self.triangles,
            source_path=self.source_path,
        )


def load_mesh(data: bytes, name: str = "", *, source_path: str = "", parsed_mesh=None) -> Mesh:
    """Decode a `.pac`/`.pam` payload into one merged mesh.

    Submeshes are merged with re-based indices: for clipping and silhouette purposes the
    material split carries no information.
    """

    from cdmw.modding.mesh_parser import parse_mesh

    # The parser selects the format (PAM / PAMLOD / PAC) from the *filename*, and returns an
    # empty mesh when it cannot. Silently empty geometry reads as "this weapon has no model",
    # so refuse instead of guessing.
    filename = name or PurePosixPath(source_path).name
    if not filename:
        raise MeshError("A filename is required to decode geometry (the parser needs the suffix)")

    try:
        parsed = parse_mesh(data, filename) if parsed_mesh is None else parsed_mesh
    except Exception as exc:  # noqa: BLE001 - report, never guess at geometry
        raise MeshError(f"{filename}: {exc}") from exc
    if not (getattr(parsed, "submeshes", None) or ()):
        raise MeshError(f"{filename}: no submeshes decoded")

    vertices: List[Vec3] = []
    triangles: List[Triangle] = []
    for submesh in getattr(parsed, "submeshes", None) or ():
        base = len(vertices)
        for vertex in getattr(submesh, "vertices", None) or ():
            try:
                vertices.append(Vec3(float(vertex[0]), float(vertex[1]), float(vertex[2])))
            except (TypeError, IndexError, ValueError):
                continue
        for face in getattr(submesh, "faces", None) or ():
            try:
                a, b, c = int(face[0]) + base, int(face[1]) + base, int(face[2]) + base
            except (TypeError, IndexError, ValueError):
                continue
            if max(a, b, c) < len(vertices) and len({a, b, c}) == 3:
                triangles.append((a, b, c))

    return Mesh(
        name=name or PurePosixPath(source_path).name,
        vertices=tuple(vertices),
        triangles=tuple(triangles),
        source_path=source_path,
    )


def merge(meshes: Iterable[Mesh], *, name: str = "merged") -> Mesh:
    vertices: List[Vec3] = []
    triangles: List[Triangle] = []
    for mesh in meshes:
        base = len(vertices)
        vertices.extend(mesh.vertices)
        triangles.extend((a + base, b + base, c + base) for a, b, c in mesh.triangles)
    return Mesh(name=name, vertices=tuple(vertices), triangles=tuple(triangles))


# ── clipping measurement ─────────────────────────────────────────────


def _bounds_overlap(a: Tuple[Vec3, Vec3], b: Tuple[Vec3, Vec3]) -> bool:
    (a_low, a_high), (b_low, b_high) = a, b
    return (
        a_low.x <= b_high.x and b_low.x <= a_high.x
        and a_low.y <= b_high.y and b_low.y <= a_high.y
        and a_low.z <= b_high.z and b_low.z <= a_high.z
    )


# A deliberately skew ray direction. An axis-aligned ray lands exactly on shared triangle
# edges whenever the geometry is axis-aligned — which game meshes and test cubes both are — and
# an edge hit is counted by *both* adjoining triangles, flipping the parity and reporting an
# interior point as outside. Casting slightly off-axis makes that coincidence vanishingly rare.
_RAY_LENGTH = math.sqrt(1.0 + 0.0179 ** 2 + 0.0431 ** 2)
_RAY = (1.0 / _RAY_LENGTH, 0.0179 / _RAY_LENGTH, 0.0431 / _RAY_LENGTH)


def _ray_hits_triangle(origin: Vec3, a: Vec3, b: Vec3, c: Vec3) -> bool:
    """Does the ray from `origin` along `_RAY` cross this triangle? (Moller-Trumbore.)"""

    e1 = (b.x - a.x, b.y - a.y, b.z - a.z)
    e2 = (c.x - a.x, c.y - a.y, c.z - a.z)
    d = _RAY
    h = (
        d[1] * e2[2] - d[2] * e2[1],
        d[2] * e2[0] - d[0] * e2[2],
        d[0] * e2[1] - d[1] * e2[0],
    )
    determinant = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
    if abs(determinant) < 1e-12:
        return False
    inv = 1.0 / determinant
    s = (origin.x - a.x, origin.y - a.y, origin.z - a.z)
    u = inv * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
    if u < 0.0 or u > 1.0:
        return False
    q = (
        s[1] * e1[2] - s[2] * e1[1],
        s[2] * e1[0] - s[0] * e1[2],
        s[0] * e1[1] - s[1] * e1[0],
    )
    v = inv * (d[0] * q[0] + d[1] * q[1] + d[2] * q[2])
    if v < 0.0 or u + v > 1.0:
        return False
    t = inv * (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2])
    return t > 1e-9


_VERTEX_CACHE_LOCK = Lock()
_VERTEX_ARRAYS: OrderedDict[int, tuple] = OrderedDict()
_TRI_ARRAYS: OrderedDict[tuple[int, int], tuple] = OrderedDict()


def _vertices_array(mesh) -> np.ndarray:
    points = getattr(mesh, "_points", None)
    if points is not None:
        arr = np.asarray(points, dtype=np.float64)
        return arr.reshape(-1, 3) if len(arr) else np.empty((0, 3), dtype=np.float64)
    if hasattr(mesh, "points") and not isinstance(mesh, Mesh):
        arr = np.asarray(mesh.points, dtype=np.float64)
        return arr.reshape(-1, 3) if len(arr) else np.empty((0, 3), dtype=np.float64)
    vertices = mesh.vertices
    if not vertices:
        return np.empty((0, 3), dtype=np.float64)
    key = id(vertices)
    with _VERTEX_CACHE_LOCK:
        hit = _VERTEX_ARRAYS.get(key)
        if hit is not None and hit[0] is vertices:
            _VERTEX_ARRAYS.move_to_end(key)
            return hit[1]
    arr = np.asarray([(v.x, v.y, v.z) for v in vertices], dtype=np.float64)
    arr.setflags(write=False)
    with _VERTEX_CACHE_LOCK:
        _VERTEX_ARRAYS[key] = (vertices, arr)
        _VERTEX_ARRAYS.move_to_end(key)
        while len(_VERTEX_ARRAYS) > 32:
            _VERTEX_ARRAYS.popitem(last=False)
    return arr


def _triangle_ray_data(mesh) -> Optional[tuple]:
    triangles = getattr(mesh, "triangles", ())
    if not triangles:
        return None
    use_cache = isinstance(mesh, Mesh) and isinstance(triangles, tuple)
    verts_ref = mesh.vertices if use_cache else None
    key = (id(verts_ref), id(triangles))
    if use_cache:
        with _VERTEX_CACHE_LOCK:
            hit = _TRI_ARRAYS.get(key)
            if hit is not None and hit[0] is verts_ref and hit[1] is triangles:
                _TRI_ARRAYS.move_to_end(key)
                return hit[2]
    verts = _vertices_array(mesh)
    if not len(verts):
        return None
    tris = np.asarray(triangles, dtype=np.int64)
    A = verts[tris[:, 0]]
    B = verts[tris[:, 1]]
    C = verts[tris[:, 2]]
    E1 = B - A
    E2 = C - A
    ray = np.asarray(_RAY, dtype=np.float64)
    H = np.cross(ray, E2)
    det = np.einsum("ij,ij->i", E1, H)
    valid = np.abs(det) >= 1e-12
    if not np.any(valid):
        return None
    A = A[valid]
    B = B[valid]
    C = C[valid]
    E1 = E1[valid]
    E2 = E2[valid]
    H = H[valid]
    inv = 1.0 / det[valid]
    x_max = np.maximum(A[:, 0], np.maximum(B[:, 0], C[:, 0]))
    y0 = np.minimum(A[:, 1], np.minimum(B[:, 1], C[:, 1]))
    y1 = np.maximum(A[:, 1], np.maximum(B[:, 1], C[:, 1]))
    z0 = np.minimum(A[:, 2], np.minimum(B[:, 2], C[:, 2]))
    z1 = np.maximum(A[:, 2], np.maximum(B[:, 2], C[:, 2]))
    data = (A, E1, E2, H, inv, x_max, y0, y1, z0, z1)
    if use_cache:
        with _VERTEX_CACHE_LOCK:
            _TRI_ARRAYS[key] = (verts_ref, triangles, data)
            _TRI_ARRAYS.move_to_end(key)
            while len(_TRI_ARRAYS) > 16:
                _TRI_ARRAYS.popitem(last=False)
    return data


def points_inside(points: Sequence[Vec3], mesh: Mesh) -> List[int]:
    """Indices of points enclosed by `mesh`, by odd/even +X ray crossings.

    Watertight-surface assumption: game armour meshes are closed enough for this to be a
    reliable *indicator*, which is what a clipping check needs. It is deliberately not sold as
    exact — the count is reported, not thresholded into a pass/fail by itself.
    """

    if mesh.empty or not mesh.triangles or len(points) == 0:
        return []
    low, high = mesh.bounds()
    if isinstance(points, np.ndarray):
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    else:
        pts = np.asarray([(p.x, p.y, p.z) for p in points], dtype=np.float64)
    if not len(pts):
        return []

    cand_mask = (
        (pts[:, 0] >= low.x) & (pts[:, 0] <= high.x)
        & (pts[:, 1] >= low.y) & (pts[:, 1] <= high.y)
        & (pts[:, 2] >= low.z) & (pts[:, 2] <= high.z)
    )
    cand_idx = np.flatnonzero(cand_mask)
    if not len(cand_idx):
        return []

    tri_data = _triangle_ray_data(mesh)
    if tri_data is None:
        return []
    A, E1, E2, H, inv, tri_xmax, tri_y0, tri_y1, tri_z0, tri_z1 = tri_data
    ray = np.asarray(_RAY, dtype=np.float64)
    reach = max(1e-6, high.x - low.x)
    z_margin = abs(_RAY[2] / _RAY[0]) * reach + 1e-4
    y_margin = abs(_RAY[1] / _RAY[0]) * reach + 1e-4

    cand_pts = pts[cand_idx]
    inside_all: List[int] = []
    for p0 in range(0, len(cand_pts), 64):
        pts_b = cand_pts[p0 : p0 + 64]
        crossings = np.zeros(len(pts_b), dtype=np.int32)
        bx_min = float(np.min(pts_b[:, 0])) - 1e-9
        by_min = float(np.min(pts_b[:, 1])) - y_margin
        by_max = float(np.max(pts_b[:, 1])) + y_margin
        bz_min = float(np.min(pts_b[:, 2])) - z_margin
        bz_max = float(np.max(pts_b[:, 2])) + z_margin
        t_cand = np.flatnonzero(
            (tri_xmax >= bx_min)
            & (tri_y1 >= by_min) & (tri_y0 <= by_max)
            & (tri_z1 >= bz_min) & (tri_z0 <= bz_max)
        )
        for t0 in range(0, len(t_cand), 4096):
            sel = t_cand[t0 : t0 + 4096]
            Ab = A[sel]
            Hb = H[sel]
            invb = inv[sel]
            u = invb[None, :] * (
                (pts_b[:, 0:1] - Ab[:, 0]) * Hb[:, 0]
                + (pts_b[:, 1:2] - Ab[:, 1]) * Hb[:, 1]
                + (pts_b[:, 2:3] - Ab[:, 2]) * Hb[:, 2]
            )
            pi, ti = np.nonzero((u >= 0.0) & (u <= 1.0))
            if not len(pi):
                continue
            orig_ti = sel[ti]
            s = pts_b[pi] - A[orig_ti]
            q = np.cross(s, E1[orig_ti])
            v = inv[orig_ti] * (q @ ray)
            keep = (v >= 0.0) & (u[pi, ti] + v <= 1.0)
            if not np.any(keep):
                continue
            keep_ti = orig_ti[keep]
            t_vals = inv[keep_ti] * np.einsum("ij,ij->i", E2[keep_ti], q[keep])
            hits = pi[keep][t_vals > 1e-9]
            if len(hits):
                crossings += np.bincount(hits, minlength=len(pts_b))
        for local_i in np.flatnonzero(crossings & 1).tolist():
            inside_all.append(int(cand_idx[p0 + local_i]))
    return inside_all


@dataclass(frozen=True, slots=True)
class ClippingReport:
    """How badly a placed weapon intersects the body."""

    weapon: str = ""
    body: str = ""
    weapon_vertices: int = 0
    inside_count: int = 0
    bounds_overlap: bool = False
    deepest: float = 0.0
    deepest_point: Optional[Vec3] = None

    @property
    def clipping(self) -> bool:
        return self.inside_count > 0

    @property
    def ratio(self) -> float:
        return self.inside_count / self.weapon_vertices if self.weapon_vertices else 0.0

    def summary(self) -> str:
        """One line a modder can act on: does the item sit on the body, or in it?

        Worded as a verdict rather than a measurement. "12/840 vertices inside, deepest
        0.0043" is precise and tells you nothing about whether to move the thing.
        """

        if not self.bounds_overlap:
            return "sits clear of the body"
        if not self.clipping:
            return "touching the body, but nothing sunk in"
        return (
            f"sunk {self.deepest * 100:.1f} cm into the body "
            f"({self.ratio * 100:.1f}% of the item) — nudge it outward"
        )


def measure_clipping_with_indices(placed_weapon: Mesh, body: Mesh) -> Tuple[ClippingReport, List[int]]:
    """Count weapon vertices inside the body, depth, and the inside vertex indices."""

    if placed_weapon.empty or body.empty:
        return ClippingReport(weapon=placed_weapon.name, body=body.name), []

    overlap = _bounds_overlap(placed_weapon.bounds(), body.bounds())
    if not overlap:
        return (
            ClippingReport(
                weapon=placed_weapon.name,
                body=body.name,
                weapon_vertices=placed_weapon.vertex_count,
                bounds_overlap=False,
            ),
            [],
        )

    weapon_pts = _vertices_array(placed_weapon)
    inside = points_inside(weapon_pts, body)
    deepest, deepest_point = 0.0, None
    if inside:
        in_pts = weapon_pts[inside]
        body_pts = _vertices_array(body)
        if len(body_pts):
            best_d2 = np.full(len(in_pts), np.inf, dtype=np.float64)
            bx, by, bz = body_pts[:, 0], body_pts[:, 1], body_pts[:, 2]
            for start in range(0, len(in_pts), 128):
                chunk = in_pts[start : start + 128]
                min_chunk = best_d2[start : start + 128]
                cx, cy, cz = chunk[:, 0:1], chunk[:, 1:2], chunk[:, 2:3]
                for b0 in range(0, len(body_pts), 4096):
                    b1 = b0 + 4096
                    dx = cx - bx[b0:b1]
                    dy = cy - by[b0:b1]
                    dz = cz - bz[b0:b1]
                    d2 = dx * dx + dy * dy + dz * dz
                    min_chunk = np.minimum(min_chunk, np.min(d2, axis=1))
                best_d2[start : start + 128] = min_chunk
            dists = np.sqrt(best_d2)
            max_i = int(np.argmax(dists))
            deepest = float(dists[max_i])
            deepest_point = placed_weapon.vertices[inside[max_i]]

    return (
        ClippingReport(
            weapon=placed_weapon.name,
            body=body.name,
            weapon_vertices=placed_weapon.vertex_count,
            inside_count=len(inside),
            bounds_overlap=True,
            deepest=deepest,
            deepest_point=deepest_point,
        ),
        inside,
    )


def measure_clipping(placed_weapon: Mesh, body: Mesh) -> ClippingReport:
    """Count weapon vertices inside the body and how far in the worst one sits."""

    report, _inside = measure_clipping_with_indices(placed_weapon, body)
    return report


# ── archive discovery ────────────────────────────────────────────────


def weapon_mesh_path(weapon_id: str, model: str) -> str:
    """`cd_phm_01_sword_0001_r` -> its `.pac` under `character/model/...`.

    Socket files carry side and case suffixes (`_r`, `_in`) that the mesh does not, so those
    are stripped rather than guessed at.
    """

    return weapon_mesh_paths(weapon_id, model)[0]


def weapon_mesh_paths(weapon_id: str, model: str) -> list:
    """Every path a weapon's mesh might be at, likeliest first.

    The side and case suffixes are usually the socket file's alone — `cd_phm_01_sword_0001_r`
    is drawn by `cd_phm_01_sword_0001.pac`. Usually, not always: a fist weapon ships as
    `cd_phm_13_cannon_0003_l.pac` and `..._r.pac`, two different meshes for the two hands. So
    the name is tried as it stands as well as stripped, and the caller takes the one that is
    actually in the archives.
    """

    stem = weapon_id
    for suffix in ("_in", "_r", "_l"):
        while stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    folder = weapon_folder(stem)
    root = f"character/model/1_pc/{model}/weapon"
    seen = []
    for candidate in (stem, weapon_id):
        path = f"{root}/{folder}/{candidate}.pac"
        if path not in seen:
            seen.append(path)
    return seen


#: The number in a weapon's name is the folder its mesh lives in. `cd_phm_04_arw_0001` is in
#: `4_bow`, not in `1_onehandweapon`.
#:
#: This used to be read as one bit — two-hand if the name contained `_02_`, one-hand otherwise —
#: which sent every bow, shield, musket and torch to a path that does not exist. They loaded as
#: weapons because their socket file is real, then drew nothing at all when selected.
WEAPON_FOLDERS: Dict[str, str] = {
    "00": "0_tools",
    "01": "1_onehandweapon",
    "02": "2_twohandweapon",
    "03": "3_shield",
    "04": "4_bow",
    "05": "5_crossbow",
    "06": "6_pistol",
    "07": "7_shotgun",
    "08": "8_musket",
    "10": "10_thrownweapon",
    "12": "12_pike",
    "11": "11_trap",
    "13": "13_fist",
}


def weapon_folder(stem: str) -> str:
    """Which `weapon/` folder a stem belongs to, from the number it carries.

    An unrecognised number falls back to one-hand, which is what the whole function used to
    assume: no worse than before for anything it cannot place.
    """

    parts = stem.split("_")
    if len(parts) > 2 and parts[2].isdigit():
        folder = WEAPON_FOLDERS.get(parts[2])
        if folder:
            return folder
    return "2_twohandweapon" if "_02_" in stem else "1_onehandweapon"


BODY_SLOTS: Tuple[str, ...] = ("9_upperbody", "10_lowerbody")

# The token a slot's meshes carry in their filename, for matching base-armour names.
BODY_SLOT_TAGS: Dict[str, str] = {"9_upperbody": "ub", "10_lowerbody": "lb"}

# `cd_phm_00_ub_0001.pac` — a base armour piece for one slot. Deliberately strict: it excludes
# `_acc` accessories, `_sub01` sub-pieces, `_belt`, and character variants like
# `cd_phm_m0001_00_artis_ub_0001`, none of which cover a body.
def is_base_armour_mesh(path: str, model: str, slot: str) -> bool:
    tag = BODY_SLOT_TAGS.get(slot, "")
    if not tag:
        return False
    stem_model = model.split("_", 1)[-1]
    name = path.rsplit("/", 1)[-1].lower()
    return bool(re.fullmatch(rf"cd_{re.escape(stem_model)}_00_{tag}_\d{{4}}\.pac", name))


def body_coverage(mesh, hierarchy) -> float:
    """How much of the rig's height the proxy spans, 0..1.

    The check that would have caught the accessory proxy: a 23 KB scrap spans 0.23 of a 1.79
    tall rig, so anything near the body is trivially "not clipping". Cheap enough to run on
    every load, and the only honest way to know a proxy is a body rather than a buckle.
    """

    if mesh is None or not getattr(mesh, "vertices", ()) or hierarchy is None or not len(hierarchy):
        return 0.0
    heights = [bone.world_position.y for bone in hierarchy]
    rig = max(heights) - min(heights)
    if rig <= 1e-6:
        return 0.0
    low, high = mesh.bounds()
    return max(0.0, min(1.0, (high.y - low.y) / rig))


# Below this fraction of the rig's height the proxy is a fragment, not a body, and every
# clipping number taken against it is meaningless.
MIN_BODY_COVERAGE = 0.45


def body_mesh_paths(baseline, model: str) -> List[str]:
    """Body proxy meshes present in the baseline, for the chosen model."""

    return sorted(
        path
        for path in baseline.paths()
        if path.endswith(".pac")
        and f"/{model}/armor/" in path
        and any(f"/{slot}/" in path for slot in BODY_SLOTS)
    )
