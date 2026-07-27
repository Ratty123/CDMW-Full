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
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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

        return Mesh(
            name=name or self.name,
            vertices=tuple(transform_point(vertex, matrix) for vertex in self.vertices),
            triangles=self.triangles,
            source_path=self.source_path,
        )


def load_mesh(data: bytes, name: str = "", *, source_path: str = "") -> Mesh:
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
        parsed = parse_mesh(data, filename)
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


def points_inside(points: Sequence[Vec3], mesh: Mesh) -> List[int]:
    """Indices of points enclosed by `mesh`, by odd/even +X ray crossings.

    Watertight-surface assumption: game armour meshes are closed enough for this to be a
    reliable *indicator*, which is what a clipping check needs. It is deliberately not sold as
    exact — the count is reported, not thresholded into a pass/fail by itself.
    """

    if mesh.empty or not mesh.triangles or not points:
        return []
    low, high = mesh.bounds()
    vertices = mesh.vertices

    # Testing every triangle for every point is O(points x triangles) and does not scale: a
    # 16,232-triangle body proxy against a 353-vertex sword is 5.7M ray/triangle tests, which
    # froze the UI for 13 seconds on a character switch. The ray is nearly +X, so a triangle
    # can only be crossed if its Y and Z spans bracket the ray — bucketing by Y turns the inner
    # loop into a small candidate list.
    span = high.y - low.y
    buckets = max(1, min(64, int(len(mesh.triangles) ** 0.5)))
    height = (span / buckets) if span > 1e-9 else 1.0
    by_row: List[List[Tuple[int, int, int, float, float]]] = [[] for _ in range(buckets)]
    for a, b, c in mesh.triangles:
        va, vb, vc = vertices[a], vertices[b], vertices[c]
        y0, y1 = min(va.y, vb.y, vc.y), max(va.y, vb.y, vc.y)
        z0, z1 = min(va.z, vb.z, vc.z), max(va.z, vb.z, vc.z)
        first = max(0, min(buckets - 1, int((y0 - low.y) / height)))
        last = max(0, min(buckets - 1, int((y1 - low.y) / height)))
        for row in range(first, last + 1):
            by_row[row].append((a, b, c, z0, z1))

    # The ray is skew, not axis-aligned, so it drifts in BOTH Y and Z as it crosses the mesh.
    # Ignoring the Y drift silently dropped triangles one bucket away, flipping the parity and
    # reporting 30 vertices inside where brute force found 27. Both margins are needed.
    reach = max(1e-6, high.x - low.x)
    z_margin = abs(_RAY[2] / _RAY[0]) * reach + 1e-4
    y_margin = abs(_RAY[1] / _RAY[0]) * reach + 1e-4
    row_span = int(y_margin / height) + 1

    inside: List[int] = []
    for index, point in enumerate(points):
        if not (
            low.x <= point.x <= high.x
            and low.y <= point.y <= high.y
            and low.z <= point.z <= high.z
        ):
            continue
        centre_row = int((point.y - low.y) / height)
        crossings = 0
        seen: set = set()
        for row in range(centre_row - row_span, centre_row + row_span + 1):
            if row < 0 or row >= buckets:
                continue
            for triangle in by_row[row]:
                a, b, c, z0, z1 = triangle
                if z1 < point.z - z_margin or z0 > point.z + z_margin:
                    continue
                key = (a, b, c)
                if key in seen:
                    continue  # a triangle spanning several rows must count once
                seen.add(key)
                if _ray_hits_triangle(point, vertices[a], vertices[b], vertices[c]):
                    crossings += 1
        if crossings % 2 == 1:
            inside.append(index)
    return inside


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


def measure_clipping(placed_weapon: Mesh, body: Mesh) -> ClippingReport:
    """Count weapon vertices inside the body and how far in the worst one sits."""

    if placed_weapon.empty or body.empty:
        return ClippingReport(weapon=placed_weapon.name, body=body.name)

    overlap = _bounds_overlap(placed_weapon.bounds(), body.bounds())
    if not overlap:
        return ClippingReport(
            weapon=placed_weapon.name,
            body=body.name,
            weapon_vertices=placed_weapon.vertex_count,
            bounds_overlap=False,
        )

    inside = points_inside(placed_weapon.vertices, body)
    deepest, deepest_point = 0.0, None
    for index in inside:
        point = placed_weapon.vertices[index]
        # Distance to the nearest body vertex is a cheap, monotone stand-in for depth.
        nearest = min(point.distance_to(vertex) for vertex in body.vertices)
        if nearest > deepest:
            deepest, deepest_point = nearest, point

    return ClippingReport(
        weapon=placed_weapon.name,
        body=body.name,
        weapon_vertices=placed_weapon.vertex_count,
        inside_count=len(inside),
        bounds_overlap=True,
        deepest=deepest,
        deepest_point=deepest_point,
    )


# ── archive discovery ────────────────────────────────────────────────


def weapon_mesh_path(weapon_id: str, model: str) -> str:
    """`cd_phm_01_sword_0001_r` -> its `.pac` under `character/model/...`.

    Socket files carry side and case suffixes (`_r`, `_in`) that the mesh does not, so those
    are stripped rather than guessed at.
    """

    stem = weapon_id
    for suffix in ("_in", "_r", "_l"):
        while stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    category = "2_twohandweapon" if "_02_" in stem else "1_onehandweapon"
    return f"character/model/1_pc/{model}/weapon/{category}/{stem}.pac"


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
