"""One read-only command that flags what a game patch broke in CDMW, area by area.

Run it after every Crimson Desert update, from the repository root:

    .\\.venv\\Scripts\\python.exe tools\\patch_day_check.py

Patch-day checklist (the local register `docs/patch-regressions.md` holds the full
procedure and every past break; worktrees do not carry it):

1. Run this command. It records the build, compares the shipped metadata with the
   baseline, recounts the archive inventory in memory, runs the `real_game` sweep once
   and sorts every result into an area of the register.
2. Read the report (`.work/tests/<date>-patch-<build>/patch-day.md`). It exits 1 when
   anything is NEW: a failure the baseline does not list, a known failure whose reason
   changed, a skip it does not expect, a missing metadata file, or a changed inventory or
   static table name. Changed metadata files and the new build are reported, not failed.
3. For each new failure, decide: real break (the app's own path fails on this build)
   or stale test (the test asserts an old name or layout the app already handles).
   For an ItemInfo row break, run `tools/probe_iteminfo_layout.py --game <root>` first.
4. Walk the register's manual and gap entries; this command cannot check them.
5. Update the register: *Last OK* on what passed, new breaks with symptom, cause, fix
   and guard. When the new state is understood, refresh the baseline with
   `--write-baseline` and commit `tests/patch_day_baseline.json` with the fixes.
6. Tell the user what passed, what regressed and what was not re-checked. Corpus and
   source checks never prove in-game behaviour; game launches need the game slot.

Nothing here writes to the game folder or launches the game. The report goes under
`.work/tests/`, never inside the installation.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "tests" / "patch_day_baseline.json"
DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")
STEAM_APP_ID = "3321460"
META_FILES = (
    "meta/0.paver", "meta/0.papgt", "meta/0.pathc", "meta/0.papk",
    "dlc/dlc_01/meta/0.paver", "dlc/dlc_01/meta/0.papgt", "dlc/dlc_01/meta/0.pathc", "dlc/dlc_01/meta/0.paeid",
)
STATIC_TABLE_ROOT = "gamedata/binarystaticinfo__/bin/"
#: An extension count that moves by more than this share is reported (a patch adds a few files).
INVENTORY_TOLERANCE = 0.02

#: Test module (or `module::test-name prefix`) -> (area, register entries). Longest key wins.
#: Every `real_game` module must be listed; an unlisted one is reported so it gets an area.
AREAS: Mapping[str, tuple[str, str]] = {
    "test_native_archive_reader": ("Archives and indexes", "P-01"),
    "test_native_composition": ("Archives and indexes", "P-01 P-07"),
    "test_native_overlay_merge": ("Archives and indexes", "P-07"),
    "test_archive_overlay": ("Archives and indexes", "P-06 (retired overlays)"),
    "test_patch_day_format_guards::test_every_package_table_parses": ("Archives and indexes", "P-01"),
    "test_patch_day_format_guards::test_paver": ("Archives and indexes", "P-04 P-30"),
    "test_patch_day_format_guards::test_papgt": ("Archives and indexes", "P-06"),
    "test_patch_day_format_guards::test_texture_registry": ("Textures", "P-20"),
    "test_pathc_format": ("Textures", "P-20"),
    "test_item_icon_registry": ("Textures", "P-19"),
    "test_patch_day_format_guards::test_dds": ("Textures", "-"),
    "test_static_table_records": ("Gameplay tables", "P-08 P-31"),
    "test_patch_day_format_guards::test_static_table_decodes": ("Gameplay tables", "P-08 P-09 P-31"),
    "test_iteminfo_row": ("Gameplay tables", "P-12"),
    "test_iteminfo_patch_3732": ("Gameplay tables", "P-34"),
    "test_storeinfo_table": ("Gameplay tables", "P-10 P-13"),
    "test_multichangeinfo_table": ("Gameplay tables", "S-4"),
    "test_itemgroupinfo_table": ("Gameplay tables", "S-2"),
    "test_stringinfo_table": ("Gameplay tables", "S-2"),
    "test_new_item_service": ("Create New Item", "P-08 P-33"),
    "test_new_item_live_corpus": ("Create New Item", "P-13"),
    "test_item_model_family": ("Create New Item", "S-2"),
    "test_item_name_archive_search": ("Text and names", "P-15 S-2"),
    "test_paloc_format": ("Text and names", "P-15"),
    "test_translation_studio": ("Text and names", "P-15"),
    "test_translation_studio_loading": ("Text and names", "P-15"),
    "test_patch_day_format_guards::test_every_shipped_text_language": ("Text and names", "P-33"),
    "test_patch_rename_guards": ("Names, paths and registries", "P-09 P-17 P-18 P-19"),
    "test_pappt_format": ("Names, paths and registries", "P-26 S-1"),
    "test_patch_day_format_guards::test_character_meshes": ("Meshes and skeletons", "-"),
    "test_patch_day_format_guards::test_static_meshes": ("Meshes and skeletons", "P-05"),
    "test_patch_day_format_guards::test_skeletons": ("Meshes and skeletons", "-"),
    "test_real_external_sword_import": ("Meshes and skeletons", "-"),
    "test_patch_day_format_guards::test_hkx": ("Physics", "-"),
    "test_papr_format": ("Physics", "-"),
    "test_papr_block": ("Physics", "-"),
    "test_patch_day_format_guards::test_pac_xml": ("Materials, appearance, prefabs", "P-22"),
    "test_patch_day_format_guards::test_appearance": ("Materials, appearance, prefabs", "-"),
    "test_patch_day_format_guards::test_prefabs": ("Materials, appearance, prefabs", "P-21"),
    "test_prefab_array_edit": ("Materials, appearance, prefabs", "P-21"),
    "test_prefab_component_graft": ("Materials, appearance, prefabs", "P-21"),
    "test_projectile_package": ("Materials, appearance, prefabs", "-"),
    "test_patch_day_format_guards::test_effects": ("Effects and sound", "P-28"),
    "test_patch_day_format_guards::test_sound": ("Effects and sound", "-"),
    "test_action_chart_binary": ("Animation and Placement", "P-14"),
    "test_paa_motion_format": ("Animation and Placement", "-"),
    "test_paa_motion_encode": ("Animation and Placement", "-"),
    "test_posemodifier_xml": ("Animation and Placement", "P-32"),
    "test_placement_studio_back_move": ("Animation and Placement", "DMM output"),
    "test_placement_studio_carry_points": ("Animation and Placement", "-"),
    "test_game_folder_fence": ("Test harness", "-"),
    "test_qa_runner": ("Test harness", "-"),
    "test_release_packaging": ("Test harness", "-"),
    "journeys": ("App journeys (need the app running)", "-"),
}


# --------------------------------------------------------------------------- build and metadata


def file_version(path: Path) -> str:
    """The executable's FileVersion resource (Windows), or "" when it cannot be read."""

    if os.name != "nt" or not path.is_file():
        return ""
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return ""
    fixed = ctypes.c_void_p()
    length = ctypes.c_uint()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(fixed), ctypes.byref(length)):
        return ""
    words = (ctypes.c_uint32 * 4).from_address(fixed.value + 8)  # dwFileVersionMS/LS
    ms, ls = words[0], words[1]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def steam_build(game_root: Path) -> str:
    manifest = game_root.parent.parent / f"appmanifest_{STEAM_APP_ID}.acf"
    try:
        match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return match.group(1) if match else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def meta_fingerprints(game_root: Path) -> dict[str, dict]:
    rows = {}
    for relative in META_FILES:
        path = game_root / relative
        rows[relative] = {"size": path.stat().st_size, "sha256": sha256(path)} if path.is_file() else {"missing": True}
    return rows


