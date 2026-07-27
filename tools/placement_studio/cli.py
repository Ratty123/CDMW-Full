"""Placement Studio command line.

Argument parsing and dispatch. Corpus commands live here; every gate lives in `gates.py`.

    python -m tools.placement_studio.cli inventory
    python -m tools.placement_studio.cli extract
    python -m tools.placement_studio.cli derive
    python -m tools.placement_studio.cli replay
    python -m tools.placement_studio.cli merge
    python -m tools.placement_studio.cli phase0     # all gates, exit 1 on failure
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.placement_studio import gates, ops  # noqa: E402
from tools.placement_studio.cli_support import (  # noqa: E402
    combination_pairs,
    derive_all,
    discover_body_meshes,
    hash_index,
    log,
    vanilla_based,
)
from tools.placement_studio.corpus import (  # noqa: E402
    Baseline,
    GoldenMod,
    discover_golden_mods,
    extract_baseline,
    game_root,
    golden_game_paths,
    golden_root,
    sha256_bytes,
    work_root,
)


def cmd_inventory(_args: argparse.Namespace) -> int:
    mods = discover_golden_mods()
    paths = golden_game_paths(mods)
    log(f"Golden root : {golden_root()}")
    log(f"Game root   : {game_root()}")
    log(f"Mods        : {len(mods)}")
    log(f"Unique paths: {len(paths):,}")
    log("")
    by_group: Dict[str, List[GoldenMod]] = {}
    for mod in mods:
        by_group.setdefault(mod.group, []).append(mod)
    for group, items in sorted(by_group.items()):
        log(f"[{group}]")
        for mod in items:
            log(f"  {mod.manager:<8} {len(mod.files):>4} files  {mod.name}")
    log("")
    kinds: Dict[str, int] = {}
    for path in paths:
        kinds[Path(path).suffix.lower() or "(none)"] = kinds.get(Path(path).suffix.lower() or "(none)", 0) + 1
    log("Path kinds:")
    for suffix, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        log(f"  {suffix:<18} {count:>5,}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    from tools.placement_studio.session import skeleton_paths_for

    mods = discover_golden_mods()
    paths = golden_game_paths(mods)

    # Sockets are meaningless in 3D without the skeleton they hang off, and the socket file
    # is named after its `.pab`, so the pairing is derived rather than hardcoded.
    skeletons = skeleton_paths_for(paths)
    if skeletons:
        log(f"Including {len(skeletons)} derived skeleton path(s):")
        for path in skeletons:
            log(f"  {path}")
        paths = sorted(set(paths) | set(skeletons))

    # Meshes for the clipping check: the weapons the golden socket files describe, plus a
    # small body proxy per model. Judging clipping needs geometry, not just sockets.
    from tools.placement_studio.meshes import weapon_mesh_path
    from tools.placement_studio.resolver import model_of, weapon_id_of

    meshes: set[str] = set()
    for path in paths:
        if path.endswith(".sockets.xml") and "/weapon/" in path:
            model = model_of(path)
            if model:
                meshes.add(weapon_mesh_path(weapon_id_of(path), model))
    body = discover_body_meshes(sorted({model_of(p) for p in paths if p.endswith(".sockets.xml")}))
    if meshes or body:
        log(f"Including {len(meshes)} weapon mesh(es) and {len(body)} body mesh(es)")
        paths = sorted(set(paths) | meshes | set(body))

    log(f"Extracting pinned vanilla baseline for {len(paths):,} path(s)")
    baseline = extract_baseline(paths, onlog=log)
    manifest = json.loads((baseline.root / "baseline.json").read_text(encoding="utf-8"))
    missing = manifest.get("missing") or []
    log(f"Extracted {len(baseline):,}; missing {len(missing):,}")
    if missing and args.verbose:
        for path in missing[:40]:
            log(f"  MISSING {path}")
    return 0


def cmd_derive(args: argparse.Namespace) -> int:
    baseline = Baseline.load()
    results, warnings = derive_all(baseline)
    out_dir = work_root() / "plans"
    totals: Dict[str, int] = {}
    for mod, plan in results:
        for tier, count in plan.tier_counts().items():
            totals[tier] = totals.get(tier, 0) + count
        ops.write_plan(plan, out_dir / f"{mod.group}__{mod.name}.json".replace("/", "_"))
        log(f"{len(plan.operations):>5} ops  {plan.tier_counts()}  {mod.key}")
    log("")
    log(f"Tier totals: {dict(sorted(totals.items()))}")
    log(f"Plans written to {out_dir}")
    if warnings:
        log(f"\n{len(warnings)} warning(s):")
        for item in warnings[: (None if args.verbose else 20)]:
            log(f"  {item}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    baseline = Baseline.load()
    results, _warnings = derive_all(baseline)
    failures = 0
    in_scope = 0
    skipped: List[str] = []
    for mod, plan in results:
        if mod.external_base:
            skipped.append(f"{mod.key} (base: {mod.external_base})")
            continue
        in_scope += 1
        try:
            outcome = ops.verify(plan, baseline, mod)
        except Exception as exc:  # noqa: BLE001
            log(f"ERROR  {mod.key}: {exc}")
            failures += 1
            continue
        flag = "ok  " if outcome.ok else "FAIL"
        log(f"{flag}  {outcome.summary():<48} {mod.key}")
        if not outcome.ok:
            failures += 1
            for path in outcome.mismatched[: (None if args.verbose else 5)]:
                log(f"        mismatch: {path}")
    log("")
    log(f"{in_scope - failures}/{in_scope} vanilla-based mods reproduce equivalently")
    if skipped:
        log(f"{len(skipped)} skipped - layered on another mod, not vanilla:")
        for item in skipped:
            log(f"  {item}")
    return 1 if failures else 0


def cmd_merge(args: argparse.Namespace) -> int:
    """The composition gate: does merging 1H + 2H reproduce the hand-built 2H-1H?"""

    baseline = Baseline.load()
    index = hash_index(baseline)
    pairs = combination_pairs(args.manager)
    if not pairs:
        log(f"No vanilla-based {args.manager} combination pairs found")
        return 1

    failures = 0
    for one_mod, two_mod, combined_mod in pairs:
        one, _w1 = ops.derive_mod(one_mod, baseline, hash_index=index)
        two, _w2 = ops.derive_mod(two_mod, baseline, hash_index=index)
        combined, _w3 = ops.derive_mod(combined_mod, baseline, hash_index=index)

        log("-" * 72)
        log(f"{combined_mod.name}")
        log(f"  1H {len(one.operations):>4} ops + 2H {len(two.operations):>4} ops "
             f"vs hand-built {len(combined.operations):>4} ops")

        report = ops.merge_report([one, two])
        overlapping = report["files_touched_by_multiple_plans"]
        log(f"  files touched by both singles: {len(overlapping)}")
        for path in overlapping[:6]:
            log(f"    {path}")

        if report["conflicts"]:
            log(f"  CONFLICTS ({len(report['conflicts'])}):")
            for item in report["conflicts"][:10]:
                log(f"    {item}")
            failures += 1
            continue

        merged = ops.merge([one, two], name="1H+2H")
        merged_keys = {op.conflict_key: op for op in merged.operations}
        hand_keys = {op.conflict_key: op for op in combined.operations}

        only_hand = sorted(set(hand_keys) - set(merged_keys))
        only_merged = sorted(set(merged_keys) - set(hand_keys))
        differing = sorted(
            key for key in set(hand_keys) & set(merged_keys)
            if ops._intent(hand_keys[key]) != ops._intent(merged_keys[key])
        )

        log(f"  only in hand-built : {len(only_hand)}")
        log(f"  only in merged     : {len(only_merged)}")
        log(f"  same target differs: {len(differing)}")
        for key in only_hand[: (None if args.verbose else 6)]:
            log(f"    HAND ONLY  {hand_keys[key].describe()}")
        for key in only_merged[: (None if args.verbose else 6)]:
            log(f"    MERGE ONLY {merged_keys[key].describe()}")
        for key in differing[: (None if args.verbose else 6)]:
            log(f"    DIFFERS    {hand_keys[key].describe()}")
            log(f"            vs {merged_keys[key].describe()}")

        if only_hand or only_merged or differing:
            failures += 1

    log("-" * 72)
    log(
        f"COMPOSITION GATE: PASS - {len(pairs)}/{len(pairs)} combined mods are reproducible by merging"
        if not failures
        else f"COMPOSITION GATE: {failures}/{len(pairs)} pair(s) differ; see above"
    )
    return 1 if failures else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="placement_studio", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inventory", help="list golden mods and the paths they overwrite")
    sub.add_parser("extract", help="extract the pinned vanilla baseline from the archives")
    sub.add_parser("derive", help="express each golden mod as an operation list")
    sub.add_parser("replay", help="replay plans and compare byte-for-byte")
    sub.add_parser("paac", help="report .paac length-prefix evidence (Tier C gate)")
    merge_parser = sub.add_parser("merge", help="composition gate: 1H + 2H vs hand-built 2H-1H")
    merge_parser.add_argument("--manager", default="DMM", help="manager layout to compare (default: DMM)")
    sub.add_parser("phase0", help="run every Phase 0 gate")

    sub.add_parser("roundtrip", help="Phase 1 gate: XML parses and re-emits byte-identically")
    bindings_parser = sub.add_parser("bindings", help="resolve vanilla placements into bindings")
    bindings_parser.add_argument("--model", default="", help="restrict to one model (1_phm, 2_phw)")
    uses_parser = sub.add_parser("uses", help="list the parts that route through a socket")
    uses_parser.add_argument("socket", help="socket name, e.g. Spine2_R_Socket")
    uses_parser.add_argument("--model", default="", help="restrict to one model")
    sub.add_parser("phase1", help="run every Phase 1 gate")
    sub.add_parser("reproduce", help="Phase 3 gate: editor reproduces golden socket edits")
    sub.add_parser("phase3", help="run every Phase 3 gate")
    charts_parser = sub.add_parser("charts", help="index action charts by referenced socket")
    charts_parser.add_argument("--model", default="", help="restrict to one model")
    sub.add_parser("retarget", help="Phase 4 gate: Tier C retarget mechanism")
    sub.add_parser("phase4", help="run every Phase 4 gate")
    package_parser = sub.add_parser("package", help="Phase 5 gate: regenerate manager variants")
    package_parser.add_argument("--group", default="1H", help="golden group to regenerate (default: 1H)")
    sub.add_parser("phase5", help="run every Phase 5 gate")
    clip_parser = sub.add_parser("clipping", help="Phase 4b gate: geometry and clipping metric")
    clip_parser.add_argument("--model", default="1_phm", help="character model")
    sub.add_parser("phase4b", help="run every Phase 4b gate")

    args = parser.parse_args(argv)
    for name, default in (("manager", "DMM"), ("model", ""), ("socket", ""), ("group", "1H")):
        if not hasattr(args, name):
            setattr(args, name, default)

    handlers = {
        "inventory": cmd_inventory,
        "extract": cmd_extract,
        "derive": cmd_derive,
        "replay": cmd_replay,
        "merge": cmd_merge,
        "paac": gates.cmd_paac,
        "phase0": gates.cmd_phase0,
        "roundtrip": gates.cmd_roundtrip,
        "bindings": gates.cmd_bindings,
        "uses": gates.cmd_uses,
        "phase1": gates.cmd_phase1,
        "reproduce": gates.cmd_reproduce,
        "phase3": gates.cmd_phase3,
        "charts": gates.cmd_charts,
        "retarget": gates.cmd_retarget,
        "phase4": gates.cmd_phase4,
        "clipping": gates.cmd_clipping,
        "phase4b": gates.cmd_phase4b,
        "package": gates.cmd_package,
        "phase5": gates.cmd_phase5,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
