"""Per-vertex benchmark for Fit to body against hand-reshaped female armor.

The Female Armor Fit mod (Nexus 837) ships male armor PACs reshaped for women
under the original's name with ``zz_`` in place of ``cd_``, with the same parts,
vertices and faces: the author moved vertices only, so every vertex has a
target. This fits each ``cd_`` original onto a female body with the harness
(:mod:`tools.refit_reference_harness`) and measures how far each fitted vertex
lands from its ``zz_`` target, beside how far the unfitted original is
(``unfit``). Errors are summarised per part, per armor category and per body
band (by height on the driver, with arms apart).

The mod's meshes are third-party content: point ``--mod-package`` at its
extracted package folder (the one holding ``0.pamt``); nothing of it is copied
or written out beyond the scores. Archive reads are read only. Development
evidence, not proof of in-game appearance.

Example::

    python tools/refit_reference_benchmark.py --mod-package "<mod>/Female Armor Fit/0036" \\
        --game-root "<Crimson Desert>" --sample 80 --method reference --output out
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_parser import parse_pac
from tools import refit_reference_harness as harness

DRIVER = "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pac"
# Height bands as shares of the driver's height, feet up; arms are apart.
BANDS = ((0.0, .28, "legs"), (.28, .47, "hips"), (.47, .60, "waist"), (.60, .73, "chest"),
         (.73, .84, "shoulders"), (.84, 1.01, "head"))


def pairs(package: Path, dependencies) -> list[tuple[str, object]]:
    """(original archive path, reshaped mod entry) for every ``zz_`` PAC with a ``cd_`` original."""
    found = []
    for entry in parse_archive_pamt(package / "0.pamt"):
        path = PurePosixPath(entry.path)
        if entry.extension != ".pac" or not path.name.startswith("zz_"):
            continue
        original = str(path.with_name("cd_" + path.name[3:]))
        if worn(original) and dependencies.entry_for_path(original) is not None:
            found.append((original, entry))
    return sorted(found, key=lambda item: item[0])


SLOTS = ("cloak", "jacket", "vest", "necklace", "belt", "hand", "foot", "hel", "sho", "acc", "ub", "lb")


def category(path: str) -> str:
    """The armor slot, from the name's tokens: boss outfits share one folder for every slot."""
    tokens = PurePosixPath(path).stem.lower().split("_")
    return next((slot for slot in SLOTS if slot in tokens), "other")


def worn(path: str) -> bool:
    """Gear a character wears; mounts and loose props are not fitted to a body."""
    return path.startswith(("character/model/1_pc/", "character/model/2_mon/cd_m0001_00_twofeet/"))


def sample(rows, count: int, seed: int):
    """An even draw across categories, so hands and feet do not crowd out tops."""
    if not count or count >= len(rows):
        return rows
    groups = defaultdict(list)
    for row in rows:
        groups[category(row[0])].append(row)
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    picked, index = [], 0
    while len(picked) < count:
        for name in sorted(groups):
            if index < len(groups[name]) and len(picked) < count:
                picked.append(groups[name][index])
        index += 1
    return sorted(picked, key=lambda item: item[0])


def band_labels(points: np.ndarray, driver: np.ndarray) -> np.ndarray:
    extent = driver.max(0) - driver.min(0)
    up = int(np.argmax(extent))
    side = [axis for axis in range(3) if axis != up]
    height = (points[:, up] - driver[:, up].min()) / extent[up]
    labels = np.empty(len(points), dtype=object)
    for low, high, name in BANDS:
        labels[(height >= low) & (height < high)] = name
    labels[height >= BANDS[-1][1]] = "head"
    labels[height < 0] = "legs"
    # Arms: beside the torso, above the hips.
    centre = np.median(driver[:, side], axis=0)
    torso = driver[(np.abs(((driver[:, up] - driver[:, up].min()) / extent[up]) - .62) < .08)]
    half = np.percentile(np.abs(torso[:, side[0]] - centre[0]), 90) if len(torso) else extent[side[0]] / 4
    lateral = np.abs(points[:, side[0]] - centre[0])
    labels[(lateral > half * 1.15) & (height > .5) & (height < .84)] = "arms"
    return labels


