from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.external_model_audit import build_external_model_audit_catalogue, write_external_model_audit_catalogue


DEFAULT_EXTERNAL_MODEL_AUDIT_ROOT = Path(r"E:\ModelCatalogue\downloads")
EXTERNAL_MODEL_AUDIT_ROOT_ENV = "CDMW_MODEL_CATALOGUE_ROOT"


def _resolved_roots(values: Sequence[str] | None) -> tuple[Path, ...]:
    if values:
        return tuple(Path(value).expanduser() for value in values)
    configured = str(os.environ.get(EXTERNAL_MODEL_AUDIT_ROOT_ENV) or "").strip()
    return (Path(configured).expanduser() if configured else DEFAULT_EXTERNAL_MODEL_AUDIT_ROOT,)


def _load_resume_report(path: Path) -> Mapping[str, object] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Resume report must contain a JSON object: {path}")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an external model material audit catalogue.")
    parser.add_argument("--root", action="append", dest="roots")
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=50_000)
    parser.add_argument("--audit-zip-contents", action="store_true")
    parser.add_argument("--max-zip-audits", type=int, default=None)
    parser.add_argument("--resume", action="store_true", help="Reuse matching rows from --out-json.")
    parser.add_argument("--force", action="store_true", help="Re-audit the selected chunk even when fingerprints match.")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-index", type=int, default=0)
    args = parser.parse_args(argv)

    resume_report = _load_resume_report(args.out_json) if args.resume else None
    report = build_external_model_audit_catalogue(
        _resolved_roots(args.roots),
        max_files=args.max_files,
        audit_zip_contents=args.audit_zip_contents,
        max_zip_audits=args.max_zip_audits,
        resume_report=resume_report,
        force=args.force,
        chunk_size=args.chunk_size,
        chunk_index=args.chunk_index,
    )
    output = write_external_model_audit_catalogue(report, args.out_json)
    print(
        json.dumps(
            {
                "output": str(output),
                "progress": report.get("progress", {}),
                "summary": report.get("summary", {}),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