# --------------------------------------------------------------------------- inventory


def static_table_stems(game_root: Path) -> list[str]:
    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    stems = set()
    for table in discover_pamt_files(game_root):
        for entry in parse_archive_pamt(table):
            path = str(entry.path).replace("\\", "/").lower()
            if path.startswith(STATIC_TABLE_ROOT) and path.endswith((".staticinfobody", ".staticinfoheader")):
                stems.add(path[len(STATIC_TABLE_ROOT):].rsplit(".", 1)[0])
    return sorted(stems)


def inventory_diff(current: Mapping[str, int], stored: Mapping[str, int]) -> dict:
    added = sorted(set(current) - set(stored))
    removed = sorted(set(stored) - set(current))
    moved = {}
    for extension in sorted(set(current) & set(stored)):
        before, after = stored[extension], current[extension]
        if before and abs(after - before) / before > INVENTORY_TOLERANCE:
            moved[extension] = [before, after]
    return {"added": added, "removed": removed, "moved": moved}


# --------------------------------------------------------------------------- sweep


def run_sweep(output: Path, basetemp: Path, extra: Sequence[str] = ()) -> tuple[int, Path]:
    junit = output / "real_game.xml"
    command = [sys.executable, "-m", "pytest", "tests", "-m", "real_game", "-o", "addopts=", "-p", "no:cacheprovider",
               "-rs", "-q", "--basetemp", str(basetemp), "--junitxml", str(junit), *extra]
    with (output / "real_game.txt").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    return result.returncode, junit


