from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from cdmw.core.external_model_audit_check import (
    DEFAULT_BLOCKING_RISK_FLAGS,
    check_external_model_audit_report_path,
)


def _risk_flags(values: Sequence[str], default: Sequence[str]) -> tuple[str, ...]:
    flags: list[str] = []
    for value in values:
        flags.extend(flag for raw in str(value).split(",") if (flag := raw.strip()))
    return tuple(flags) or tuple(default)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an external model audit report.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--warn-only", action="store_true")
    parser.add_argument("--fail-on", action="append", default=[])
    parser.add_argument("--allow-risk", action="append", default=[])
    args = parser.parse_args(argv)

    fail_on = () if args.warn_only else _risk_flags(args.fail_on, DEFAULT_BLOCKING_RISK_FLAGS)
    allowed = set(_risk_flags(args.allow_risk, ()))
    fail_on = tuple(flag for flag in fail_on if flag not in allowed)
    result = check_external_model_audit_report_path(args.path, fail_on_risk_flags=fail_on)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if not result.get("blocking_risk_flags") else 1


if __name__ == "__main__":
    raise SystemExit(main())
