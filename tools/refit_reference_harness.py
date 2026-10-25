"""Headless Morph & Refit harness for Fit to body on real PACs.

Fits an outfit onto a driver body in one resident native session, either with
the body the outfit was authored on (``morph_set_reference_body``, the
``reference`` method) or with the driver alone (``morph_configure_refit``, the
``bound`` method), and scores each result:

- worst rigid distortion: Kabsch residual of every island the config marks rigid;
- new inside-body vertices: garment vertices more than 0.5 mm inside the driver
  that were not already inside the authored body (beside an open rim, such as a
  head's cut-out face, nothing counts as inside);
- new skin through cloth: driver vertices in front of the garment face closest
  to them, facing the same way, within 30 mm and not beside an open hem, where
  the garment point beneath is inside the body (a breast or knee through a
  coarse triangle whose corners are all clear of it) but was not inside the
  authored body as authored. Many outfits come with their own body through
  them, presumably hidden in game; all such vertices and the count for the
  authored body under the outfit as loaded are reported beside it;
- new layer crossings: triangle pairs between garment islands that intersect
  after the fit but not before (python-fcl);
- cloth edge strain: ``|length / authored length - 1|`` over flexible islands,
  and over the islands the config names as ``tails``;
- solid-piece distortion: the same Kabsch residual for every small closed piece
  the body does not pass through (blades, buckles, plates), marked or not.

Crossings are also split into rigid-against-cloth and cloth-against-cloth, where
an island counts as rigid if the fit moved it without changing its shape.

``--poses`` (archive mode) also skins the fitted outfit and the driver through a
few limb and torso rotations, the outfit with its own weights and its bones
matched to the driver's skeleton by name, and scores what motion adds beside the
outfit posed the same way on its authored body (``tools/refit_reference_poses.py``).
Fit to body changes positions only, so this is where weights show.

``--corpus`` fits every outfit in a list (``tools/refit_reference_corpus.json``:
11002 plus two outfits per PHM, PHW and monster-PHM slot, picked by path hash)
onto one driver from a fresh, unmarked setup and tabulates both methods. Judge a
fitting change on the whole corpus, not on one outfit.

Inputs are decoded files, or archive paths read from a game install. Archive
mode is read only; it finds the reference body exactly as the editor does
(:func:`cdmw.services.mesh_refit_reference_lookup.find_refit_reference_body`)
and shows each PAC in its character appearance first, as the editor does.

Part and island numbers in configs and reports are the outfit's own, as the
editor lists them, not offsets into the combined session.

Dev-only dependencies: trimesh, python-fcl, scipy, and Pillow for ``--render``.

Examples::

    python tools/refit_reference_harness.py --preset 11002 --assets <decoded folder> --output out
    python tools/refit_reference_harness.py --preset 11002 --game-root "<Crimson Desert>" --output out \\
        --method reference bound
    python tools/refit_reference_harness.py --game-root "<Crimson Desert>" --corpus tools/refit_reference_corpus.json \\
        --method bound reference --output out
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.domain.mesh.islands import mesh_islands  # noqa: E402
from cdmw.modding import mesh_native_core  # noqa: E402
from cdmw.modding.mesh_parser import ParsedMesh, parse_pac, resolve_pac_bone_palette  # noqa: E402
from cdmw.modding.mesh_refit_reference import RefitReferenceBody, retarget_reference_body  # noqa: E402
from cdmw.modding.skeleton_parser import parse_pab  # noqa: E402

INSIDE = 0.0005
SKIN_REACH = 0.03
SKIN_FACING = 0.5

# 11002 (PHM upper body) onto Damiane (PHW). Rigid islands are marked by hand:
# daggers, buckles, plates and rope knots. Tails are the hanging cloth strips.
PRESETS = {
    "11002": {
        "body": "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac",
        "outfit": "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_01_phm/armor_desert/9_upperbody/"
                  "cd_m0001_00_de_phm_ub_11002.pac",
        "reference": "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac",
        "source_skeleton": "phm_01.pab",
        "target_skeleton": "phw_01.pab",
        # Fit to body's defaults for a fresh setup; Tightness also enables the
        # automatic rigid accessory inference.
        "clearance": 0.1,
        "tightness": 100.0,
        "parts": {
            "0": {"rigid_islands": [1, 2, 3, 4, 5]},
            "1": {"mode": "rigid_component"},
            "3": {"mode": "rigid"},
            "5": {"rigid_islands": [0, 1, 2, 3, 6, 7, 8, 9, 10, 11]},
            "6": {"rigid_islands": [0, 1, 2]},
            "8": {"mode": "rigid_component"},
        },
        "tails": [[5, 4], [5, 5], [6, 3], [6, 4]],
    },
}


def _require_dev_dependencies(render: bool, archive: bool):
    missing = []
    # lz4 is an app requirement; archive PABs and PACs are mostly LZ4-compressed.
    for module in ("trimesh", "fcl", "scipy") + (("PIL",) if render else ()) + (("lz4",) if archive else ()):
        try:
            __import__(module)
        except ImportError:
            missing.append({"fcl": "python-fcl", "PIL": "Pillow"}.get(module, module))
    if missing:
        raise SystemExit(f"Install the harness's dev-only dependencies first: pip install {' '.join(missing)}")


# ------------------------------------------------------------------ inputs
def _combined(body: ParsedMesh, outfit: ParsedMesh) -> ParsedMesh:
    parts = [deepcopy(part) for part in (*body.submeshes, *outfit.submeshes)]
    return ParsedMesh(path="refit-harness.pac", format="pac", submeshes=parts,
                      total_vertices=sum(len(part.vertices) for part in parts),
                      total_faces=sum(len(part.faces) for part in parts))


def _file_inputs(config: dict, assets: Path) -> dict:
    def path(name):
        value = Path(config[name])
        return value if value.is_file() else assets / value.name
    read = {name: path(name).read_bytes() for name in ("body", "outfit", "reference", "source_skeleton", "target_skeleton")}
    source, target = (parse_pab(read[name], str(path(name))) for name in ("source_skeleton", "target_skeleton"))
    reference_mesh = parse_pac(read["reference"], path("reference").name)
    palette = resolve_pac_bone_palette(read["reference"], source)
    if not palette:
        raise SystemExit("The reference body's bones do not resolve against the source skeleton.")
    reference = retarget_reference_body(reference_mesh.submeshes, palette, source, target, label=config["reference"])
    return {"body": parse_pac(read["body"], path("body").name), "outfit": parse_pac(read["outfit"], path("outfit").name),
            "reference": reference, "provenance": {name: str(path(name)) for name in read}}


def _archive_index(game_root: Path):
    """The members of the editor's ArchiveWorkflowDependencyContext the lookup reads, without Qt."""
    from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _real_archive_all_pamt_entries

    entries, _pamts, errors = _real_archive_all_pamt_entries(game_root)
    if not entries:
        raise SystemExit(f"No archive entries under {game_root}: {errors[:1]}")
    by_path, by_basename = _archive_entry_indexes(entries)
    return SimpleNamespace(
        entries_by_normalized_path=by_path, entries_by_basename=by_basename,
        entry_for_path=lambda path: next(iter(by_path.get(_archive_key(path), ())), None),
    )


