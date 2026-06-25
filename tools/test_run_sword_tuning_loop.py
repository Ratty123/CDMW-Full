from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.rendering.ingame_capture import capture_crimson_ingame_screenshot
from cdmw.rendering.test_run_sword_tuning import (
    TEST_RUN_SWORD_MINIMUM_VARIANTS,
    build_test_run_sword_run_manifest,
    build_test_run_sword_session_status,
    write_test_run_sword_session_plan,
    write_test_run_sword_session_status,
)


def _run_index(run_dir: Path) -> int:
    suffix = run_dir.name.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else 1


def _write_run_manifest(run_dir: Path, *, capture_report: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_test_run_sword_run_manifest(
        run_index=_run_index(run_dir),
        preview_screenshot=run_dir / "preview.png",
        in_game_screenshot=run_dir / "ingame.png",
        in_game_capture_report=capture_report,
        package_manifest=run_dir / "package_manifest.json",
        comparison_report=run_dir / "comparison.json",
    )
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _plan(args: argparse.Namespace) -> int:
    session = write_test_run_sword_session_plan(
        args.output_dir,
        variants=args.variants,
        source_mod_dir=args.source_mod_dir,
        dmm_mod_dir=args.dmm_mod_dir,
    )
    print(json.dumps({"session_manifest": str(session), "variant_count": max(TEST_RUN_SWORD_MINIMUM_VARIANTS, int(args.variants))}, indent=2))
    return 0


def _capture_ingame(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    report_path = run_dir / "ingame_capture_report.json"
    screenshot_path = run_dir / "ingame.png"
    if not args.auxiliary:
        result = capture_crimson_ingame_screenshot(
            screenshot_path,
            launch_game=False,
            wait_for_window_s=args.wait_for_window,
            press_e=args.press_e,
        )
    else:
        result = capture_crimson_ingame_screenshot(
            screenshot_path,
            launch_game=False,
            wait_for_window_s=args.wait_for_window,
        )
    payload = result.to_dict()
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_run_manifest(run_dir, capture_report=report_path)
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 2


def _status(args: argparse.Namespace) -> int:
    payload = build_test_run_sword_session_status(args.output_dir, variants=args.variants)
    if args.out_json:
        write_test_run_sword_session_status(args.output_dir, output_path=args.out_json, variants=args.variants)
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--variants", type=int, default=TEST_RUN_SWORD_MINIMUM_VARIANTS)
    plan.add_argument("--source-mod-dir", type=Path, required=True)
    plan.add_argument("--dmm-mod-dir", type=Path, required=True)
    plan.set_defaults(func=_plan)
    capture = sub.add_parser("capture-ingame")
    capture.add_argument("--run-dir", type=Path, required=True)
    capture.add_argument("--wait-for-window", type=float, default=45.0)
    capture.add_argument("--press-e", action="store_true")
    capture.add_argument("--auxiliary", action="store_true")
    capture.set_defaults(func=_capture_ingame)
    status = sub.add_parser("status")
    status.add_argument("--output-dir", type=Path, required=True)
    status.add_argument("--variants", type=int, default=TEST_RUN_SWORD_MINIMUM_VARIANTS)
    status.add_argument("--out-json", type=Path)
    status.set_defaults(func=_status)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
