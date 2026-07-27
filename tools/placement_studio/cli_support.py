"""Helpers shared by `cli.py` and `gates.py`.

Extracted so both stay under the repository's 1,000-line owner ceiling, and so the corpus
helpers have one home rather than being duplicated across command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from tools.placement_studio import ops
from tools.placement_studio.corpus import Baseline, GoldenMod, discover_golden_mods

# The 2H hip retarget the golden corpus performs, used by the Phase 4 gate.
HIP_RETARGET: Tuple[str, str] = ("Spine2_B_SubWeapon_Socket", "Pelvis_L_SubWeapon_Socket")


def log(message: str) -> None:
    print(message, flush=True)


def hash_index(baseline: Baseline) -> Dict[str, str]:
    """sha256 -> vanilla path, so substitutions can be proven to reuse existing payloads."""

    index: Dict[str, str] = {}
    for path in baseline.paths():
        record = baseline.record(path)
        if record is not None:
            index.setdefault(record.sha256, path)
    return index


def derive_all(baseline: Baseline) -> Tuple[List[Tuple[GoldenMod, ops.Plan]], List[str]]:
    index = hash_index(baseline)
    results: List[Tuple[GoldenMod, ops.Plan]] = []
    warnings: List[str] = []
    for mod in discover_golden_mods():
        plan, mod_warnings = ops.derive_mod(mod, baseline, hash_index=index)
        results.append((mod, plan))
        warnings.extend(f"{mod.key}: {item}" for item in mod_warnings)
    return results, warnings


def vanilla_based(manager: str) -> List[GoldenMod]:
    return [
        mod
        for mod in discover_golden_mods()
        if mod.manager == manager and not mod.external_base
    ]


def combination_pairs(manager: str) -> List[Tuple[GoldenMod, GoldenMod, GoldenMod]]:
    """Pair each hand-built combined mod with the two singles it was merged from.

    Combined names follow "2H Sword Hip + <1H variant> Carry and Draw Animations - <mgr>", so
    the 1H half is recoverable from the name rather than guessed by position.
    """

    by_group: Dict[str, List[GoldenMod]] = {}
    for mod in vanilla_based(manager):
        by_group.setdefault(mod.group, []).append(mod)

    pairs: List[Tuple[GoldenMod, GoldenMod, GoldenMod]] = []
    for combined in by_group.get("2H-1H", []):
        head, _sep, _tail = combined.name.partition(" + ")
        two = next((m for m in by_group.get("2H", []) if m.name.startswith(head)), None)
        one_name = combined.name.split(" + ", 1)[1] if " + " in combined.name else ""
        one = next(
            (m for m in by_group.get("1H", []) if one_name.startswith(m.name.rsplit(" - ", 1)[0])),
            None,
        )
        if one and two:
            pairs.append((one, two, combined))
    return pairs


def discover_body_meshes(models: Sequence[str], *, per_slot: int = 1) -> List[str]:
    """Pick one body armour mesh per slot as a clipping proxy.

    The character has no single body mesh — it is composed of armour pieces — so the upper and
    lower body slots stand in for it.

    Two traps here, and the codebase has been in both:

    * **Picking by size alone selects an accessory, not a small body.** "Smallest per slot"
      chose `cd_phm_00_ub_acc_00_0377.pac` (23 KB, 623 triangles, spanning 0.23 of a 1.79-tall
      rig). It renders as a scrap near one elbow, so the body looks like it failed to load and
      every clipping measurement reads "no vertices inside the body".
    * **The largest is a 3.8 MB show piece**, which is what that size rule was avoiding.

    So restrict to canonically named base armour — which drops `_acc` accessories, `_sub`
    sub-pieces, belts and character variants — then take the *median* sized one. Measured
    against the four hand-picked meshes this replaced, that gives equal or better body coverage
    for about a third of the triangles (Damian's proxy: 16,232 -> 3,867).
    """

    from tools.placement_studio.corpus import archive_entry_sizes
    from tools.placement_studio.meshes import BODY_SLOTS, is_base_armour_mesh

    sizes = archive_entry_sizes(".pac", contains="/armor/")
    wanted: List[str] = []
    for model in [m for m in models if m]:
        for slot in BODY_SLOTS:
            in_slot = [p for p in sizes if f"/{model}/armor/{slot}/" in p]
            matching = [p for p in in_slot if is_base_armour_mesh(p, model, slot)]
            if not matching:
                # Unknown naming for this model: fall back to the whole slot rather than
                # shipping no proxy at all, still avoiding both size extremes.
                matching = in_slot
            matching.sort(key=lambda path: (sizes[path], path))
            middle = len(matching) // 2
            wanted.extend(matching[middle : middle + per_slot] or matching[:per_slot])
    return sorted(set(wanted))


def socket_from_raw(raw: str):
    """Recover a Socket from a captured `<Socket .../>` element."""

    import re

    from tools.placement_studio.model import Quat, Socket, Vec3

    attributes = dict(re.findall(r'\b([A-Za-z_][\w.\-]*)="([^"]*)"', raw))
    return Socket(
        name=attributes.get("Name", ""),
        parent_bone=attributes.get("Parent", ""),
        rotation=Quat.parse(attributes["Rotation"]) if attributes.get("Rotation") else Quat(),
        translation=Vec3.parse(attributes["Translation"]) if attributes.get("Translation") else Vec3(),
    )


def chart_index(baseline: Baseline):
    """Index every action chart in the pinned baseline by the sockets it references."""

    from tools.placement_studio.animation import ChartIndex, index_chart, is_actionchart

    index = ChartIndex()
    for path in baseline.paths():
        if is_actionchart(path):
            index.add(index_chart(path, baseline.read(path)))
    return index
