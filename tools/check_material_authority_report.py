from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.material_authority_report_check import (  # noqa: E402
    DEFAULT_BLOCKING_RISK_FLAGS,
    check_material_authority_report_path,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check cdmw_material_authority_report.json for package material/DDS authority blockers."
    )
    parser.add_argument(
        "path",
        help="Report JSON path or package root containing cdmw_material_authority_report.json.",
    )
    parser.add_argument("--out-json", default="", help="Optional check-result JSON output path.")
    parser.add_argument(
        "--fail-on",
        action="append",
        default=[],
        help="Risk flag that should fail the check. Repeatable. Defaults to built-in blocker set.",
    )
    parser.add_argument(
        "--allow-risk",
        action="append",
        default=[],
        help="Remove a risk flag from the blocker set for this run. Repeatable.",
    )
    parser.add_argument("--warn-only", action="store_true", help="Print failures but return exit code 0.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    fail_on = tuple(args.fail_on or DEFAULT_BLOCKING_RISK_FLAGS)
    allowed = {str(value) for value in tuple(args.allow_risk or ()) if str(value).strip()}
    fail_on = tuple(flag for flag in fail_on if flag not in allowed)
    result = check_material_authority_report_path(args.path, fail_on_risk_flags=fail_on)
    output = json.dumps(result, indent=2, sort_keys=True)
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if args.warn_only:
        return 0
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
