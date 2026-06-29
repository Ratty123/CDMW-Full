from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from cdmw.core.external_model_audit import build_external_model_audit_catalogue, write_external_model_audit_catalogue


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an external model material audit catalogue.")
    parser.add_argument("--root", action="append", dest="roots", required=True)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=50_000)
    parser.add_argument("--audit-zip-contents", action="store_true")
    parser.add_argument("--max-zip-audits", type=int, default=None)
    args = parser.parse_args(argv)

    report = build_external_model_audit_catalogue(
        [Path(root) for root in args.roots],
        max_files=args.max_files,
        audit_zip_contents=args.audit_zip_contents,
        max_zip_audits=args.max_zip_audits,
    )
    output = write_external_model_audit_catalogue(report, args.out_json)
    print(json.dumps({"output": str(output), "summary": report.get("summary", {})}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
