"""CLI for hash-pinned review of equipment PAC and material-region units."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.mesh_harness.equipment_material_review import (
    build_equipment_review_index,
    finalize_equipment_review,
    record_equipment_review_pages,
    record_equipment_review_units,
    summarize_equipment_review,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = build_equipment_review_index(args.evidence_root)
    elif args.command == "record":
        limitation_evidence = _read_optional_object(args.limitation_evidence)
        disposition_evidence = _read_optional_object(args.disposition_evidence)
        record = (
            record_equipment_review_units
            if args.unit_id
            else record_equipment_review_pages
        )
        result = record(
            args.evidence_root,
            args.unit_id or args.page_id,
            verdict=args.verdict,
            observations=args.observations,
            limitation_evidence=limitation_evidence,
            disposition_evidence=disposition_evidence,
        )
    elif args.command == "status":
        result = summarize_equipment_review(args.evidence_root)
    else:
        result = finalize_equipment_review(
            args.evidence_root,
            args.catalogue,
            args.resolution,
        )
    print(json.dumps(_brief(result), indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, record, and finalize the exhaustive equipment material review."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--evidence-root", required=True, type=Path)
    record = commands.add_parser("record")
    record.add_argument("--evidence-root", required=True, type=Path)
    target = record.add_mutually_exclusive_group(required=True)
    target.add_argument("--unit-id", action="append")
    target.add_argument(
        "--page-id",
        action="append",
        help="Compatibility option; valid only for a page containing one review unit.",
    )
    record.add_argument(
        "--verdict",
        choices=(
            "PASS",
            "LIMITATION",
            "EXCLUDED_CATALOGUE_DEFECT",
            "AUTHORED_EMPTY",
            "CONCERN",
            "FAIL",
        ),
        required=True,
    )
    record.add_argument("--observations", required=True)
    record.add_argument("--limitation-evidence", type=Path)
    record.add_argument("--disposition-evidence", type=Path)
    status = commands.add_parser("status")
    status.add_argument("--evidence-root", required=True, type=Path)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--evidence-root", required=True, type=Path)
    finalize.add_argument("--catalogue", required=True, type=Path)
    finalize.add_argument("--resolution", required=True, type=Path)
    return parser


def _brief(result: dict[str, object]) -> dict[str, object]:
    return {
        key: result[key]
        for key in (
            "schema",
            "ok",
            "asset_count",
            "renderable_asset_count",
            "source_only_asset_count",
            "material_region_count",
            "review_unit_count",
            "page_count",
            "page_counts",
            "unit_counts",
            "verdict_counts",
            "rendered_pass_count",
            "limitation_count",
            "excluded_catalogue_defect_count",
            "authored_empty_count",
            "reviewed_count",
            "unreviewed_count",
            "concern_count",
            "fail_count",
            "finalized",
        )
        if key in result
    }


def _read_optional_object(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    payload = json.loads(
        path.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise TypeError(f"Review evidence must be a JSON object: {path}")
    return payload


if __name__ == "__main__":
    sys.exit(main())