def score(original: str, mod_entry, method: str, config: dict, dependencies) -> dict:
    inputs = harness._archive_inputs({**config, "outfit": original}, dependencies)
    target = parse_pac(read_archive_entry_data(mod_entry)[0], mod_entry.path)
    row = {"outfit": original, "category": category(original), "reference": inputs["provenance"]["reference"],
           "reason": inputs["reason"]}
    if method == "unfit":
        fitted_parts = inputs["outfit"].submeshes
        body_parts = inputs["body"].submeshes
        row["status"] = "ok"
    else:
        if method == "reference" and inputs["reference"] is None:
            row.update(status="no reference", error=inputs["reason"])
            return row
        run = harness.fit(inputs, {**config, "outfit": original}, method)
        row["status"], row["error"], row["seconds"] = run["status"], run["error"], run["seconds"]
        if run["status"] != "ok":
            return row
        n = run["body_count"]
        fitted_parts = run["fitted"].submeshes[n:]
        body_parts = run["fitted"].submeshes[:n]
    body, body_faces = harness._joined(body_parts)
    surface = harness._Surface(body, body_faces)
    if len(fitted_parts) != len(target.submeshes):
        row.update(status="part mismatch")
        return row
    errors, unfit, labels, looser, offsets = [], [], [], [], []
    for fitted_part, target_part, source_part in zip(fitted_parts, target.submeshes, inputs["outfit"].submeshes):
        if len(fitted_part.vertices) != len(target_part.vertices):
            row.update(status="vertex mismatch")
            return row
        goal = np.asarray(target_part.vertices, float)
        fitted = np.asarray(fitted_part.vertices, float)
        errors.append(np.linalg.norm(fitted - goal, axis=1))
        offsets.append(fitted - goal)
        # How much further from the skin than the author's shape (positive: looser).
        looser.append(harness._signed_distance(surface, fitted) - harness._signed_distance(surface, goal))
        unfit.append(np.linalg.norm(np.asarray(source_part.vertices, float) - goal, axis=1))
        labels.append(band_labels(goal, body))
    error, base, label = np.concatenate(errors) * 1000, np.concatenate(unfit) * 1000, np.concatenate(labels)
    offset = np.concatenate(looser) * 1000
    finite = np.isfinite(offset)
    # Where the fit lands beside the author's shape, per axis (median, mm): a
    # shared direction is a systematic bias, not scatter.
    bias = np.concatenate(offsets) * 1000
    row.update(vertices=len(error), median_mm=float(np.median(error)), p95_mm=float(np.percentile(error, 95)),
               max_mm=float(error.max()), unfit_median_mm=float(np.median(base)),
               unfit_p95_mm=float(np.percentile(base, 95)),
               looser_median_mm=float(np.median(offset[finite])) if finite.any() else 0.0,
               bias_mm=[float(value) for value in np.median(bias, axis=0)],
               bands={name: {"vertices": int((label == name).sum()), "median_mm": float(np.median(error[label == name])),
                             "bias_mm": [float(value) for value in np.median(bias[label == name], axis=0)],
                             "unfit_median_mm": float(np.median(base[label == name])),
                             "looser_median_mm": float(np.median(offset[(label == name) & finite]))
                             if ((label == name) & finite).any() else 0.0}
                      for name in sorted(set(label)) if (label == name).sum() >= 20})
    return row


def memoise_skeleton_resolution() -> None:
    """Resolve each PAC's skeleton and descriptor once per run.

    Every row resolves the same driver again, and each resolution scans the
    whole archive index; the archive does not change during a run.
    """
    from cdmw.core import archive_mesh_appearance, skeleton_resolver

    for name in ("resolve_skeleton_for_model", "resolve_skeleton_descriptor_for_model"):
        function, results = getattr(skeleton_resolver, name), {}

        def memoised(model_entry, *args, _function=function, _results=results, **kwargs):
            authored = kwargs.get("authored_descriptor")
            key = (str(model_entry.path), str(getattr(authored, "path", "")), kwargs.get("read_entry_data") is None)
            if key not in _results:
                _results[key] = _function(model_entry, *args, **kwargs)
            return _results[key]

        for module in (skeleton_resolver, archive_mesh_appearance):
            if hasattr(module, name):
                setattr(module, name, memoised)


