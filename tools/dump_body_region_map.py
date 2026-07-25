"""Segment a skinned body .pac into named regions and dump the result.

Headless counterpart to the future region-atlas UI: it answers "did the
segmentation actually land on the right anatomy" without any of the app
running. The OBJ dump carries one colour per dominant region, so the map can
be eyeballed in Blender or MeshLab.

Usage:
    python -m tools.dump_body_region_map BODY.pac --out-obj regions.obj
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from cdmw.domain.mesh.body_region_falloff import DEFAULT_FALLOFF_BAND, smooth_body_region_weights
from cdmw.domain.mesh.body_regions import (
    BodyRegionMap,
    build_body_region_map,
    dominant_region_by_vertex,
)
from cdmw.modding.mesh_parser import parse_mesh, resolve_pac_bone_palette
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames, parse_pab


# Distinct hues rather than a gradient: neighbouring regions must not read as
# the same colour when the dump is inspected by eye.
_REGION_COLOURS: tuple[tuple[float, float, float], ...] = (
    (0.90, 0.25, 0.25),
    (0.25, 0.60, 0.90),
    (0.35, 0.80, 0.35),
    (0.95, 0.70, 0.20),
    (0.70, 0.40, 0.90),
    (0.20, 0.80, 0.80),
    (0.95, 0.45, 0.75),
    (0.60, 0.55, 0.30),
    (0.45, 0.45, 0.95),
    (0.85, 0.55, 0.35),
    (0.40, 0.75, 0.60),
    (0.80, 0.80, 0.40),
)
_UNCLAIMED_COLOUR = (0.35, 0.35, 0.35)


def _skeleton_candidates(pac_path: Path, explicit: Path | None) -> tuple[Path, ...]:
    """Every .pab worth trying for this body, best-named first.

    Races share rigs — the "other" races carry no .pab of their own and skin
    against the phm/phw/ptm ones — so name matching alone is not enough. The
    caller settles it by seeing whose palette actually resolves.
    """

    if explicit is not None:
        return (explicit,) if explicit.is_file() else ()
    ordered: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path).lower()
        if path.is_file() and key not in seen:
            seen.add(key)
            ordered.append(path)

    _add(pac_path.with_suffix(".pab"))
    names = iter_pab_candidate_basenames(pac_path.as_posix())
    # Race rigs sit beside the model folder, shared ones several levels up.
    directory = pac_path.parent
    for _level in range(6):
        for basename in names:
            _add(directory / basename)
        if directory.parent == directory:
            break
        directory = directory.parent
    # Shared rigs live in a sibling race folder (a "pom" body skins against
    # phm_01.pab), so sweep the surrounding tree once the named guesses run out.
    # Bounded so a full game extract does not turn this into a directory crawl.
    for root in pac_path.parents[:5]:
        for found in sorted(root.rglob("*.pab"))[:64]:
            _add(found)
        if len(ordered) >= 64:
            break
    return tuple(ordered)


def _resolve_skeleton(pac_path: Path, raw: bytes, explicit: Path | None):
    """Pick the candidate whose bone palette resolves, else the first parsed."""

    first = None
    for candidate in _skeleton_candidates(pac_path, explicit):
        try:
            skeleton = parse_pab(candidate.read_bytes(), candidate.name)
        except Exception:
            continue
        skeleton.path = str(candidate)
        palette = resolve_pac_bone_palette(raw, skeleton)
        if palette:
            return skeleton, palette
        first = first or (skeleton, ())
    return first if first is not None else (None, ())


def _write_region_obj(path: Path, mesh: object, region_map: BodyRegionMap) -> None:
    """Write an OBJ whose vertex lines carry per-region colours.

    ``v x y z r g b`` is the widely supported vertex-colour extension; readers
    that ignore the extra floats still load the geometry.
    """

    colour_by_region = {
        region.region_id: _REGION_COLOURS[index % len(_REGION_COLOURS)]
        for index, region in enumerate(region_map.populated_regions)
    }
    dominant = dominant_region_by_vertex(region_map)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())

    lines: list[str] = ["# CDMW body region map", f"# fingerprint {region_map.topology_fingerprint}"]
    vertex_base = 0
    for submesh_index, submesh in enumerate(submeshes):
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        faces = tuple(getattr(submesh, "faces", ()) or ())
        lines.append(f"o submesh_{submesh_index}_{getattr(submesh, 'name', '') or 'unnamed'}")
        for vertex_index, vertex in enumerate(vertices):
            region_id = dominant.get((submesh_index, vertex_index), "")
            red, green, blue = colour_by_region.get(region_id, _UNCLAIMED_COLOUR)
            lines.append(
                f"v {float(vertex[0]):.6f} {float(vertex[1]):.6f} {float(vertex[2]):.6f} "
                f"{red:.3f} {green:.3f} {blue:.3f}"
            )
        for face in faces:
            a, b, c = (int(face[0]) + 1, int(face[1]) + 1, int(face[2]) + 1)
            lines.append(f"f {a + vertex_base} {b + vertex_base} {c + vertex_base}")
        vertex_base += len(vertices)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_lines(region_map: BodyRegionMap) -> list[str]:
    populated = region_map.populated_regions
    lines = [
        f"skeleton      : {region_map.skeleton_source or '(none)'}",
        f"bones         : {region_map.mapped_bone_count} mapped / {region_map.skeleton_bone_count} total",
        f"vertices      : {region_map.skinned_vertex_count} skinned / "
        f"{region_map.unskinned_vertex_count} unskinned",
        f"regions       : {len(populated)} populated / {len(region_map.regions)} resolved",
        f"unclaimed wt  : {region_map.unmapped_weight_fraction * 100.0:.2f}%",
        "",
        f"{'region':<16}{'group':<8}{'side':<8}{'verts':>8}{'dominant':>10}{'peak':>8}  axis",
    ]
    for region in populated:
        axis = region.axis
        lines.append(
            f"{region.region_id:<16}{region.group:<8}{region.side:<8}"
            f"{region.vertex_count:>8}{region.dominant_vertex_count:>10}"
            f"{region.peak_weight:>8.3f}  "
            f"{axis.source} len={axis.length:.4f}"
        )
    empty = [region.region_id for region in region_map.regions if region.empty]
    if empty:
        lines += ["", f"resolved but unweighted: {', '.join(empty)}"]
    if region_map.unmapped_bone_names:
        lines += ["", "unmapped bones (tune the rule table against these):"]
        lines += [f"  {name}" for name in region_map.unmapped_bone_names]
    if region_map.diagnostics:
        lines += [""] + [f"! {message}" for message in region_map.diagnostics]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump the body-region segmentation of a .pac.")
    parser.add_argument("pac", type=Path, help="Body .pac to segment.")
    parser.add_argument("--pab", type=Path, default=None, help="Skeleton to use instead of the sibling .pab.")
    parser.add_argument("--out-obj", type=Path, default=None, help="Write a region-coloured OBJ here.")
    parser.add_argument("--out-json", type=Path, default=None, help="Write the full region map here.")
    parser.add_argument("--min-weight", type=float, default=1.0e-3, help="Drop region weights below this.")
    parser.add_argument(
        "--falloff",
        type=float,
        default=DEFAULT_FALLOFF_BAND,
        help="Metres of surface over which regions fade out; 0 keeps hard edges.",
    )
    args = parser.parse_args(argv)

    if not args.pac.is_file():
        parser.error(f"Body .pac not found: {args.pac}")

    raw = args.pac.read_bytes()
    mesh = parse_mesh(raw, args.pac.name)
    skeleton, palette = _resolve_skeleton(args.pac, raw, args.pab)
    if skeleton is None:
        print("! No .pab found; every region will be empty. Pass --pab explicitly.")
    elif not palette:
        print("! No candidate skeleton resolved this .pac's bone palette; slots stay unnamed.")
    region_map = build_body_region_map(
        mesh,
        skeleton,
        minimum_weight=args.min_weight,
        bone_palette=palette or None,
    )
    region_map = smooth_body_region_weights(mesh, region_map, band=args.falloff)
    print("\n".join(_report_lines(region_map)))

    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(asdict(region_map), indent=2), encoding="utf-8")
        print(f"\nwrote {args.out_json}")
    if args.out_obj is not None:
        args.out_obj.parent.mkdir(parents=True, exist_ok=True)
        _write_region_obj(args.out_obj, mesh, region_map)
        print(f"wrote {args.out_obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