def _archive_inputs(config: dict, dependencies) -> dict:
    """Load both PACs as the editor's archive Refit does and ask its lookup for the reference.

    ``reference`` is None, with the lookup's ``reason``, when Fit would use the driver alone.
    """
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_mesh_appearance import UnresolvedPacBonePaletteError, apply_archive_mesh_appearance
    from cdmw.services.mesh_archive_refit import ArchiveRefitAsset, ArchiveRefitContext
    from cdmw.services.mesh_refit_reference_lookup import find_refit_reference_body

    by_path, by_basename = dependencies.entries_by_normalized_path, dependencies.entries_by_basename
    assets, meshes, appearances, offset = [], {}, {}, 0
    for role, name in (("body", "body"), ("loaded", "outfit")):
        entry = dependencies.entry_for_path(config[name])
        if entry is None:
            raise ValueError(f"{config[name]} is not in the game archive.")
        data = read_archive_entry_data(entry)[0]
        mesh = parse_pac(data, entry.path)
        try:
            shown, _notes = apply_archive_mesh_appearance(
                entry, mesh, data, archive_entries_by_normalized_path=by_path, archive_entries_by_basename=by_basename)
        except UnresolvedPacBonePaletteError:
            shown = mesh
        appearance = getattr(shown, "_cdmw_neutral_appearance", None)
        meshes[name], appearances[name] = (shown if appearance is not None else mesh), appearance
        indices = tuple(range(offset, offset + len(mesh.submeshes)))
        offset += len(mesh.submeshes)
        assets.append(ArchiveRefitAsset(entry, SimpleNamespace(original_data=data), indices, role,
                                        SimpleNamespace(archive_dependencies=dependencies), neutral_appearance=appearance))
    body_count = len(meshes["body"].submeshes)
    lookup = find_refit_reference_body(ArchiveRefitContext(tuple(assets)),
                                       tuple(range(body_count, offset)), tuple(range(body_count)))
    reference = lookup.reference
    return {"body": meshes["body"], "outfit": meshes["outfit"], "reference": reference, "reason": lookup.reason,
            "provenance": {"body": config["body"], "outfit": config["outfit"],
                           "reference": reference.label if reference is not None else None,
                           "appearances": {name: getattr(value, "source", None) for name, value in appearances.items()},
                           "substituted_bones": list(reference.substituted_bones) if reference is not None else []}}


def _rig(config: dict, dependencies, inputs: dict) -> dict:
    """Skeletons and bone palettes that pose the body and outfit as the game skins them (``--poses``).

    The outfit's bones follow the driver's skeleton by name (nearest shared
    ancestor), as in the reference retarget. The authored pairing poses the
    reference body and the outfit as loaded with the outfit's own skeleton.
    """
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.modding.mesh_refit_reference import retarget_transforms
    from cdmw.services.mesh_refit_reference_lookup import _skeleton

    reference = inputs["reference"]
    if reference is None:
        raise ValueError(f"posing needs the authored body: {inputs['reason']}")
    if any(inputs["provenance"]["appearances"].values()):
        raise ValueError("posing does not yet place joints for character appearances")

    def read(entry):
        return read_archive_entry_data(entry)[0]

    data, skeletons = {}, {}
    for name in ("body", "outfit"):
        entry = dependencies.entry_for_path(config[name])
        data[name] = read(entry)
        resolved = _skeleton(SimpleNamespace(entry=entry, source=SimpleNamespace(original_data=data[name])), dependencies, read)
        skeleton = getattr(resolved, "skeleton", None)
        if skeleton is None:  # the lookup's reason why not
            raise ValueError(str(resolved))
        skeletons[name] = skeleton
    nude = read(dependencies.entry_for_path(reference.label))
    outfit_slots = resolve_pac_bone_palette(data["outfit"], skeletons["outfit"])
    return {"driver": skeletons["body"], "authored": skeletons["outfit"],
            "body_slots": resolve_pac_bone_palette(data["body"], skeletons["body"]),
            "outfit_driver_slots": retarget_transforms(outfit_slots, skeletons["outfit"], skeletons["body"])[1],
            "outfit_slots": outfit_slots,
            # The same Parts the reference body was built from, so weights line up with its positions.
            "nude_parts": [part for part in parse_pac(nude, reference.label).submeshes if len(part.vertices) and len(part.faces)],
            "nude_slots": resolve_pac_bone_palette(nude, skeletons["outfit"])}


