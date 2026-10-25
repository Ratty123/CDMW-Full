"""Headless Morph & Refit harness for Fit to body on real PACs.

Fits an outfit onto a driver body in one resident native session, either with
the body the outfit was authored on (``morph_set_reference_body``, the
``reference`` method) or with the driver alone (``morph_configure_refit``, the
``bound`` method), and scores each result:

- worst rigid distortion: Kabsch residual of every island the config marks rigid;
- new inside-body vertices: garment vertices more than 0.5 mm inside the driver
  that were not already inside the authored body;
- new layer crossings: triangle pairs between garment islands that intersect
  after the fit but not before (python-fcl);
- cloth edge strain: ``|length / authored length - 1|`` over flexible islands,
  and over the islands the config names as ``tails``.

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


def _archive_inputs(config: dict, game_root: Path) -> dict:
    """Load both PACs as the editor's archive Refit does and ask its lookup for the reference."""
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_mesh_appearance import UnresolvedPacBonePaletteError, apply_archive_mesh_appearance
    from cdmw.services.mesh_archive_refit import ArchiveRefitAsset, ArchiveRefitContext
    from cdmw.services.mesh_refit_reference_lookup import find_refit_reference_body
    from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _real_archive_all_pamt_entries

    entries, _pamts, errors = _real_archive_all_pamt_entries(game_root)
    if not entries:
        raise SystemExit(f"No archive entries under {game_root}: {errors[:1]}")
    by_path, by_basename = _archive_entry_indexes(entries)
    # The members of the editor's ArchiveWorkflowDependencyContext the lookup reads, without Qt.
    dependencies = SimpleNamespace(
        entries_by_normalized_path=by_path, entries_by_basename=by_basename,
        entry_for_path=lambda path: next(iter(by_path.get(_archive_key(path), ())), None),
    )
    assets, meshes, appearances, offset = [], {}, {}, 0
    for role, name in (("body", "body"), ("loaded", "outfit")):
        entry = dependencies.entry_for_path(config[name])
        if entry is None:
            raise SystemExit(f"{config[name]} is not in the game archive.")
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
    if lookup.reference is None:
        raise SystemExit(f"Fit to body would use only the driver: {lookup.reason}")
    return {"body": meshes["body"], "outfit": meshes["outfit"], "reference": lookup.reference,
            "provenance": {"game_root": str(game_root), "body": config["body"], "outfit": config["outfit"],
                           "reference": lookup.reference.label,
                           "appearances": {name: getattr(value, "source", None) for name, value in appearances.items()},
                           "substituted_bones": list(lookup.reference.substituted_bones)}}


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
def _surface(parts):
    import trimesh

    vertices = [np.asarray(part.vertices, float) for part in parts]
    offsets = np.cumsum([0] + [len(item) for item in vertices])
    faces = np.concatenate([np.asarray(part.faces) + offsets[i] for i, part in enumerate(parts)])
    return trimesh.Trimesh(np.concatenate(vertices), faces, process=False)


def _signed_distance(surface, points):
    import trimesh

    closest, distance, triangle = trimesh.proximity.closest_point(surface, points)
    side = np.sign(np.einsum("ij,ij->i", points - closest, surface.face_normals[triangle]))
    return distance * np.where(side == 0, 1.0, side)


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


def analyse(run: dict, config: dict, reference: RefitReferenceBody) -> dict:
    import trimesh

    body_count, islands = run["body_count"], run["islands"]
    driver = _surface(run["fitted"].submeshes[:body_count])
    authored = trimesh.Trimesh(np.asarray(reference.source_positions), np.asarray(reference.faces), process=False)
    tails = {tuple(item) for item in config.get("tails", ())}
    parts, pieces, cloth, tail = [], [], [], []
    rigid_worst = 0.0
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
                crossings.append({"a": [pa, ia], "b": [pb, ib], "before": before, "after": after})
    worst_cloth = sorted(((row["part"], item["island"], item["strain"]["p95"]) for row in parts for item in row["islands"]
                          if not item["rigid"]), key=lambda value: -value[2])[:8]
    return {
        "summary": {
            "method": run["method"], "status": run["status"], "seconds": run["seconds"],
            "worst_rigid_distortion_mm": rigid_worst,
            "new_inside_vertices": sum(row["new_inside_vertices"] for row in parts),
            "deepest_new_inside_mm": max((row["deepest_new_inside_mm"] for row in parts), default=0.0),
            "new_layer_crossing_pairs": len(crossings),
            "new_layer_crossing_triangles": sum(item["after"] - item["before"] for item in crossings),
            "cloth_strain": _summary(np.concatenate(cloth)) if cloth else _summary(()),
            "tail_strain": _summary(np.concatenate(tail)) if tail else _summary(()),
        },
        "worst_cloth_islands_p95": [{"part": part, "island": island, "p95": value} for part, island, value in worst_cloth],
        "new_layer_crossings": crossings, "parts": parts, "error": run["error"], "last_fit": run["last_fit"],
    }


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
    args = parser.parse_args(argv)
    if bool(args.assets) == bool(args.game_root):
        parser.error("give exactly one of --assets or --game-root")
    config = dict(PRESETS.get(args.preset, {}))
    if args.config:
        config.update(json.loads(args.config.read_text(encoding="utf-8")))
    if not config.get("body") or not config.get("outfit"):
        parser.error("choose a --preset or give a --config naming body and outfit")
    _require_dev_dependencies(args.render, bool(args.game_root))
    if not mesh_native_core.native_mesh_core_available():
        raise SystemExit("Build the native mesh core first (native/cdmw_mesh_core, Release).")
    inputs = _archive_inputs(config, args.game_root) if args.game_root else _file_inputs(config, args.assets)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = {"provenance": inputs["provenance"], "config": config, "unmarked": args.unmarked, "runs": {}}
    fitting = {key: value for key, value in config.items() if key != "parts"} if args.unmarked else config
    for method in args.method:
        run = fit(inputs, fitting, method)
        report = analyse(run, config, inputs["reference"])
        reports["runs"][method] = report
        if args.render:
            render_sheet(run["mesh"], run["body_count"], args.output / "before.png")
            render_sheet(run["fitted"], run["body_count"], args.output / f"after_{method}.png")
        print(json.dumps(report["summary"], indent=1))
    (args.output / "report.json").write_text(json.dumps(reports, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
