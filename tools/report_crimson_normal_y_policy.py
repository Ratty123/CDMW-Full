from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _scan_audit_csv(path: Path, *, limit: int = 0) -> dict[str, object]:
    normal_rows = 0
    suffix_counts: Counter[str] = Counter()
    source_kind_counts: Counter[str] = Counter()
    authority_counts: Counter[str] = Counter()
    sampled_paths: list[str] = []
    if not path.is_file():
        return {
            "status": "missing",
            "normal_rows": 0,
            "normal_suffix_counts": [],
            "normal_source_kind_counts": [],
            "normal_authority_counts": [],
            "sampled_paths": [],
        }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if limit > 0 and index >= limit:
                break
            slot = str(row.get("slot", "") or "").strip().lower()
            source_kind = str(row.get("source_kind", "") or "").strip().lower()
            parameter_name = str(row.get("parameter_name", "") or "").strip().lower()
            dds_path = str(row.get("dds_path", "") or "").strip()
            if slot != "normal" and "normal" not in source_kind and "normal" not in parameter_name:
                continue
            normal_rows += 1
            suffix_counts[str(row.get("suffix", "") or "<none>")] += 1
            source_kind_counts[source_kind or "<none>"] += 1
            authority_counts[str(row.get("authority", "") or "<none>")] += 1
            if dds_path and len(sampled_paths) < 16:
                sampled_paths.append(dds_path)
    return {
        "status": "scanned",
        "normal_rows": normal_rows,
        "normal_suffix_counts": suffix_counts.most_common(16),
        "normal_source_kind_counts": source_kind_counts.most_common(16),
        "normal_authority_counts": authority_counts.most_common(8),
        "sampled_paths": sampled_paths,
    }


def build_normal_y_policy_report(
    *,
    audit_csv: Path | None = None,
    archive_source: Path | None = None,
    texture_helper_source: Path | None = None,
    d3d11_preview_source: Path | None = None,
    audit_limit: int = 0,
) -> dict[str, object]:
    audit = _scan_audit_csv(audit_csv, limit=audit_limit) if audit_csv is not None else {}
    archive_text = _read_text(archive_source) if archive_source is not None else ""
    helper_text = _read_text(texture_helper_source) if texture_helper_source is not None else ""
    d3d11_text = _read_text(d3d11_preview_source) if d3d11_preview_source is not None else ""

    archive_marks_green_up = '"normal_space": "green_up" if slot_key == "normal"' in archive_text
    helper_inverts_green_up = (
        "should_invert_green" in helper_text
        and 'normal_space == "green_up"' in helper_text
        and "invert_green_channel" in helper_text
    )
    d3d11_asset_inverts = (
        "bool invert_normal_y = true" in d3d11_text
        and "normal_y_policy.find(\"invert\")" in d3d11_text
        and "d3d11_normal_y_mode" in d3d11_text
    )
    inferred = archive_marks_green_up and helper_inverts_green_up and d3d11_asset_inverts
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "inferred" if inferred else "partial",
        "normal_y_mode": "green_up_asset_inverted_for_directx_preview" if inferred else "",
        "authority": "corpus_and_app_policy_inferred" if inferred else "diagnostic",
        "renderdoc_authority": "unavailable_ags_replay_blocked",
        "audit": audit,
        "evidence": {
            "archive_original_normal_space_green_up": archive_marks_green_up,
            "directxtex_preview_inverts_green_up_normals": helper_inverts_green_up,
            "d3d11_asset_mode_inverts_normal_y_by_default": d3d11_asset_inverts,
        },
        "policy": (
            "Original archive normal maps are treated as green-up source data and inverted for DirectX-style preview. "
            "This is not RenderDoc replay truth; it is corpus/app behavior evidence."
        ),
        "findings": [
            "renderdoc_normal_y_truth_unavailable_due_ags_replay_blocker",
            "use_force_flip_or_force_no_flip_setting_for_visual_A_B_until_replay_truth_available",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report Crimson normal-map Y policy from corpus/app evidence.")
    parser.add_argument("--audit-csv", default="", help="Optional shader audit CSV for normal row counts.")
    parser.add_argument("--archive-source", default="cdmw/core/archive.py")
    parser.add_argument("--texture-helper-source", default="native/cd_texture_dx/src/main.cpp")
    parser.add_argument("--d3d11-preview-source", default="native/cdmw_d3d11_preview/src/main.cpp")
    parser.add_argument("--audit-limit", type=int, default=0, help="Optional max audit rows to scan.")
    parser.add_argument("--out-json", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_normal_y_policy_report(
        audit_csv=Path(args.audit_csv) if args.audit_csv else None,
        archive_source=Path(args.archive_source),
        texture_helper_source=Path(args.texture_helper_source),
        d3d11_preview_source=Path(args.d3d11_preview_source),
        audit_limit=max(0, int(args.audit_limit or 0)),
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"normal-y policy: {report['status']} ({report.get('normal_y_mode', '')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