# ------------------------------------------------------------------ fitting
def _command(session: str, name: str, payload: dict | None = None, timeout: float = 300.0) -> dict:
    report = mesh_native_core.native_mesh_editor_session_command(name, session, payload or {}, timeout_seconds=timeout)
    if report is None:
        from cdmw.modding.mesh_native_core import last_native_mesh_core_job_error
        raise RuntimeError(f"native {name} failed: {last_native_mesh_core_job_error()}")
    return report


def _islands(outfit: ParsedMesh) -> list[tuple[tuple[int, ...], ...]]:
    return [mesh_islands(part) for part in outfit.submeshes]


def _rigid(config: dict, part: int, count: int) -> set[int]:
    row = config.get("parts", {}).get(str(part), {})
    if row.get("mode") in {"rigid", "rigid_component"}:
        return set(range(count))
    return set(row.get("rigid_islands", ()))


def _settings(outfit: ParsedMesh, islands, body_count: int, config: dict) -> list[dict]:
    rows = []
    for part, groups in enumerate(islands):
        row_config = config.get("parts", {}).get(str(part), {})
        row = {"submesh_index": body_count + part, "mode": row_config.get("mode", config.get("default_mode", "surface")),
               "tightness_percent": float(row_config.get("tightness", config.get("tightness", 100.0))),
               "clearance_percent": float(row_config.get("clearance", config.get("clearance", 0.1))),
               "enabled": not row_config.get("skip", False)}
        if row_config.get("rigid_islands"):
            row["island_settings"] = [{"face_indices": list(groups[index]), "mode": "rigid_component",
                                       "tightness_percent": row["tightness_percent"],
                                       "clearance_percent": row["clearance_percent"]}
                                      for index in row_config["rigid_islands"]]
        rows.append(row)
    return rows


def fit(inputs: dict, config: dict, method: str) -> dict:
    body, outfit, reference = inputs["body"], inputs["outfit"], inputs["reference"]
    body_count = len(body.submeshes)
    mesh = _combined(body, outfit)
    islands = _islands(outfit)
    session = f"refit-harness-{uuid4().hex}"
    if mesh_native_core.open_native_mesh_editor_session(mesh, session, timeout_seconds=60.0) is None:
        raise RuntimeError("The native mesh core could not open the session.")
    try:
        _command(session, "morph_upload", {"profile": {"profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
                                                       "definitions": [], "fields": []}})
        _command(session, "morph_set_driver", {"submesh_indices": list(range(body_count))})
        garments = list(range(body_count, len(mesh.submeshes)))
        _command(session, "morph_bind", {"garment_submesh_indices": garments})
        payload = {"garment_submesh_indices": garments, "garment_settings": _settings(outfit, islands, body_count, config)}
        started = time.perf_counter()
        status, error = "ok", None
        try:
            if method == "reference":
                _command(session, "morph_set_reference_body", {**payload, "reference_body": reference.payload()})
            else:
                _command(session, "morph_configure_refit", payload)
        except RuntimeError as exc:
            status, error = "refused", str(exc)
        seconds = time.perf_counter() - started
        state = _command(session, "morph_state")["morph_state"]
        fitted = deepcopy(mesh)
        if not mesh_native_core.export_native_mesh_editor_session_to_mesh(fitted, session, timeout_seconds=60.0):
            raise RuntimeError("The native mesh core could not export the fitted session.")
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)
    reference_state = (state.get("refit") or {}).get("reference_body") or {}
    return {"method": method, "status": status, "error": error, "seconds": seconds, "mesh": mesh, "fitted": fitted,
            "body_count": body_count, "islands": islands, "last_fit": reference_state.get("last_fit")}


# ------------------------------------------------------------------ metrics
class _Surface:
    """A body surface with a well-defined inside where it is closed.

    Body PACs are open: the head part has the face cut out. A point whose
    closest feature is an open edge or corner has no side and counts as
    outside, as in the native fitter. Elsewhere the side comes from the face
    normal, the summed normals of an edge's faces, or a corner's
    angle-weighted pseudonormal, which is exact on closed regions.
    """

    def __init__(self, vertices, faces):
        import trimesh

        self.mesh = trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces), process=False)
        points, faces = self.mesh.vertices, self.mesh.faces
        _, welded = np.unique(np.round(points * 1e5).astype(np.int64), axis=0, return_inverse=True)
        self.welded = welded.ravel()[faces]
        normals = self.mesh.face_normals
        self.corner_normals = np.zeros((self.welded.max() + 1, 3))
        self.edge_normals, uses = {}, {}
        for c in range(3):
            first, second = points[faces[:, (c + 1) % 3]] - points[faces[:, c]], points[faces[:, (c + 2) % 3]] - points[faces[:, c]]
            cosine = np.einsum("ij,ij->i", first, second) / np.maximum(
                np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1), 1e-12)
            np.add.at(self.corner_normals, self.welded[:, c], normals * np.arccos(np.clip(cosine, -1, 1))[:, None])
        for face, corners in enumerate(self.welded):
            for c in range(3):
                edge = tuple(sorted((corners[c], corners[(c + 1) % 3])))
                self.edge_normals[edge] = self.edge_normals.get(edge, 0) + normals[face]
                uses[edge] = uses.get(edge, 0) + 1
        self.open_edges = {edge for edge, count in uses.items() if count == 1}
        self.open_corners = {corner for edge in self.open_edges for corner in edge}