def read_junit(junit: Path) -> dict[str, dict]:
    """`module::Class::test` -> {"outcome", "message"} from a pytest JUnit file."""

    results = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        parts = classname.split(".")
        # tests.test_x.Class -> test_x::Class; tests.journeys.test_y -> journeys/test_y
        parts = parts[1:] if parts and parts[0] == "tests" else parts
        modules = [p for p in parts if p.startswith("test_") or p == "journeys"]
        module = "/".join(p for p in parts if p in modules)
        rest = [p for p in parts if p not in modules]
        key = "::".join([module, *rest, name])
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = (node.get("message") or node.text or "").strip().splitlines()[0][:240] if (
                    node.get("message") or node.text) else ""
                break
        results[key] = {"outcome": outcome, "message": message}
    return results


def area_of(key: str) -> tuple[str, str]:
    module, _, rest = key.partition("::")
    test = rest.rsplit("::", 1)[-1]
    best, found = -1, ("UNMAPPED", "-")
    for pattern, value in AREAS.items():
        name, _, prefix = pattern.partition("::")
        if module.split("/")[0] != name and module.split("/")[-1] != name:
            continue
        if prefix and not test.startswith(prefix):
            continue
        if len(pattern) > best:
            best, found = len(pattern), value
    return found


def skip_matches(key: str, pattern: str) -> bool:
    """An expected-skip key is one test, or a group when it ends in `/`, `::` or `[`."""

    return key == pattern or (pattern.endswith(("/", "::", "[")) and key.startswith(pattern))


def classify(results: Mapping[str, dict], baseline: Mapping[str, object]) -> list[dict]:
    known = baseline.get("known_failures", {})
    skips = baseline.get("expected_skips", {})
    rows = []
    for key, result in sorted(results.items()):
        area, entries = area_of(key)
        outcome = result["outcome"]
        if outcome == "passed":
            verdict = "FIXED (was a known failure)" if key in known else "ok"
        elif outcome in ("failed", "error"):
            if key not in known:
                verdict = "NEW FAILURE"
            elif "message" in known[key] and (failure_signature(known[key]["message"])
                                              != failure_signature(result["message"])):
                verdict = f"KNOWN FAILURE CHANGED ({known[key]['entry']}; was: {known[key]['message'][:120]})"
            else:
                verdict = f"known ({known[key]['entry']})"
        else:
            reason = next((r for pattern, r in skips.items() if skip_matches(key, pattern)), None)
            local = next((why for rule, why in ENVIRONMENT_SKIPS if rule.search(result["message"])), None)
            if reason:
                verdict = f"expected skip ({reason})"
            elif local:
                verdict = f"not run here ({local})"
            else:
                verdict = "UNEXPECTED SKIP"
        rows.append({"test": key, "area": area, "entries": entries, "outcome": outcome,
                     "verdict": verdict, "message": result["message"]})
    for key in sorted(set(known) - set(results)):
        rows.append({"test": key, "area": area_of(key)[0], "entries": known[key]["entry"], "outcome": "missing",
                     "verdict": "KNOWN FAILURE NO LONGER RUNS", "message": ""})
    return rows


#: Skips caused by this machine or checkout, not by the game: a missing local build or input.
#: They are not new, but the report lists them as unguarded on this run.
ENVIRONMENT_SKIPS = (
    (re.compile(r"native item composer", re.I), "build the native item composer to run it"),
    (re.compile(r"extracted vanilla motion tree", re.I), "needs the extracted motion tree"),
    (re.compile(r"CDMW_JOURNEY_BASE_PROFILE|no game profile", re.I), "needs a journey profile and the app"),
    (re.compile(r"external model", re.I), "needs the external test model"),
)

