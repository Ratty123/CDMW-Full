from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from cdmw.rendering.asset_fidelity_preflight import normal_y_policy_report


def _read_text(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _audit_summary(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"normal_rows": 0}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {"normal_rows": 0}
    normal_rows = [
        row
        for row in rows
        if str(row.get("slot", "") or "").lower() == "normal"
        or str(row.get("source_kind", "") or "").lower() == "crimson_normal"
        or str(row.get("suffix", "") or "").lower() in {"n", "wn"}
    ]
    return {"normal_rows": len(normal_rows), "row_count": len(rows)}


def build_normal_y_policy_report(
    *,
    audit_csv: Path | None = None,
    archive_source: Path | None = None,
    texture_helper_source: Path | None = None,
    d3d11_preview_source: Path | None = None,
    d3d11_normal_y_mode: object = "asset",
) -> dict[str, Any]:
    report = dict(normal_y_policy_report(d3d11_normal_y_mode))
    archive_text = _read_text(archive_source)
    helper_text = _read_text(texture_helper_source)
    d3d11_text = _read_text(d3d11_preview_source)
    report.update(
        {
            "status": "inferred",
            "audit": _audit_summary(audit_csv),
            "source_checks": {
                "archive_marks_green_up": "green_up" in archive_text,
                "texture_helper_inverts_green": "invert_green" in helper_text,
                "d3d11_exposes_normal_y_mode": "d3d11_normal_y_mode" in d3d11_text,
            },
        }
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-csv", type=Path)
    parser.add_argument("--archive-source", type=Path)
    parser.add_argument("--texture-helper-source", type=Path)
    parser.add_argument("--d3d11-preview-source", type=Path)
    parser.add_argument("--d3d11-normal-y-mode", default="asset")
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_normal_y_policy_report(
        audit_csv=args.audit_csv,
        archive_source=args.archive_source,
        texture_helper_source=args.texture_helper_source,
        d3d11_preview_source=args.d3d11_preview_source,
        d3d11_normal_y_mode=args.d3d11_normal_y_mode,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