def _surface(parts):
    vertices = [np.asarray(part.vertices, float) for part in parts]
    offsets = np.cumsum([0] + [len(item) for item in vertices])
    return _Surface(np.concatenate(vertices), np.concatenate([np.asarray(part.faces) + offsets[i] for i, part in enumerate(parts)]))


def _signed_distance(surface: _Surface, points):
    """Signed distance, positive outside; +inf where the closest feature is an open rim."""
    import trimesh

    points = np.asarray(points, float)
    closest, distance, triangle = trimesh.proximity.closest_point(surface.mesh, points)
    barycentric = trimesh.triangles.points_to_barycentric(surface.mesh.triangles[triangle], closest)
    zero = barycentric <= 1e-6
    side = surface.mesh.face_normals[triangle].copy()
    result = distance.copy()
    for i in np.where(zero.any(1))[0]:
        corners = surface.welded[triangle[i]]
        if zero[i].sum() == 1:
            kept = corners[~zero[i]]
            edge = tuple(sorted(kept))
            if edge in surface.open_edges:
                result[i] = np.inf
                continue
            side[i] = surface.edge_normals[edge]
        else:
            corner = corners[int(np.argmax(barycentric[i]))]
            if corner in surface.open_corners:
                result[i] = np.inf
                continue
            side[i] = surface.corner_normals[corner]
    sign = np.sign(np.einsum("ij,ij->i", points - closest, side))
    return np.where(np.isinf(result), result, result * np.where(sign == 0, 1.0, sign))


def _skin_through(body: _Surface, garment_points, garment_faces, authored=None) -> tuple[int, float]:
    """Body vertices that came out through their closest garment face: (count, deepest mm)."""
    through, depth = _skin_through_mask(body, garment_points, garment_faces, authored)
    return int(through.sum()), float(depth[through].max() * 1000) if through.any() else 0.0


def _skin_through_mask(body: _Surface, garment_points, garment_faces, authored=None) -> tuple[np.ndarray, np.ndarray]:
    """Which body vertices came through the garment, and each vertex's distance in front of it.

    The vertex is in front of that face, which faces the way the skin does and
    is closer than SKIN_REACH, and the garment point beneath it is inside the
    body (a hand in front of a strap on the hip is not through it). A closest
    point on the garment's open hem does not count: the body is beside the
    garment there, not under it. With ``authored`` (the garment's points as
    authored and the authored body), a vertex whose garment point was already
    inside the authored body is not counted: the outfit came that way.
    """
    import trimesh

    garment = _Surface(garment_points, garment_faces)
    points = body.mesh.vertices
    signed = _signed_distance(garment, points)
    beneath, _, triangle = trimesh.proximity.closest_point(garment.mesh, points)
    facing = np.einsum("ij,ij->i", garment.mesh.face_normals[triangle], body.mesh.vertex_normals)
    through = np.isfinite(signed) & (signed > INSIDE) & (signed < SKIN_REACH) & (facing > SKIN_FACING)
    if through.any():
        through[through] = _signed_distance(body, beneath[through]) < 0.0
    if through.any() and authored is not None:
        before, authored_body = authored
        corners = garment.mesh.faces[triangle[through]]
        weights = trimesh.triangles.points_to_barycentric(garment.mesh.triangles[triangle[through]], beneath[through])
        point = np.einsum("ij,ijk->ik", weights, np.asarray(before, float)[corners])
        through[through] = ~(_signed_distance(authored_body, point) < -INSIDE)
    return through, signed


def _joined(parts):
    points = [np.asarray(part.vertices, float) for part in parts]
    offsets = np.cumsum([0] + [len(item) for item in points])
    return np.concatenate(points), np.concatenate([np.asarray(part.faces) + offsets[i] for i, part in enumerate(parts)])


def rigid_residual(before: np.ndarray, after: np.ndarray) -> float:
    """Largest distance from the best rigid motion (Kabsch) of ``before`` onto ``after``."""
    a, b = before - before.mean(0), after - after.mean(0)
    u, _, vt = np.linalg.svd(a.T @ b)
    flip = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag([1.0, 1.0, flip]) @ u.T
    return float(np.linalg.norm(a @ rotation.T - b, axis=1).max())


def edge_strain(before: np.ndarray, after: np.ndarray, faces: np.ndarray) -> np.ndarray:
    edges = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    authored = np.linalg.norm(before[edges[:, 0]] - before[edges[:, 1]], axis=1)
    fitted = np.linalg.norm(after[edges[:, 0]] - after[edges[:, 1]], axis=1)
    keep = authored > 1e-7
    return np.abs(fitted[keep] / authored[keep] - 1.0)


