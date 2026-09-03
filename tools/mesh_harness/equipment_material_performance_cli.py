"""CLI for equipment material performance aggregation and repetitions."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_text
from tools.mesh_harness.equipment_material_performance import (
    EXPECTED_LOGICAL_PAC_COUNT,
    build_equipment_performance_summary,
    run_equipment_performance_repetitions,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.expected_logical_count != EXPECTED_LOGICAL_PAC_COUNT:
        raise ValueError(
            "Production equipment evidence requires exactly "
            f"{EXPECTED_LOGICAL_PAC_COUNT:,} logical PACs."
        )
    repository_root = Path(__file__).resolve().parents[2]
    evidence_root = args.evidence_root.expanduser().resolve(strict=True)
    repetition_results = args.repetition_results
    if args.execute_repetitions:
        required = {
            "--catalogue": args.catalogue,
            "--resolution": args.resolution,
            "--cache-root": args.cache_root,
            "--rust-helper": args.rust_helper,
            "--repetition-output-root": args.repetition_output_root,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "Repetition execution requires " + ", ".join(sorted(missing)) + "."
            )
        repetition_output = args.repetition_output_root.expanduser().resolve()
        _require_external_repetition_root(
            repetition_output,
            repository_root=repository_root,
            evidence_root=evidence_root,
        )
        run_equipment_performance_repetitions(
            catalogue_path=args.catalogue,
            resolution_path=args.resolution,
            evidence_root=evidence_root,
            output_root=repetition_output,
            cache_root=args.cache_root,
            rust_helper=args.rust_helper,
            capture_timeout_seconds=args.capture_timeout,
        )
        repetition_results = (
            repetition_output / "equipment-performance-repetitions.json"
        )

    summary = build_equipment_performance_summary(
        evidence_root,
        baseline_root=args.baseline_root,
        repetition_results_path=repetition_results,
        baseline_repetition_results_path=args.baseline_repetition_results,
        expected_logical_count=args.expected_logical_count,
    )
    if args.output is not None:
        output = args.output.expanduser().resolve()
        protected_roots = [repository_root, evidence_root]
        if args.baseline_root is not None:
            protected_roots.append(args.baseline_root.expanduser().resolve(strict=True))
        for protected_input in (
            repetition_results,
            args.baseline_repetition_results,
            args.catalogue,
            args.resolution,
        ):
            if protected_input is not None:
                protected_roots.append(
                    protected_input.expanduser().resolve()
                )
        capture_manifest = summary.get("capture_manifest", {})
        if isinstance(capture_manifest, dict):
            census_identity = capture_manifest.get("census_identity", {})
            if isinstance(census_identity, dict):
                archive = census_identity.get("archive", {})
                if isinstance(archive, dict):
                    live_archive = archive.get("live_archive", {})
                    if isinstance(live_archive, dict):
                        package_root = str(live_archive.get("package_root", "") or "")
                        if package_root:
                            protected_roots.append(
                                Path(package_root).expanduser().resolve()
                            )
        _require_external_summary_output(output, protected_roots=protected_roots)
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "acceptance_status": summary["acceptance_status"],
                "census": {
                    key: summary["census"][key]
                    for key in (
                        "expected_logical_count",
                        "manifest_asset_count",
                        "instrumented_renderable_count",
                        "source_only_count",
                        "missing_or_uninstrumented_count",
                        "complete",
                    )
                },
                "integrity": summary["integrity"],
                "worst_cases": summary["worst_cases"],
                "repetition_plan": summary["repetition_plan"],
                "baseline_comparison_status": summary["baseline_comparison"]["status"],
                "repetition_acceptance_status": summary["repetition_acceptance"][
                    "status"
                ],
                "output": str(args.output.expanduser().resolve())
                if args.output is not None
                else "",
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    if summary["acceptance_status"] == "fail":
        return 1
    if args.require_complete and summary["acceptance_status"] != "pass":
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate the exact equipment material performance census, select "
            "deterministic worst cases, and optionally run exact 7-cold/20-warm evidence."
        )
    )
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--repetition-results", type=Path)
    parser.add_argument("--baseline-repetition-results", type=Path)
    parser.add_argument(
        "--expected-logical-count", type=int, default=EXPECTED_LOGICAL_PAC_COUNT
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--execute-repetitions", action="store_true")
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--resolution", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--rust-helper", type=Path)
    parser.add_argument("--repetition-output-root", type=Path)
    parser.add_argument("--capture-timeout", type=float, default=180.0)
    return parser


def _require_external_repetition_root(
    output_root: Path,
    *,
    repository_root: Path,
    evidence_root: Path,
) -> None:
    repository = repository_root.resolve()
    evidence = evidence_root.resolve()
    if _paths_overlap(output_root, repository):
        raise ValueError("Repetition evidence must remain outside the repository.")
    if _paths_overlap(output_root, evidence):
        raise ValueError(
            "Repetition evidence must use a separate root so the census remains immutable."
        )


def _require_external_summary_output(
    output: Path, *, protected_roots: Sequence[Path]
) -> None:
    if any(_paths_overlap(output, root.resolve()) for root in protected_roots):
        raise ValueError(
            "Performance summary output must remain outside the repository, census, "
            "baseline, and game install."
        )


def _paths_overlap(candidate: Path, protected: Path) -> bool:
    return (
        candidate == protected
        or candidate.is_relative_to(protected)
        or protected.is_relative_to(candidate)
    )


if __name__ == "__main__":
    sys.exit(main())
