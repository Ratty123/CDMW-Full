from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.external_model_audit import (  # noqa: E402
    EXTERNAL_MODEL_AUDIT_EXTENSIONS,
    build_external_model_audit_catalogue,
    write_external_model_audit_catalogue,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of external model files. Builds a material inventory report "
            "for OBJ, DAE, glTF, GLB, and records unsupported FBX rows with companion texture guesses."
        )
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help=r"Model root to scan. Repeatable. Defaults to E:\ModelCatalogue\downloads.",
    )
    parser.add_argument(
        "--out-json",
        default=str(REPO_ROOT / "model_catalogue" / "external_model_material_audit.json"),
        help="JSON report output path.",
    )
    parser.add_argument("--max-files", type=int, default=50_000, help="Maximum model files to scan.")
    parser.add_argument(
        "--audit-zip-contents",
        action="store_true",
        help="Safely temp-extract importable ZIPs and build material inventory for contained models.",
    )
    parser.add_argument(
        "--max-zip-audits",
        type=int,
        default=25,
        help="Maximum ZIP files to temp-extract when --audit-zip-contents is set. Use 0 for no cap.",
    )
    args = parser.parse_args(argv)

    roots = [Path(value) for value in args.root] if args.root else [Path(r"E:\ModelCatalogue\downloads")]
    report = build_external_model_audit_catalogue(
        roots,
        max_files=max(1, int(args.max_files)),
        audit_zip_contents=bool(args.audit_zip_contents),
        max_zip_audits=max(0, int(args.max_zip_audits)),
    )
    output_path = write_external_model_audit_catalogue(report, args.out_json)
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    print(
        json.dumps(
            {
                "output": str(output_path),
                "extensions": list(EXTERNAL_MODEL_AUDIT_EXTENSIONS),
                "summary": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