def _crossings(first: np.ndarray, second: np.ndarray) -> int:
    import fcl

    def shape(triangles):
        model = fcl.BVHModel()
        model.beginModel(len(triangles) * 3, len(triangles))
        model.addSubModel(triangles.reshape(-1, 3), np.arange(len(triangles) * 3).reshape(-1, 3))
        model.endModel()
        return fcl.CollisionObject(model, fcl.Transform())
    result = fcl.CollisionResult()
    fcl.collide(shape(first), shape(second), fcl.CollisionRequest(num_max_contacts=100000, enable_contact=True), result)
    return len({(contact.b1, contact.b2) for contact in result.contacts})


def _summary(values) -> dict:
    values = np.asarray(values, float)
    return {"p95": float(np.percentile(values, 95)), "max": float(values.max())} if len(values) else {"p95": 0.0, "max": 0.0}


def _solid(before: np.ndarray, island_faces: np.ndarray, limit: float, body_low: np.ndarray, body_high: np.ndarray) -> bool:
    """A small closed piece (blade, buckle, plate): every edge has two faces, no larger than ``limit``.

    A closed band the body passes through (a collar, a belt) is meant to conform,
    so a piece whose bounds contain the body's centre line is not counted, as in
    the native band test.
    """
    keys = np.unique(np.round(before * 1e5).astype(np.int64), axis=0, return_inverse=True)[1].ravel()[island_faces]
    edges = np.sort(np.concatenate([keys[:, [0, 1]], keys[:, [1, 2]], keys[:, [2, 0]]]), axis=1)
    _, uses = np.unique(edges, axis=0, return_counts=True)
    points = before[np.unique(island_faces)]
    low, high = points.min(0), points.max(0)
    up = int(np.argmax(body_high - body_low))
    centre = (body_low + body_high) / 2
    band = all(low[axis] <= centre[axis] <= high[axis] for axis in range(3) if axis != up)
    return bool(np.all(uses == 2)) and float((high - low).max()) <= limit and not band


def analyse(run: dict, config: dict, reference: RefitReferenceBody | None) -> dict:
    body_count, islands = run["body_count"], run["islands"]
    driver = _surface(run["fitted"].submeshes[:body_count])
    # Without an authored body, "already inside" is judged against the driver as loaded.
    authored = (_Surface(reference.source_positions, reference.faces) if reference is not None
                else _surface(run["mesh"].submeshes[:body_count]))
    driver_points = np.concatenate([np.asarray(p.vertices, float) for p in run["mesh"].submeshes[:body_count]])
    solid_limit = .25 * float(np.linalg.norm(driver_points.max(0) - driver_points.min(0)))
    tails = {tuple(item) for item in config.get("tails", ())}
    parts, pieces, cloth, tail = [], [], [], []
    rigid_worst = solid_worst = 0.0
    solid_count = 0
    for part, (before_part, after_part) in enumerate(zip(run["mesh"].submeshes[body_count:], run["fitted"].submeshes[body_count:])):
        before, after = np.asarray(before_part.vertices, float), np.asarray(after_part.vertices, float)
        faces = np.asarray(before_part.faces)
        rigid = _rigid(config, part, len(islands[part]))
        inside_after = _signed_distance(driver, after) < -INSIDE
        inside_before = _signed_distance(authored, before) < -INSIDE
        depth = -_signed_distance(driver, after)
        new = inside_after & ~inside_before
        row = {"part": part, "name": before_part.name, "islands": [],
               "new_inside_vertices": int(new.sum()), "deepest_new_inside_mm": float(depth[new].max() * 1000) if new.any() else 0.0,
               "inside_vertices": int(inside_after.sum()), "inside_vertices_authored": int(inside_before.sum())}
        for island, group in enumerate(islands[part]):
            island_faces = faces[list(group)]
            vertices = np.unique(island_faces)
            strain = edge_strain(before, after, island_faces)
            item = {"island": island, "faces": len(group), "rigid": island in rigid,
                    "moved_mm": float(np.linalg.norm(after[vertices].mean(0) - before[vertices].mean(0)) * 1000),
                    "strain": _summary(strain)}
            residual = rigid_residual(before[vertices], after[vertices])
            # Moved without changing shape: the fit treated it as rigid (marked or inferred).
            item["rigid_in_fit"] = residual < 1e-5 and float(np.abs(after[vertices] - before[vertices]).max()) > 5e-4
            if _solid(before, island_faces, solid_limit, driver_points.min(0), driver_points.max(0)):
                item["solid_residual_mm"] = residual * 1000
                solid_worst, solid_count = max(solid_worst, item["solid_residual_mm"]), solid_count + 1
            if island in rigid:
                item["rigid_residual_mm"] = rigid_residual(before[vertices], after[vertices]) * 1000
                rigid_worst = max(rigid_worst, item["rigid_residual_mm"])
            else:
                cloth.append(strain)
                if (part, island) in tails:
                    tail.append(strain)
            row["islands"].append(item)
            pieces.append((part, island, before[island_faces], after[island_faces]))
        parts.append(row)
    crossings = []
    for a in range(len(pieces)):
        for b in range(a + 1, len(pieces)):
            pa, ia, before_a, after_a = pieces[a]
            pb, ib, before_b, after_b = pieces[b]
            low = np.maximum(after_a.reshape(-1, 3).min(0), after_b.reshape(-1, 3).min(0))
            high = np.minimum(after_a.reshape(-1, 3).max(0), after_b.reshape(-1, 3).max(0))
            if (low > high).any():
                continue
            after = _crossings(after_a, after_b)
            if after and after > (before := _crossings(before_a, before_b)):
                rigid_sides = parts[pa]["islands"][ia]["rigid_in_fit"] + parts[pb]["islands"][ib]["rigid_in_fit"]
                crossings.append({"a": [pa, ia], "b": [pb, ib], "before": before, "after": after,
                                  "kind": ("cloth-cloth", "rigid-cloth", "rigid-rigid")[rigid_sides]})
    worst_cloth = sorted(((row["part"], item["island"], item["strain"]["p95"]) for row in parts for item in row["islands"]
                          if not item["rigid"]), key=lambda value: -value[2])[:8]
    garment_before, garment_faces = _joined(run["mesh"].submeshes[body_count:])
    garment_after, _ = _joined(run["fitted"].submeshes[body_count:])
    skin, skin_depth = _skin_through(driver, garment_after, garment_faces, (garment_before, authored))
    skin_all, _ = _skin_through(driver, garment_after, garment_faces)
    skin_authored, _ = _skin_through(authored, garment_before, garment_faces)
    return {
        "summary": {
            "method": run["method"], "status": run["status"], "seconds": run["seconds"],
            "worst_rigid_distortion_mm": rigid_worst,
            # Small closed pieces should never bend, marked or not.
            "solid_pieces": solid_count, "worst_solid_distortion_mm": solid_worst,
            "new_inside_vertices": sum(row["new_inside_vertices"] for row in parts),
            "deepest_new_inside_mm": max((row["deepest_new_inside_mm"] for row in parts), default=0.0),
            # Skin through cloth where the authored body did not come through the same garment point,
            # beside every such vertex and the count on the authored body under the outfit as loaded.
            "new_skin_through_vertices": skin, "deepest_new_skin_through_mm": skin_depth,
            "skin_through_vertices": skin_all, "skin_through_vertices_authored": skin_authored,
            "new_layer_crossing_pairs": len(crossings),
            "new_layer_crossing_triangles": sum(item["after"] - item["before"] for item in crossings),
            "new_crossing_triangles_by_kind": {kind: sum(item["after"] - item["before"] for item in crossings if item["kind"] == kind)
                                               for kind in ("cloth-cloth", "rigid-cloth", "rigid-rigid")},
            # Pieces that did not touch at all as authored; the rest grew an authored overlap (often a seam).
            "new_crossing_triangles_on_clean_pairs": sum(item["after"] for item in crossings if item["before"] == 0),
            "cloth_strain": _summary(np.concatenate(cloth)) if cloth else _summary(()),
            "tail_strain": _summary(np.concatenate(tail)) if tail else _summary(()),
        },
        "worst_cloth_islands_p95": [{"part": part, "island": island, "p95": value} for part, island, value in worst_cloth],
        "new_layer_crossings": crossings, "parts": parts, "error": run["error"], "last_fit": run["last_fit"],
    }


