from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.preview_comparison import compare_preview_images, write_preview_comparison_report
from cdmw.rendering.ingame_capture import (
    DEFAULT_CRIMSON_GAME_ROOT,
    capture_crimson_ingame_screenshot,
    find_crimson_game_window,
)
from cdmw.rendering.test_run_sword_tuning import (
    TEST_RUN_SWORD_MINIMUM_VARIANTS,
    TEST_RUN_SWORD_OUTPUT_ROOT,
    build_test_run_sword_session_status,
    create_test_run_sword_run_artifacts,
    sync_test_run_sword_variant_to_dmm,
    write_test_run_sword_session_plan,
    write_test_run_sword_session_status,
)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _update_run_manifest(run_manifest_path: Path, **updates: object) -> None:
    try:
        data = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    artifacts = data.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        for key in ("preview_screenshot", "in_game_screenshot", "in_game_capture_report", "comparison_report"):
            value = updates.get(key)
            if value:
                artifacts[key] = str(value)
    notes = updates.get("notes")
    if notes:
        data["notes"] = str(notes)
    run_manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _ensure_run_manifest(run_dir: Path) -> None:
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        return
    match = re.fullmatch(r"run_(\d+)", run_dir.name)
    if not match:
        return
    create_test_run_sword_run_artifacts(run_dir.parent, run_index=int(match.group(1)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and record TestRunSword material tuning run artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Create the 20-run folder/session manifest skeleton.")
    plan.add_argument("--output-dir", default=TEST_RUN_SWORD_OUTPUT_ROOT)
    plan.add_argument("--variants", type=int, default=TEST_RUN_SWORD_MINIMUM_VARIANTS)
    plan.add_argument("--source-mod-dir", default="")
    plan.add_argument("--dmm-mod-dir", default="")

    run = subparsers.add_parser("run-folder", help="Create or refresh one numbered run folder.")
    run.add_argument("--output-dir", default=TEST_RUN_SWORD_OUTPUT_ROOT)
    run.add_argument("--run-index", type=int, required=True)
    run.add_argument("--notes", default="")
    run.add_argument("--source-mod-dir", default="")
    run.add_argument("--dmm-mod-dir", default="")

    sync = subparsers.add_parser("sync", help="Dry-run or apply loose TestRunSword copy into the DMM mod folder.")
    sync.add_argument("--run-dir", required=True)
    sync.add_argument("--source-mod-dir", default="")
    sync.add_argument("--dmm-mod-dir", default="")
    sync.add_argument("--apply", action="store_true", help="Actually copy files. Default is dry-run.")

    compare = subparsers.add_parser("compare", help="Record preview/in-game screenshot comparison for a run folder.")
    compare.add_argument("--run-dir", required=True)
    compare.add_argument("--preview", required=True)
    compare.add_argument("--in-game", required=True)
    compare.add_argument("--item-icon", default="")
    compare.add_argument("--preview-roi", default="", help="Optional preview ROI as x,y,width,height.")
    compare.add_argument("--in-game-roi", default="", help="Optional in-game ROI as x,y,width,height.")
    compare.add_argument("--item-icon-roi", default="", help="Optional item icon ROI as x,y,width,height.")
    compare.add_argument("--notes", default="")

    capture = subparsers.add_parser("capture-ingame", help="Capture an in-game screenshot into a run folder.")
    capture.add_argument("--run-dir", required=True)
    capture.add_argument("--game-root", default=DEFAULT_CRIMSON_GAME_ROOT)
    capture.add_argument("--game-exe", default="")
    capture.add_argument("--launch-game", action="store_true", help="Explicitly launch the game if no window is running.")
    capture.add_argument("--press-e", action="store_true", help="Send E to the game window before capture.")
    capture.add_argument("--wait-for-window", type=float, default=45.0)
    capture.add_argument("--wait-after-e", type=float, default=2.0)
    capture.add_argument("--out", default="")
    capture.add_argument(
        "--auxiliary",
        action="store_true",
        help="Write a non-canonical capture without replacing the run manifest screenshot/report artifacts.",
    )
    capture.add_argument("--notes", default="")

    status = subparsers.add_parser("game-status", help="Report whether a Crimson Desert game window is visible.")

    status_report = subparsers.add_parser("status-report", help="Audit TestRunSword loop artifacts and next actions.")
    status_report.add_argument("--output-dir", default=TEST_RUN_SWORD_OUTPUT_ROOT)
    status_report.add_argument("--variants", type=int, default=TEST_RUN_SWORD_MINIMUM_VARIANTS)
    status_report.add_argument("--out", default="")

    args = parser.parse_args(argv)
    if args.command == "plan":
        kwargs = {}
        if args.source_mod_dir:
            kwargs["source_mod_dir"] = args.source_mod_dir
        if args.dmm_mod_dir:
            kwargs["dmm_mod_dir"] = args.dmm_mod_dir
        session_path = write_test_run_sword_session_plan(args.output_dir, variants=args.variants, **kwargs)
        _print_json({"session_manifest": str(session_path), "variant_count": max(TEST_RUN_SWORD_MINIMUM_VARIANTS, args.variants)})
        return 0
    if args.command == "run-folder":
        kwargs = {}
        if args.source_mod_dir:
            kwargs["source_mod_dir"] = args.source_mod_dir
        if args.dmm_mod_dir:
            kwargs["dmm_mod_dir"] = args.dmm_mod_dir
        payload = create_test_run_sword_run_artifacts(args.output_dir, run_index=args.run_index, notes=args.notes, **kwargs)
        _print_json(payload)
        return 0
    if args.command == "sync":
        kwargs = {}
        if args.source_mod_dir:
            kwargs["source_mod_dir"] = args.source_mod_dir
        if args.dmm_mod_dir:
            kwargs["dmm_mod_dir"] = args.dmm_mod_dir
        payload = sync_test_run_sword_variant_to_dmm(run_dir=args.run_dir, apply=bool(args.apply), **kwargs)
        _print_json(payload)
        return 0 if not payload.get("diagnostics") else 2
    if args.command == "compare":
        run_dir = Path(args.run_dir).expanduser()
        comparison_json = run_dir / "comparison.json"
        comparison_csv = run_dir / "comparison.csv"
        report = compare_preview_images(
            args.preview,
            item_icon_path=args.item_icon,
            in_game_path=args.in_game,
            preview_roi=args.preview_roi,
            in_game_roi=args.in_game_roi,
            item_icon_roi=args.item_icon_roi,
        )
        outputs = write_preview_comparison_report(report, json_path=comparison_json, csv_path=comparison_csv)
        _update_run_manifest(
            run_dir / "run_manifest.json",
            preview_screenshot=args.preview,
            in_game_screenshot=args.in_game,
            comparison_report=comparison_json,
            notes=args.notes,
        )
        _print_json({"outputs": outputs, "diagnostics": report.get("diagnostics", [])})
        return 0
    if args.command == "capture-ingame":
        run_dir = Path(args.run_dir).expanduser()
        _ensure_run_manifest(run_dir)
        output_path = Path(args.out).expanduser() if args.out else run_dir / "ingame.png"
        result = capture_crimson_ingame_screenshot(
            output_path,
            game_root=args.game_root,
            game_exe=args.game_exe or None,
            launch_game=bool(args.launch_game),
            wait_for_window_s=float(args.wait_for_window),
            press_e=bool(args.press_e),
            wait_after_e_s=float(args.wait_after_e),
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "ingame_capture_report.json"
        report_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        if not args.auxiliary:
            _update_run_manifest(
                run_dir / "run_manifest.json",
                in_game_screenshot=result.screenshot_path,
                in_game_capture_report=report_path,
                notes=args.notes,
            )
        _print_json({"capture_report": str(report_path), **result.to_dict()})
        return 0 if result.ok else 2
    if args.command == "game-status":
        window = find_crimson_game_window()
        _print_json({"running": bool(window), "window": dict(window)})
        return 0 if window else 2
    if args.command == "status-report":
        if args.out:
            path = write_test_run_sword_session_status(args.output_dir, output_path=args.out, variants=args.variants)
            payload = json.loads(path.read_text(encoding="utf-8"))
            _print_json({"status_report": str(path), **payload})
            return 0 if payload.get("status") == "complete" else 1
        payload = build_test_run_sword_session_status(args.output_dir, variants=args.variants)
        _print_json(payload)
        return 0 if payload.get("status") == "complete" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
