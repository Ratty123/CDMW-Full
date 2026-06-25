from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.core.archive_scan_cache import scan_archive_entries
from cdmw.core.prefab_corpus import (
    build_prefab_json_import_archive_entry_report,
    build_prefab_json_import_corpus_report,
    discover_loose_prefab_corpus_paths,
    discover_prefab_archive_entries,
    merge_prefab_json_import_corpus_reports,
)


def _int_or_none(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _status(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(gate, Mapping):
        gate = {}
    summary_keys = (
        "files_discovered",
        "files_scanned",
        "scan_offset",
        "scan_count",
        "merged_report_count",
        "coverage_complete",
        "coverage_errors",
        "edit_probes_enabled",
        "discovery_limited",
        "all_discovered_files_scanned",
        "no_edit_roundtrip_passed",
        "no_edit_roundtrip_failed",
        "layout_rebuild_passed",
        "layout_rebuild_failed",
        "json_layout_rebuild_passed",
        "json_layout_rebuild_failed",
        "experimental_length_change_resource_rebuild_probe_status_effective_expected_counts",
        "experimental_length_change_placement_rebuild_probe_status_effective_expected_counts",
    )
    gate_keys = (
        "same_length_import_ready",
        "layout_no_edit_rebuild_ready",
        "json_layout_no_edit_rebuild_ready",
        "full_corpus_no_edit_rebuild_ready",
        "length_changing_import_ready",
        "length_changing_failed_subgates",
        "length_changing_blocker_detail_counts",
        "resource_resize_offset_gate_ready",
        "placement_resize_offset_gate_ready",
        "resize_offset_validator_ready",
        "resource_effective_resize_offset_model_ready",
        "placement_effective_resize_offset_model_ready",
        "effective_resize_offset_model_ready",
        "array_count_hint_semantics_proven",
        "descriptor_word3_semantics_proven",
        "descriptor_count_semantics_proven",
        "descriptor_count_mutation_proven",
        "descriptor_value_editing_ready",
        "transform_payload_layout_proven",
        "transform_value_semantics_proven",
        "transform_value_mutation_proven",
        "transform_value_editing_ready",
        "array_payload_layout_proven",
        "array_count_mutation_proven",
        "array_resizing_ready",
        "unknown_block_edit_semantics_proven",
        "reference_descriptor_edit_semantics_proven",
        "unknown_reference_preservation_ready",
    )
    return {
        "summary": {key: summary.get(key) for key in summary_keys},
        "gate": {key: gate.get(key) for key in gate_keys},
    }


def _should_fail(report: Mapping[str, Any]) -> bool:
    summary = report.get("summary", {})
    if not isinstance(summary, Mapping):
        return True
    if int(summary.get("files_scanned") or 0) <= 0:
        return True
    if summary.get("merged_report_count") is not None and summary.get("coverage_complete") is not True:
        return True
    return any(
        int(summary.get(key) or 0) > 0
        for key in ("no_edit_roundtrip_failed", "layout_rebuild_failed", "json_layout_rebuild_failed")
    )


def _expand_report_paths(paths: Sequence[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        if any(char in text for char in "*?["):
            matches = sorted(Path(match) for match in glob.glob(text))
            if not matches:
                raise FileNotFoundError(f"No report files match: {text}")
            expanded.extend(matches)
        else:
            expanded.append(path)
    return expanded


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _validate_written_report(tmp_path)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _validate_written_report(path: Path) -> None:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if b"\x00" in chunk:
                raise ValueError(f"Generated report contains a NUL byte: {path}")
    with path.open("r", encoding="utf-8") as handle:
        json.load(handle)


def _shard_report_path(shard_dir: Path, offset: int, count: int) -> Path:
    return shard_dir / f"prefab-corpus-shard-{offset:06d}-{count:06d}.json"


def _build_shard_batch(args: argparse.Namespace) -> Mapping[str, Any]:
    shard_dir = Path(args.shard_dir)
    shard_size = int(args.shard_size or 0)
    if shard_size <= 0:
        raise ValueError("--shard-size must be greater than 0.")
    max_new_shards = int(args.max_shards or 0) if int(args.max_shards or 0) > 0 else None

    include_edit_probes = not args.no_edit_probes
    reports: list[Mapping[str, Any]] = []
    built_shards = 0
    if args.archive:
        if len(args.source) != 1:
            raise ValueError("--archive expects exactly one source path.")
        root = args.source[0]
        entries = scan_archive_entries(root)
        discovered = discover_prefab_archive_entries(entries, discovery_limit=_int_or_none(args.discovery_limit))
        total = len(discovered)
        for offset in range(0, total, shard_size):
            count = min(shard_size, total - offset)
            path = _shard_report_path(shard_dir, offset, count)
            if args.resume_shards and path.exists():
                reports.append(json.loads(path.read_text(encoding="utf-8")))
                continue
            if max_new_shards is not None and built_shards >= max_new_shards:
                continue
            report = build_prefab_json_import_archive_entry_report(
                entries,
                source_label=str(root),
                discovery_limit=_int_or_none(args.discovery_limit),
                detail_scan_limit=None,
                scan_offset=offset,
                scan_count=count,
                include_edit_probes=include_edit_probes,
            )
            _write_report(path, report)
            reports.append(report)
            built_shards += 1
    else:
        if not args.source:
            raise ValueError("source path is required unless --merge-reports is used.")
        discovered = discover_loose_prefab_corpus_paths(args.source, discovery_limit=_int_or_none(args.discovery_limit))
        total = len(discovered)
        for offset in range(0, total, shard_size):
            count = min(shard_size, total - offset)
            path = _shard_report_path(shard_dir, offset, count)
            if args.resume_shards and path.exists():
                reports.append(json.loads(path.read_text(encoding="utf-8")))
                continue
            if max_new_shards is not None and built_shards >= max_new_shards:
                continue
            report = build_prefab_json_import_corpus_report(
                args.source,
                discovery_limit=_int_or_none(args.discovery_limit),
                detail_scan_limit=None,
                scan_offset=offset,
                scan_count=count,
                include_edit_probes=include_edit_probes,
            )
            _write_report(path, report)
            reports.append(report)
            built_shards += 1
    return merge_prefab_json_import_corpus_reports(reports)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a prefab JSON import corpus report.")
    parser.add_argument("source", nargs="*", type=Path, help="Loose prefab roots/files, or one game install root with --archive.")
    parser.add_argument("--archive", action="store_true", help="Treat source as a Crimson Desert install root and scan archive entries.")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--merge-reports", nargs="+", type=Path, help="Merge shard reports and fail unless coverage is complete.")
    parser.add_argument("--shard-dir", type=Path, help="Write all contiguous shard reports here, then write merged --out-json.")
    parser.add_argument("--shard-size", type=int, default=1000)
    parser.add_argument("--max-shards", type=int, help="Build at most this many new shard reports in this run.")
    parser.add_argument("--resume-shards", action="store_true", help="Reuse existing shard reports in --shard-dir when present.")
    parser.add_argument("--discovery-limit", type=int)
    parser.add_argument("--detail-scan-limit", type=int)
    parser.add_argument("--scan-offset", type=int, default=0, help="Start scanning at this sorted discovered prefab index.")
    parser.add_argument("--scan-count", type=int, help="Scan this many sorted discovered prefabs contiguously.")
    parser.add_argument("--no-edit-probes", action="store_true", help="Skip edit probes for wider no-edit/layout scans.")
    args = parser.parse_args(argv)

    if args.merge_reports and args.shard_dir:
        parser.error("--merge-reports cannot be combined with --shard-dir.")

    if args.merge_reports:
        if args.source:
            parser.error("source paths are not allowed with --merge-reports.")
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in _expand_report_paths(args.merge_reports)]
        report = merge_prefab_json_import_corpus_reports(reports)
    elif args.shard_dir:
        try:
            report = _build_shard_batch(args)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.archive:
        if len(args.source) != 1:
            parser.error("--archive expects exactly one source path.")
        root = args.source[0]
        entries = scan_archive_entries(root)
        report = build_prefab_json_import_archive_entry_report(
            entries,
            source_label=str(root),
            discovery_limit=_int_or_none(args.discovery_limit),
            detail_scan_limit=_int_or_none(args.detail_scan_limit),
            scan_offset=max(0, int(args.scan_offset or 0)),
            scan_count=_int_or_none(args.scan_count),
            include_edit_probes=not args.no_edit_probes,
        )
    else:
        if not args.source:
            parser.error("source path is required unless --merge-reports is used.")
        report = build_prefab_json_import_corpus_report(
            args.source,
            discovery_limit=_int_or_none(args.discovery_limit),
            detail_scan_limit=_int_or_none(args.detail_scan_limit),
            scan_offset=max(0, int(args.scan_offset or 0)),
            scan_count=_int_or_none(args.scan_count),
            include_edit_probes=not args.no_edit_probes,
        )

    _write_report(args.out_json, report)
    print(json.dumps(_status(report), indent=2))
    return 1 if _should_fail(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