def analyse_poses(run: dict, rig: dict) -> dict:
    """What each pose in ``tools.refit_reference_poses`` adds, for the fit on the driver and as authored."""
    from tools.refit_reference_poses import (
        POSES,
        blended_matrices,
        follow_error,
        pose_matrices,
        skin_parts,
        slot_transforms,
    )

    count = run["body_count"]
    pairings = {
        "fitted": (rig["driver"], run["fitted"].submeshes[:count], rig["body_slots"],
                   run["fitted"].submeshes[count:], rig["outfit_driver_slots"]),
        "authored": (rig["authored"], rig["nude_parts"], rig["nude_slots"], run["mesh"].submeshes[count:], rig["outfit_slots"]),
    }
    result = {}
    for label, (skeleton, body_parts, body_slots, garment_parts, garment_slots) in pairings.items():
        body_rest, body_faces = _joined(body_parts)
        garment_rest, garment_faces = _joined(garment_parts)
        rest = _Surface(body_rest, body_faces)
        inside_rest = _signed_distance(rest, garment_rest) < -INSIDE
        skin_rest, _ = _skin_through_mask(rest, garment_rest, garment_faces)
        for name, pose in POSES.items():
            matrices = pose_matrices(skeleton, pose)
            body_transforms = slot_transforms(matrices, body_slots)
            body_posed = skin_parts(body_parts, [np.asarray(p.vertices, float) for p in body_parts], body_transforms)
            garment_posed = skin_parts(garment_parts, [np.asarray(p.vertices, float) for p in garment_parts],
                                       slot_transforms(matrices, garment_slots))
            posed = _Surface(body_posed, body_faces)
            depth = -_signed_distance(posed, garment_posed)
            added = (depth > INSIDE) & ~inside_rest
            skin, _ = _skin_through_mask(posed, garment_posed, garment_faces)
            follow = follow_error(body_rest, blended_matrices(body_parts, body_transforms), garment_rest, garment_posed)
            result.setdefault(name, {})[label] = {
                "added_inside": int(added.sum()),
                "deepest_added_inside_mm": float(depth[added].max() * 1000) if added.any() else 0.0,
                "added_skin_through": int((skin & ~skin_rest).sum()),
                "follow_p95_mm": float(np.percentile(follow, 95) * 1000) if len(follow) else 0.0,
                "follow_max_mm": float(follow.max() * 1000) if len(follow) else 0.0,
            }
    return result


