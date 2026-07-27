"""The clipping gate: is a placement measurably better or worse than vanilla?

Split from `gates.py` to keep both under the repository's 1,000-line owner ceiling. This is the
one gate that reasons about geometry rather than bytes, so it carries its own mesh imports.
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from tools.placement_studio.cli_support import log as _log
from tools.placement_studio.corpus import Baseline


def cmd_clipping(args: argparse.Namespace) -> int:
    """Phase 4b gate: geometry is loaded in process and the clipping metric responds to edits.

    The absolute penetration number is *not* a verdict. A sheathed sword on the hip genuinely
    intersects a bare body proxy — vanilla measures ~40% — so what matters is the change against
    vanilla. This gate proves the metric is responsive and correctly signed:

      1. geometry decodes in process, with no helper subprocess,
      2. a weapon held in the hand shows no penetration (the sanity anchor),
      3. pushing the socket into the body increases penetration,
      4. pulling it away from the body decreases it,
      5. the sheath tracks the weapon it cases.
    """

    from tools.placement_studio.editing import session_from_baseline
    from tools.placement_studio.meshes import (
        MIN_BODY_COVERAGE,
        body_coverage,
        body_mesh_paths,
        load_mesh,
        measure_clipping,
        merge,
        weapon_mesh_path,
    )
    from tools.placement_studio.model import Vec3
    from tools.placement_studio.session import PlacementSession

    baseline = Baseline.load()
    model = args.model or "1_phm"
    session = PlacementSession.from_baseline(baseline, model)
    if not session.weapons():
        _log(f"No weapon socket files for {model}")
        return 1
    session.select_weapon(session.weapons()[0])

    body_paths = body_mesh_paths(baseline, model)
    if not body_paths:
        _log(f"No body proxy meshes in the baseline for {model}. Run: extract")
        return 1
    body = merge([load_mesh(baseline.read(p), source_path=p) for p in body_paths], name="body")
    coverage = body_coverage(body, session.hierarchy)
    _log(f"body proxy: {len(body_paths)} mesh(es), {body.vertex_count:,} verts, "
         f"{body.triangle_count:,} tris, {coverage:.0%} of rig height")

    # Every clipping number below is measured against this proxy, so a proxy that is not a body
    # makes all of them meaningless while still looking like a clean pass. A baseline once
    # pinned a 23 KB accessory here, covering 10% of the rig: it rendered as a scrap near one
    # elbow and reported "no vertices inside the body" for every placement.
    if coverage < MIN_BODY_COVERAGE:
        _log(f"  FAIL: proxy covers only {coverage:.0%} of the rig "
             f"(need {MIN_BODY_COVERAGE:.0%}) — {', '.join(p.rsplit('/', 1)[-1] for p in body_paths)}")
        _log("  Re-extract the baseline: placement_studio extract")
        return 1

    weapon_path = weapon_mesh_path(session.weapon.weapon_id, model)
    if weapon_path not in baseline:
        _log(f"Weapon mesh not in baseline: {weapon_path}")
        return 1
    weapon = load_mesh(baseline.read(weapon_path), source_path=weapon_path)
    _log(f"weapon: {session.weapon.weapon_id} -> {weapon.vertex_count} verts, "
         f"{weapon.triangle_count} tris  (decoded in process, no helper)")
    _log("")

    binding = next(
        (b for b in session.bindings() if b.part_name == "CD_MainWeapon_Sword_R"), None
    )
    if binding is None:
        _log("No CD_MainWeapon_Sword_R row for this model")
        return 1

    def penetration(translation_delta: Optional[Vec3] = None) -> float:
        """Stowed penetration ratio, optionally after nudging the stowed body socket."""

        active = session
        if translation_delta is not None:
            edits = session_from_baseline(baseline)
            socket_file = session.placed(binding.part.in_socket).socket.source_file
            current = edits.socket(socket_file, binding.part.in_socket)
            edits.set_translation(
                socket_file,
                binding.part.in_socket,
                current.translation.offset(
                    translation_delta.x, translation_delta.y, translation_delta.z
                ),
            )
            from tools.placement_studio.resolver import PlacementResolver

            overrides = edits.preview()
            resolver = PlacementResolver()
            for path in baseline.paths():
                from tools.placement_studio.documents import is_descriptor_file, is_socket_file

                if is_socket_file(path) or is_descriptor_file(path):
                    resolver.add_files({path: overrides.get(path, baseline.read(path))})
            active = PlacementSession(model, session.hierarchy, resolver)
            for candidate in active.weapons():
                if candidate.weapon_id == session.weapon.weapon_id:
                    active.select_weapon(candidate)
                    break
        matrix = active.attachment_matrix(
            binding.part.in_socket, binding.part.in_child_socket
        )
        if matrix is None:
            return -1.0
        return measure_clipping(weapon.transformed(matrix, name=weapon.name), body).ratio

    failures = 0

    # 2. A held weapon overlaps the bare body proxy a little by design: the fist sits against
    # the hip, so the grip region is inside a mesh that has no armour on it. What matters is
    # that it is *small* — the blade must not be buried.
    held_matrix = session.attachment_matrix(
        binding.part.out_socket, binding.part.out_child_socket
    )
    held = measure_clipping(weapon.transformed(held_matrix, name=weapon.name), body)
    _log(f"held   : {held.summary()}")
    if held.ratio > 0.15:
        _log("   FAIL: a held weapon should only graze the body, not sit inside it")
        failures += 1

    baseline_ratio = penetration()
    _log(f"stowed : {baseline_ratio * 100:.1f}% of weapon vertices inside the body (vanilla)")
    _log("   (a sheathed sword rests against a bare body proxy, so a little overlap is")
    _log("    expected — this is the reference, not a verdict)")
    _log("")

    # 3 & 4. The metric must respond, and in the right direction. Direction is *not* assumed:
    # socket translation is in parent-bone space, so a local -X is not "towards the body" — it
    # depends entirely on how that bone is oriented.
    _log("sweeping the stowed socket along its local X (bone space, not world space):")
    sweep: List[tuple[float, float]] = []
    for offset in (-0.20, -0.10, 0.0, 0.10, 0.20):
        ratio = baseline_ratio if offset == 0.0 else penetration(Vec3(offset, 0.0, 0.0))
        sweep.append((offset, ratio))
        _log(f"   {offset:+.2f}: {ratio * 100:5.1f}%")

    ratios = [ratio for _offset, ratio in sweep]
    if max(ratios) - min(ratios) < 0.05:
        _log("   FAIL: the metric barely responded to a 0.40 sweep")
        failures += 1
    if min(ratios) > 1e-9:
        _log("   FAIL: some direction should clear the body entirely")
        failures += 1
    if max(ratios) <= baseline_ratio:
        _log("   FAIL: some direction should push the weapon further into the body")
        failures += 1
    # The shipped placement must sit nearer the clear end than the buried end: vanilla is a
    # resting position, not a worst case. This is what the previous "peaks at vanilla"
    # assertion got backwards, and it only passed because the child socket was applied
    # forwards instead of inverted, pointing a held blade behind the character.
    if baseline_ratio > (min(ratios) + max(ratios)) / 2.0:
        _log("   FAIL: vanilla is closer to fully buried than to clear")
        failures += 1
    if not failures:
        _log(
            f"   responsive and directional: {min(ratios) * 100:.1f}% .. {max(ratios) * 100:.1f}%, "
            f"vanilla {baseline_ratio * 100:.1f}% near the clear end"
        )
    _log("")

    # 5. the sheath must follow the weapon it cases.
    case = next(
        (b for b in session.bindings() if b.part_name == binding.part.weapon_case_part), None
    )
    if case is not None:
        case_matrix = session.attachment_matrix(
            case.part.in_socket, case.part.in_child_socket
        )
        case_report = measure_clipping(weapon.transformed(case_matrix, name="case"), body)
        same = abs(case_report.ratio - baseline_ratio) < 1e-9
        _log(f"case row {case.part_name}: {'tracks the weapon' if same else 'DIVERGES'}")
        if not same:
            failures += 1

    _log("")
    if failures:
        _log(f"FAIL: {failures} check(s) failed")
        return 1
    _log("Clipping metric responds correctly; geometry decodes with no helper process")
    return 0