#: Verdicts that make the run fail: something the baseline does not explain.
NEW_VERDICTS = ("NEW FAILURE", "KNOWN FAILURE CHANGED", "UNEXPECTED SKIP", "KNOWN FAILURE NO LONGER RUNS")


def failure_signature(message: str) -> str:
    """A known failure's message with its numbers blanked: counts may drift, the reason may not."""

    return re.sub(r"\d[\d,._]*", "#", str(message or "")).strip()


def is_new(row: Mapping[str, str]) -> bool:
    return row["verdict"].startswith(NEW_VERDICTS) or row["area"] == "UNMAPPED"


# --------------------------------------------------------------------------- report


def render(report: Mapping[str, object]) -> str:
    lines = [f"# Patch-day check, {report['date']}", ""]
    build = report["build"]
    lines += [f"- Executable: {build['exe'] or 'unreadable'} (baseline {build['baseline_exe']})",
              f"- Steam build: {build['steam'] or 'unknown'} (baseline {build['baseline_steam']})", ""]
    changed = [k for k, v in report["meta"].items() if v.get("changed")]
    lines.append(f"- Changed metadata files: {', '.join(changed) if changed else 'none'}")
    inventory = report.get("inventory")
    if inventory:
        lines.append(f"- Inventory: added {inventory['added'] or 'none'}, removed {inventory['removed'] or 'none'}, "
                     f"moved over {INVENTORY_TOLERANCE:.0%}: {inventory['moved'] or 'none'}")
        tables = report["static_tables"]
        lines.append(f"- Static tables: added {tables['added'] or 'none'}, removed {tables['removed'] or 'none'}")
    lines.append("")
    rows = report.get("tests", [])
    if rows:
        lines += ["## Areas", "", "| Area | Tests | OK | New | Known failures | Expected skips | Not run here |",
                  "|---|---|---|---|---|---|---|"]
        areas: dict[str, Counter] = {}
        for row in rows:
            counter = areas.setdefault(row["area"], Counter())
            counter["tests"] += 1
            counter["new" if is_new(row) else row["verdict"].split(" ")[0]] += 1
        for area, c in sorted(areas.items()):
            verdict = f"**{c['new']}**" if c["new"] else "0"
            lines.append(f"| {area} | {c['tests']} | {c['ok'] + c['FIXED']} | {verdict} | {c['known']} | "
                         f"{c['expected']} | {c['not']} |")
        lines += ["", "## New since the baseline", ""]
        new = [row for row in rows if is_new(row) or row["verdict"].startswith("FIXED")]
        lines += [f"- {row['verdict']}: `{row['test']}` ({row['area']}; {row['entries']}) {row['message']}"
                  for row in new] or ["Nothing new."]
        lines += ["", "## Not run on this machine (unguarded this run)", ""]
        lines += [f"- `{row['test']}`: {row['verdict']}" for row in rows
                  if row["verdict"].startswith("not run here")] or ["None."]
        lines += ["", "## Known failures still failing", ""]
        lines += [f"- `{row['test']}`: {row['verdict']} {row['message']}" for row in rows
                  if row["verdict"].startswith("known")] or ["None."]
    lines += ["", "Not covered by this command: the register's manual and gap entries, any game launch, "
              "DMM's own support for the build. Source and corpus checks never prove in-game behaviour.", ""]
    return "\n".join(lines)