# ------------------------------------------------------------------ renders
_PALETTE = np.array([(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
                     (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
                     (170, 110, 40), (255, 250, 200), (128, 0, 0), (170, 255, 195)], float) / 255.0


def _render(meshes, yaw, size, center, extent):
    """Orthographic flat-shaded z-buffer; +Y up, yaw 180 shows the character's front."""
    angle = np.radians(yaw)
    rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]])
    image = np.full((size, size, 3), .08)
    depth = np.full((size, size), -np.inf)
    light = np.array([.3, .5, 1.]) / np.linalg.norm([.3, .5, 1.])
    for vertices, faces, colour in meshes:
        view = (np.asarray(vertices, float) - center) @ rotation.T
        faces = np.asarray(faces, int)
        x, y = (view[:, 0] / extent * .5 + .5) * size, (.5 - view[:, 1] / extent * .5) * size
        triangles = view[faces]
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        shade = .25 + .75 * np.abs(normals @ light)
        for index, (a, b, c) in enumerate(faces):
            xs, ys, zs = x[[a, b, c]], y[[a, b, c]], view[[a, b, c], 2]
            left, right = int(max(np.floor(xs.min()), 0)), int(min(np.ceil(xs.max()), size - 1))
            top, bottom = int(max(np.floor(ys.min()), 0)), int(min(np.ceil(ys.max()), size - 1))
            if right < left or bottom < top:
                continue
            grid_x, grid_y = np.meshgrid(np.arange(left, right + 1) + .5, np.arange(top, bottom + 1) + .5)
            area = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(area) < 1e-12:
                continue
            w0 = ((ys[1] - ys[2]) * (grid_x - xs[2]) + (xs[2] - xs[1]) * (grid_y - ys[2])) / area
            w1 = ((ys[2] - ys[0]) * (grid_x - xs[2]) + (xs[0] - xs[2]) * (grid_y - ys[2])) / area
            w2 = 1 - w0 - w1
            covered = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
            window = depth[top:bottom + 1, left:right + 1]
            nearer = covered & (z > window)
            window[nearer] = z[nearer]
            image[top:bottom + 1, left:right + 1][nearer] = colour * shade[index]
    return (np.clip(image, 0, 1) * 255).astype(np.uint8)


def render_sheet(mesh: ParsedMesh, body_count: int, path: Path, size: int = 500) -> Path:
    from PIL import Image

    garments = np.concatenate([np.asarray(part.vertices, float) for part in mesh.submeshes[body_count:]])
    center = (garments.min(0) + garments.max(0)) / 2
    extent = float((garments.max(0) - garments.min(0)).max()) * .6
    meshes = [(part.vertices, part.faces, np.array([.75, .72, .68])) for part in mesh.submeshes[:body_count]]
    meshes += [(part.vertices, part.faces, _PALETTE[index % len(_PALETTE)])
               for index, part in enumerate(mesh.submeshes[body_count:])]
    tiles = [_render(meshes, yaw, size, center, extent) for yaw in (180, 90, 0, -90)]
    Image.fromarray(np.concatenate(tiles, axis=1)).save(path)
    return path


# ------------------------------------------------------------------ corpus
_CORPUS_COLUMNS = {"new_inside_vertices": np.sum, "deepest_new_inside_mm": np.max, "new_skin_through_vertices": np.sum,
                   "deepest_new_skin_through_mm": np.max, "skin_through_vertices": np.sum, "new_layer_crossing_triangles": np.sum,
                   "new_crossing_triangles_on_clean_pairs": np.sum,
                   "rigid_cloth_crossing_triangles": np.sum, "worst_solid_distortion_mm": np.max, "seconds": np.sum}


