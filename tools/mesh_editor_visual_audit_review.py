from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.mesh_harness.visual_audit_review import finalize_visual_audit_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize inspected Mesh Editor visual-audit verdicts.")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--verdicts", type=Path, required=True)
    args = parser.parse_args()
    summary = finalize_visual_audit_review(args.evidence, args.verdicts)
    print(
        f"Finalized {summary['asset_count']} models: "
        f"PASS={summary['pass_count']} CONCERN={summary['concern_count']} FAIL={summary['fail_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
