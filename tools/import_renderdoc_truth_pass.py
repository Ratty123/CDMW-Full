from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.renderdoc_truth_pass import (  # noqa: E402
    load_renderdoc_truth_pass,
    summarize_truth_reports,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import normalized RenderDoc shader truth JSON.")
    parser.add_argument("--capture-json", nargs="+", action="append", required=True, help="One or more exported capture truth JSON files.")
    parser.add_argument("--out-json", required=True, help="Output normalized report JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    capture_paths = [path for group in args.capture_json for path in group]
    reports = [load_renderdoc_truth_pass(Path(path)) for path in capture_paths]
    output = {
        "summary": summarize_truth_reports(reports),
        "captures": reports,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(reports)} capture report(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
