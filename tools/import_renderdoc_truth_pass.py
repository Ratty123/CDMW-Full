from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from cdmw.rendering.renderdoc_truth_pass import normalize_renderdoc_truth_pass, summarize_truth_reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-json", type=Path, action="append", required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    captures = [normalize_renderdoc_truth_pass(json.loads(path.read_text(encoding="utf-8"))) for path in args.capture_json]
    report = {"schema_version": 1, "summary": summarize_truth_reports(captures), "captures": captures}
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