def load_baseline(path: Path = BASELINE_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_baseline(report: Mapping[str, object], previous: Mapping[str, object], path: Path = BASELINE_PATH) -> None:
    """Accept the current state: today's failures and skips become the known set (reasons kept)."""

    known_before = previous.get("known_failures", {})
    known = {} if report.get("tests") else dict(known_before)  # a --no-sweep run keeps the known set
    for row in report.get("tests", []):
        if row["outcome"] in ("failed", "error"):
            known[row["test"]] = {**known_before.get(row["test"], {"entry": "unclassified", "reason": row["message"]}),
                                  "message": row["message"]}
    baseline = dict(previous)
    baseline.update(
        exe=report["build"]["exe"], steam_build=report["build"]["steam"], recorded=report["date"],
        meta={k: {"size": v["size"], "sha256": v["sha256"]} for k, v in report["meta"].items() if "sha256" in v},
        static_tables=report.get("static_table_list", previous.get("static_tables", [])),
        inventory=report.get("inventory_counts", previous.get("inventory", {})),
        known_failures=known,
    )
    if report.get("tests"):
        skips = dict(previous.get("expected_skips", {}))
        for row in report["tests"]:
            if (row["outcome"] == "skipped" and not row.get("verdict", "").startswith("not run here")
                    and not any(skip_matches(row["test"], p) for p in skips)):
                skips[row["test"]] = row["message"] or "skipped"
        baseline["expected_skips"] = skips
    path.write_text(json.dumps(baseline, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, default=Path(os.environ.get("CDMW_GAME_ROOT") or DEFAULT_GAME_ROOT))
    parser.add_argument("--out", type=Path, help="report folder (default .work/tests/<date>-patch-<build>)")
    parser.add_argument("--no-sweep", action="store_true", help="only the fast metadata and inventory checks")
    parser.add_argument("--write-baseline", action="store_true",
                        help="accept this run as the new baseline (after the register is updated)")
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments after --, e.g. -k paver")
    args = parser.parse_args(argv)

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    game = args.game
    if not (game / "bin64" / "CrimsonDesert.exe").is_file():
        print(f"No Crimson Desert installation at {game}", file=sys.stderr)
        return 2
    baseline = load_baseline()
    date = _dt.date.today().isoformat()
    exe = file_version(game / "bin64" / "CrimsonDesert.exe")
    build_label = exe.rsplit(".", 1)[-1] if exe else "unknown"
    output = args.out or REPO_ROOT / ".work" / "tests" / f"{date}-patch-{build_label}"
    if os.path.normcase(str(output.resolve())).startswith(os.path.normcase(str(game.resolve()))):
        print("The report folder must be outside the game installation.", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)

    report: dict = {"date": date, "game": str(game)}
    report["build"] = {"exe": exe, "steam": steam_build(game), "baseline_exe": baseline.get("exe", "none"),
                       "baseline_steam": baseline.get("steam_build", "none")}
    meta = meta_fingerprints(game)
    for relative, row in meta.items():
        before = baseline.get("meta", {}).get(relative)
        row["changed"] = bool(before) and before.get("sha256") != row.get("sha256")
    report["meta"] = meta
    print(f"Build {exe} (Steam {report['build']['steam']}); baseline {report['build']['baseline_exe']}")

    from tools.report_format_decode_progress import load_inventory, scan_inventory

    # Compare with the baseline's own recount; the tracked inventory file is only a fallback,
    # since it is refreshed with the capability manifest, not on every patch.
    extensions = scan_inventory(game)["extensions"]
    report["inventory_counts"] = extensions
    report["inventory"] = inventory_diff(extensions, baseline.get("inventory") or load_inventory())
    stems = static_table_stems(game)
    report["static_table_list"] = stems
    stored = baseline.get("static_tables", [])
    report["static_tables"] = {"added": sorted(set(stems) - set(stored)) if stored else [],
                               "removed": sorted(set(stored) - set(stems)) if stored else []}

    if not args.no_sweep:
        print("Running the real_game sweep (read-only; several minutes)...")
        code, junit = run_sweep(output, Path(os.environ.get("TEMP", output)) / f"cdmw-patch-sweep-{build_label}",
                                args.pytest_args)
        report["pytest_exit"] = code
        report["tests"] = classify(read_junit(junit), baseline) if junit.is_file() else []

    (output / "patch-day.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    text = render(report)
    (output / "patch-day.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Report: {output / 'patch-day.md'}")

    if args.write_baseline:
        write_baseline(report, baseline)
        print(f"Baseline written: {BASELINE_PATH}")
        return 0
    new = [row for row in report.get("tests", []) if is_new(row)]
    # A patch changes the meta files every time; that is reported, not a failure. A missing one is.
    flagged = (new or any(v.get("missing") for v in meta.values())
               or any(report["inventory"].values()) or any(report["static_tables"].values())
               or (not args.no_sweep and not report.get("tests")))
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