def run_corpus(args) -> int:
    """Fit every outfit of a corpus unmarked, as a fresh setup, and tabulate both methods side by side."""
    if not mesh_native_core.native_mesh_core_available():
        raise SystemExit("Build the native mesh core first (native/cdmw_mesh_core, Release).")
    outfits = [item if isinstance(item, str) else item["outfit"] for item in json.loads(args.corpus.read_text(encoding="utf-8"))]
    dependencies = _archive_index(args.game_root)
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for outfit in outfits:
        config = {"body": args.driver, "outfit": outfit, "clearance": 0.1, "tightness": 100.0}
        row = {"outfit": outfit, "runs": {}}
        try:
            inputs = _archive_inputs(config, dependencies)
            row["reference"], row["reason"] = inputs["provenance"]["reference"], inputs["reason"]
            rig = _rig(config, dependencies, inputs) if args.poses else None
            for method in args.method:
                if method == "reference" and inputs["reference"] is None:
                    continue
                run = fit(inputs, config, method)
                report = analyse(run, config, inputs["reference"])
                summary = report["summary"]
                if rig is not None:
                    summary["poses"] = analyse_poses(run, rig)
                summary["cloth_strain_p95"] = summary["cloth_strain"]["p95"]
                summary["cloth_strain_max"] = summary["cloth_strain"]["max"]
                summary["rigid_cloth_crossing_triangles"] = summary["new_crossing_triangles_by_kind"]["rigid-cloth"]
                row["runs"][method] = summary
        except Exception as exc:  # one broken asset must not stop the corpus
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
        cells = []
        for method in args.method:
            s = row["runs"].get(method)
            cells.append(f"{method}: " + ("-" if s is None else
                         f"{s['status']}, inside {s['new_inside_vertices']} ({s['deepest_new_inside_mm']:.1f} mm), "
                         f"new skin {s['new_skin_through_vertices']} ({s['deepest_new_skin_through_mm']:.1f} mm) "
                         f"of {s['skin_through_vertices']}, "
                         f"cross {s['new_layer_crossing_triangles']} (rigid-cloth {s['rigid_cloth_crossing_triangles']}, "
                         f"clean pairs {s['new_crossing_triangles_on_clean_pairs']}), "
                         f"strain p95 {s['cloth_strain_p95']:.2f}, "
                         f"solid {s['worst_solid_distortion_mm']:.1f} mm, {s['seconds']:.1f} s"))
        print(outfit.rsplit("/", 1)[-1], "|", " | ".join(cells), "|", row.get("error") or row.get("reason") or "", flush=True)
        for method in args.method:
            poses = (row["runs"].get(method) or {}).get("poses")
            for name, pairs in (poses or {}).items():
                print(f"    {method} {name}: " + " | ".join(
                    f"{label} inside +{p['added_inside']} ({p['deepest_added_inside_mm']:.1f} mm), skin +{p['added_skin_through']}, "
                    f"follow p95 {p['follow_p95_mm']:.1f} max {p['follow_max_mm']:.1f} mm" for label, p in pairs.items()), flush=True)
        (args.output / "corpus.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    totals = {}
    for method in args.method:
        rows = [row["runs"][method] for row in results if method in row["runs"]]
        totals[method] = {"outfits": len(rows), "refused": sum(r["status"] != "ok" for r in rows),
                          **{key: float(combine([r[key] for r in rows])) if rows else 0.0
                             for key, combine in _CORPUS_COLUMNS.items()},
                          "median_cloth_strain_p95": float(np.median([r["cloth_strain_p95"] for r in rows])) if rows else 0.0}
        posed = [r["poses"] for r in rows if "poses" in r]
        if posed:
            totals[method]["poses"] = {
                name: {label: {"added_inside": int(sum(p[name][label]["added_inside"] for p in posed)),
                               "added_skin_through": int(sum(p[name][label]["added_skin_through"] for p in posed)),
                               "median_follow_p95_mm": float(np.median([p[name][label]["follow_p95_mm"] for p in posed])),
                               "worst_follow_max_mm": float(max(p[name][label]["follow_max_mm"] for p in posed))}
                       for label in posed[0][name]}
                for name in posed[0]}
    print(json.dumps(totals, indent=1))
    (args.output / "corpus.json").write_text(json.dumps({"driver": args.driver, "outfits": results, "totals": totals},
                                                        indent=1), encoding="utf-8")
    return 0


# ------------------------------------------------------------------ command line
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", choices=sorted(PRESETS), help="A built-in fitting case")
    parser.add_argument("--config", type=Path, help="JSON with body/outfit/reference paths, parts, clearance and tails")
    parser.add_argument("--assets", type=Path, help="Folder of decoded PACs and PABs (file mode)")
    parser.add_argument("--game-root", type=Path, help="Crimson Desert install to read the PACs from (read only)")
    parser.add_argument("--method", nargs="+", choices=("reference", "bound"), default=["reference"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true", help="Write before/after Part-colour sheets (needs Pillow)")
    parser.add_argument("--unmarked", action="store_true",
                        help="Fit every Part as cloth, as a new setup does, but still score the config's rigid pieces")
    parser.add_argument("--corpus", type=Path,
                        help="JSON list of outfit archive paths, each fitted unmarked onto --driver (needs --game-root)")
    parser.add_argument("--driver", default=PRESETS["11002"]["body"], help="Driver body archive path for --corpus")
    parser.add_argument("--poses", action="store_true",
                        help="Also pose body and outfit together and score what motion adds (archive mode)")
    args = parser.parse_args(argv)
    if bool(args.assets) == bool(args.game_root):
        parser.error("give exactly one of --assets or --game-root")
    if args.poses and not args.game_root:
        parser.error("--poses resolves skeletons from --game-root")
    if args.corpus:
        if not args.game_root:
            parser.error("--corpus reads outfits from --game-root")
        _require_dev_dependencies(args.render, True)
        return run_corpus(args)
    config = dict(PRESETS.get(args.preset, {}))
    if args.config:
        config.update(json.loads(args.config.read_text(encoding="utf-8")))
    if not config.get("body") or not config.get("outfit"):
        parser.error("choose a --preset or give a --config naming body and outfit")
    _require_dev_dependencies(args.render, bool(args.game_root))
    if not mesh_native_core.native_mesh_core_available():
        raise SystemExit("Build the native mesh core first (native/cdmw_mesh_core, Release).")
    dependencies = _archive_index(args.game_root) if args.game_root else None
    inputs = _archive_inputs(config, dependencies) if dependencies else _file_inputs(config, args.assets)
    rig = _rig(config, dependencies, inputs) if args.poses else None
    if inputs["reference"] is None and "reference" in args.method:
        raise SystemExit(f"Fit to body would use only the driver: {inputs['reason']}")
    args.output.mkdir(parents=True, exist_ok=True)
    reports = {"provenance": inputs["provenance"], "config": config, "unmarked": args.unmarked, "runs": {}}
    fitting = {key: value for key, value in config.items() if key != "parts"} if args.unmarked else config
    for method in args.method:
        run = fit(inputs, fitting, method)
        report = analyse(run, config, inputs["reference"])
        if rig is not None:
            report["poses"] = analyse_poses(run, rig)
        reports["runs"][method] = report
        if args.render:
            render_sheet(run["mesh"], run["body_count"], args.output / "before.png")
            render_sheet(run["fitted"], run["body_count"], args.output / f"after_{method}.png")
        print(json.dumps({**report["summary"], **({"poses": report["poses"]} if rig is not None else {})}, indent=1))
    (args.output / "report.json").write_text(json.dumps(reports, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