def summarise(rows: list[dict]) -> dict:
    scored = [row for row in rows if "median_mm" in row]
    summary = {"parts": len(rows), "scored": len(scored),
               "failed": {row["outfit"]: row.get("status") for row in rows if "median_mm" not in row}}
    if not scored:
        return summary
    summary["median_of_part_medians_mm"] = float(np.median([row["median_mm"] for row in scored]))
    summary["median_of_part_p95_mm"] = float(np.median([row["p95_mm"] for row in scored]))
    summary["unfit_median_of_part_medians_mm"] = float(np.median([row["unfit_median_mm"] for row in scored]))
    summary["parts_worse_than_unfit"] = sum(row["median_mm"] > row["unfit_median_mm"] for row in scored)
    by_category, by_band = defaultdict(list), defaultdict(list)
    for row in scored:
        by_category[row["category"]].append(row)
        for name, band in row["bands"].items():
            by_band[name].append(band)
    summary["categories"] = {name: {"parts": len(items),
                                    "median_mm": float(np.median([r["median_mm"] for r in items])),
                                    "unfit_median_mm": float(np.median([r["unfit_median_mm"] for r in items]))}
                             for name, items in sorted(by_category.items())}
    summary["bands"] = {name: {"parts": len(items), "median_mm": float(np.median([b["median_mm"] for b in items])),
                               "bias_mm": [float(value) for value in np.median([b["bias_mm"] for b in items], axis=0)],
                               "unfit_median_mm": float(np.median([b["unfit_median_mm"] for b in items])),
                               "looser_median_mm": float(np.median([b["looser_median_mm"] for b in items]))}
                        for name, items in sorted(by_band.items())}
    summary["looser_median_mm"] = float(np.median([row["looser_median_mm"] for row in scored]))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mod-package", type=Path, required=True, help="Extracted mod package folder holding 0.pamt")
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--driver", default=DRIVER, help="Female body archive path to fit onto")
    parser.add_argument("--method", nargs="+", choices=("reference", "bound", "unfit"), default=["reference"])
    parser.add_argument("--sample", type=int, default=0, help="Parts to draw evenly across categories (0: all)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--filter", default="", help="Only originals whose path contains this text")
    parser.add_argument("--slots", default="", help="Comma-separated slots to keep (ub,vest,jacket,...)")
    parser.add_argument("--skin-pull", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    harness._require_dev_dependencies(False, True)
    memoise_skeleton_resolution()
    dependencies = harness._archive_index(args.game_root)
    slots = {slot for slot in args.slots.split(",") if slot}
    rows = [row for row in pairs(args.mod_package, dependencies)
            if args.filter in row[0] and (not slots or category(row[0]) in slots)]
    rows = sample(rows, args.sample, args.seed)
    config = {"body": args.driver, "clearance": 0.1, "tightness": 100.0, "skin_pull": args.skin_pull}
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"driver": args.driver, "skin_pull": args.skin_pull, "methods": {}}
    for method in args.method:
        results, started = [], time.perf_counter()
        for original, entry in rows:
            try:
                row = score(original, entry, method, config, dependencies)
            except Exception as error:  # noqa: BLE001 - one bad part must not end a long run.
                row = {"outfit": original, "category": category(original), "status": "error", "error": str(error)}
            results.append(row)
            cells = (f"{row['median_mm']:6.1f} med {row['p95_mm']:6.1f} p95 (unfit {row['unfit_median_mm']:5.1f}) "
                     f"looser {row['looser_median_mm']:+5.1f}"
                     if "median_mm" in row else f"{row.get('status', '')}: {row.get('error') or ''}")
            print(f"{method:9} {PurePosixPath(original).name[:44]:<44} {cells}", flush=True)
        report["methods"][method] = {"summary": summarise(results), "seconds": time.perf_counter() - started,
                                     "parts": results}
        print(json.dumps({method: {k: v for k, v in report["methods"][method]["summary"].items() if k != "failed"}},
                         indent=1), flush=True)
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
