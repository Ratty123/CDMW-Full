from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from cdmw.core.archive_hkx_corpus_planning import _HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS

_HKX_CORPUS_PRIORITY_CLASS_TARGETS = (
    "hknpTriangleShape",
    "hknpBallAndSocketConstraintData",
    "hknpLodShape",
    "hknpHingeConstraintData",
    "hknpVelocityConstraintMotor",
    "hknpMeshShape",
    "hknpPhysicsSystemData",
    "hknpPhysicsSystemData::ExtendedBodyCinfo",
    "hknpMaterial",
    "hknpRagdollConstraintData",
)


def _hkx_corpus_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _hkx_corpus_counter_value(mapping: object, *keys: str) -> int:
    if not isinstance(mapping, Mapping):
        return 0
    return sum(_hkx_corpus_int(mapping.get(key)) for key in keys)


def _hkx_corpus_counter_matching(mapping: object, fragments: Sequence[str]) -> int:
    if not isinstance(mapping, Mapping):
        return 0
    total = 0
    lowered_fragments = tuple(fragment.casefold() for fragment in fragments)
    for key, value in mapping.items():
        key_text = str(key).casefold()
        if any(fragment in key_text for fragment in lowered_fragments):
            total += _hkx_corpus_int(value)
    return total


def _hkx_corpus_sorted_count_rows(mapping: object, limit: int = 12) -> List[Dict[str, object]]:
    if not isinstance(mapping, Mapping):
        return []
    rows: List[Dict[str, object]] = []
    for key, value in mapping.items():
        count = _hkx_corpus_int(value)
        if count <= 0:
            continue
        rows.append({"key": str(key), "count": count})
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["key"])))[: max(0, int(limit))]


def _hkx_corpus_file_examples_for_target(
    rows: Sequence[Mapping[str, object]],
    target: str,
    *,
    limit: int = 5,
) -> List[str]:
    examples: List[str] = []
    target_text = str(target)
    for row in rows:
        path = str(row.get("path") or "")
        if not path:
            continue
        matched = False
        unknown_areas = row.get("unknown_schema_areas")
        if isinstance(unknown_areas, list):
            for area in unknown_areas:
                if isinstance(area, Mapping) and str(area.get("type_name") or "") == target_text:
                    matched = True
                    break
        if not matched:
            type_names = row.get("type_names")
            if isinstance(type_names, list) and target_text in {str(value) for value in type_names}:
                matched = True
        if not matched:
            readiness = row.get("hkclass_metadata_readiness_summary")
            if isinstance(readiness, Mapping):
                hard_targets = readiness.get("hard_decoder_observed_targets")
                class_targets = readiness.get("class_internals_targets")
                if isinstance(hard_targets, list) and target_text in {str(value) for value in hard_targets}:
                    matched = True
                if isinstance(class_targets, list) and target_text in {str(value) for value in class_targets}:
                    matched = True
        if matched:
            examples.append(path)
            if len(examples) >= limit:
                break
    return examples


def _hkx_corpus_file_examples_for_ptch_case(
    rows: Sequence[Mapping[str, object]],
    case: str,
    *,
    limit: int = 5,
) -> List[str]:
    examples: List[str] = []
    wanted = str(case)
    for row in rows:
        path = str(row.get("path") or "")
        if not path:
            continue
        summary = row.get("fixup_semantics_summary")
        if not isinstance(summary, Mapping):
            continue
        priorities = summary.get("ptch_remaining_case_priorities")
        if not isinstance(priorities, list):
            continue
        if any(isinstance(priority, Mapping) and str(priority.get("case") or "") == wanted for priority in priorities):
            examples.append(path)
            if len(examples) >= limit:
                break
    return examples


def _hkx_corpus_priority_targets(
    report: Mapping[str, object],
    file_rows: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    unknown_byte_priorities = report.get("aggregate_unknown_schema_type_priorities")
    unknown_frequency_priorities = report.get("aggregate_unknown_schema_frequency_priorities")
    hard_target_counts = report.get("aggregate_hard_decoder_target_counts")
    hard_byte_counts = report.get("aggregate_hard_decoder_target_byte_counts")
    class_target_counts = report.get("aggregate_class_internals_target_counts")
    priority_targets: List[Dict[str, object]] = []
    seen_targets: set[str] = set()

    def _add_priority_target(row: Dict[str, object]) -> None:
        target = str(row.get("target") or row.get("type_name") or row.get("key") or "")
        if not target or target in seen_targets:
            return
        seen_targets.add(target)
        row["priority_rank"] = len(priority_targets) + 1
        row["sample_paths"] = _hkx_corpus_file_examples_for_target(file_rows, target)
        priority_targets.append(row)

    if isinstance(unknown_byte_priorities, list):
        for priority in unknown_byte_priorities[:12]:
            if not isinstance(priority, Mapping):
                continue
            type_name = str(priority.get("type_name") or "")
            if type_name:
                _add_priority_target(
                    {
                        "target": type_name,
                        "source": "unknown_schema_bytes",
                        "record_count": _hkx_corpus_int(priority.get("record_count")),
                        "raw_preserved_byte_count": _hkx_corpus_int(priority.get("raw_preserved_byte_count")),
                        "raw_preserved_byte_share": float(priority.get("raw_preserved_byte_share") or 0.0),
                        "reason": "Unknown schema still preserved as raw CDMW metadata; decode this to reduce raw fallback.",
                    }
                )
    if isinstance(unknown_frequency_priorities, list):
        for priority in unknown_frequency_priorities[:12]:
            if not isinstance(priority, Mapping):
                continue
            type_name = str(priority.get("type_name") or "")
            if type_name:
                _add_priority_target(
                    {
                        "target": type_name,
                        "source": "unknown_schema_frequency",
                        "record_count": _hkx_corpus_int(priority.get("record_count")),
                        "raw_preserved_byte_count": _hkx_corpus_int(priority.get("raw_preserved_byte_count")),
                        "record_count_share": float(priority.get("record_count_share") or 0.0),
                        "reason": "Frequent unknown schema; decode this to improve many files.",
                    }
                )
    if isinstance(class_target_counts, Mapping):
        for target in _HKX_CORPUS_PRIORITY_CLASS_TARGETS:
            count = _hkx_corpus_int(class_target_counts.get(target))
            if count > 0:
                _add_priority_target(
                    {
                        "target": target,
                        "source": "class_internals_target",
                        "observation_count": count,
                        "reason": "Observed class-specific target needs real member metadata and stronger decoder coverage.",
                    }
                )
    if isinstance(hard_target_counts, Mapping):
        for target, count_value in sorted(
            hard_target_counts.items(),
            key=lambda item: (-_hkx_corpus_int(item[1]), str(item[0])),
        ):
            count = _hkx_corpus_int(count_value)
            if count > 0:
                _add_priority_target(
                    {
                        "target": str(target),
                        "source": "hard_decoder_target",
                        "observation_count": count,
                        "observed_byte_count": _hkx_corpus_int(hard_byte_counts.get(target))
                        if isinstance(hard_byte_counts, Mapping)
                        else 0,
                        "reason": "Hard internal layout is observed in the corpus but still needs semantic decode and rebuild rules.",
                    }
                )
    return priority_targets


def _hkx_corpus_representative_samples(
    report: Mapping[str, object],
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    representative_plan = report.get("representative_real_hkx_corpus_plan")
    role_status = representative_plan.get("role_status") if isinstance(representative_plan, Mapping) else None
    sample_files: List[Dict[str, object]] = []
    roundtrip_required: List[Dict[str, object]] = []
    if isinstance(role_status, Mapping):
        for role_key, raw_status in sorted(role_status.items()):
            if not isinstance(raw_status, Mapping):
                continue
            examples = (
                [str(path) for path in raw_status.get("examples", []) if str(path)]
                if isinstance(raw_status.get("examples"), list)
                else []
            )
            status_row = {
                "role": str(role_key),
                "label": str(raw_status.get("label") or role_key),
                "covered": bool(raw_status.get("covered")),
                "file_count": _hkx_corpus_int(raw_status.get("file_count")),
                "roundtrip_identical_count": _hkx_corpus_int(raw_status.get("roundtrip_identical_count")),
                "roundtrip_complete": bool(raw_status.get("roundtrip_complete")),
                "examples": examples[:5],
            }
            sample_files.append(status_row)
            if status_row["covered"] and not status_row["roundtrip_complete"]:
                roundtrip_required.append(status_row)
    return sample_files, roundtrip_required


def _hkx_corpus_ptch_targets(
    report: Mapping[str, object],
    file_rows: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    ptch_proof = report.get("ptch_semantics_proof")
    requirements = ptch_proof.get("requirements") if isinstance(ptch_proof, Mapping) else None
    targets: List[Dict[str, object]] = []
    if isinstance(requirements, list):
        for requirement in requirements:
            if not isinstance(requirement, Mapping):
                continue
            key = str(requirement.get("key") or "")
            if key:
                targets.append(
                    {
                        "key": key,
                        "label": str(requirement.get("label") or key),
                        "observed": bool(requirement.get("observed")),
                        "observation_count": _hkx_corpus_int(requirement.get("observation_count")),
                        "status": "observed_unpromoted"
                        if bool(requirement.get("observed"))
                        else "missing_corpus_observation",
                        "description": str(requirement.get("description") or ""),
                    }
                )
    else:
        payload_counts = report.get("aggregate_ptch_payload_match_kind_counts")
        reference_counts = report.get("aggregate_ptch_semantics_reference_category_counts")
        varuint_counts = report.get("aggregate_ptch_varuint_status_counts")
        target_counts = report.get("aggregate_tagfile_ptch_target_status_counts")
        derived_counts = {
            "object_or_null_patch_sites": _hkx_corpus_counter_value(target_counts, "object", "null"),
            "data_references": _hkx_corpus_counter_value(payload_counts, "ptch_data_offset", "ptch_absolute_offset")
            + _hkx_corpus_counter_value(reference_counts, "data_reference_candidate"),
            "string_references": _hkx_corpus_counter_value(payload_counts, "ptch_string_table_index")
            + _hkx_corpus_counter_value(reference_counts, "string_reference"),
            "type_references": _hkx_corpus_counter_value(payload_counts, "ptch_type_index")
            + _hkx_corpus_counter_value(reference_counts, "type_reference", "type_class_reference"),
            "section_local_or_packed_indexes": _hkx_corpus_counter_matching(
                payload_counts, ("section_local", "packed_index")
            )
            + _hkx_corpus_counter_matching(reference_counts, ("section_local", "packed_index")),
            "packed_or_varuint_variants": sum(
                _hkx_corpus_int(count)
                for status, count in (varuint_counts.items() if isinstance(varuint_counts, Mapping) else ())
                if str(status or "") not in {"", "not_decoded", "native_not_decoded"}
            ),
        }
        for key, label, description in _HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS:
            count = int(derived_counts.get(key, 0))
            targets.append(
                {
                    "key": key,
                    "label": label,
                    "observed": count > 0,
                    "observation_count": count,
                    "status": "observed_unpromoted" if count > 0 else "missing_corpus_observation",
                    "description": description,
                }
            )
    remaining_cases = report.get("aggregate_ptch_remaining_case_priorities")
    if isinstance(remaining_cases, list):
        for case in remaining_cases[:24]:
            if not isinstance(case, Mapping):
                continue
            case_name = str(case.get("case") or "")
            if case_name:
                targets.append(
                    {
                        "key": case_name,
                        "label": case_name,
                        "observed": True,
                        "observation_count": _hkx_corpus_int(case.get("count")),
                        "status": "remaining_case",
                        "description": str(
                            case.get("description")
                            or "Remaining PTCH/fixup observation that needs corpus review."
                        ),
                        "sample_paths": _hkx_corpus_file_examples_for_ptch_case(file_rows, case_name),
                    }
                )
    return targets


def _hkx_corpus_native_scan_status(report: Mapping[str, object]) -> Dict[str, object]:
    native_fast_scan = report.get("native_fast_scan")
    available = isinstance(native_fast_scan, Mapping)
    return {
        "available": available,
        "status": "available" if available else "unavailable",
        "format": str(native_fast_scan.get("format") or "") if available else "",
        "file_count": _hkx_corpus_int(native_fast_scan.get("file_count")) if available else 0,
        "ok_count": _hkx_corpus_int(native_fast_scan.get("ok_count")) if available else 0,
        "total_item_records": _hkx_corpus_int(native_fast_scan.get("total_item_records")) if available else 0,
        "total_physics_tuning_slots": _hkx_corpus_int(native_fast_scan.get("total_physics_tuning_slots"))
        if available
        else 0,
        "note": ""
        if available
        else "Native Rust corpus preflight was unavailable; install cargo/rustc and rerun for native evidence.",
    }


def build_hkx_corpus_evidence_from_report(
    report: Mapping[str, object],
    *,
    source_path: Optional[Path | str] = None,
) -> Dict[str, object]:
    """Extract a compact decoder-priority view from an HKX corpus report.

    The full corpus JSON can be hundreds of MB because it carries per-file rows. This helper keeps
    only the evidence needed to drive decoder work and UI/status summaries.
    """

    files_raw = report.get("files")
    file_rows = [row for row in files_raw if isinstance(row, Mapping)] if isinstance(files_raw, list) else []
    priority_targets = _hkx_corpus_priority_targets(report, file_rows)
    sample_files, roundtrip_required = _hkx_corpus_representative_samples(report)
    mesh_detail_counts = report.get("aggregate_mesh_detail_group_counts")
    evidence: Dict[str, object] = {
        "format": "cdmw_hkx_corpus_evidence_v1",
        "source_report_format": str(report.get("format") or ""),
        "source_report_path": str(source_path) if source_path is not None else "",
        "source_report_external": source_path is not None,
        "discovered_file_count": _hkx_corpus_int(report.get("discovered_file_count")),
        "file_count": _hkx_corpus_int(report.get("file_count")),
        "ok_count": _hkx_corpus_int(report.get("ok_count")),
        "priority_decoder_targets": priority_targets[:40],
        "ptch_semantic_targets": _hkx_corpus_ptch_targets(report, file_rows)[:48],
        "representative_sample_files": sample_files,
        "roundtrip_required_files": roundtrip_required,
        "native_scan_status": _hkx_corpus_native_scan_status(report),
        "mesh_detail_group_counts": dict(mesh_detail_counts) if isinstance(mesh_detail_counts, Mapping) else {},
        "ptch_patch_site_summary": {
            "found": _hkx_corpus_int(report.get("aggregate_tagfile_ptch_patch_site_count")),
            "resolved": _hkx_corpus_int(report.get("aggregate_tagfile_ptch_resolved_patch_site_count")),
            "unresolved": _hkx_corpus_int(report.get("aggregate_tagfile_ptch_unresolved_patch_site_count")),
            "null": _hkx_corpus_int(report.get("aggregate_tagfile_ptch_null_patch_site_count")),
            "target_status_counts": dict(report.get("aggregate_tagfile_ptch_target_status_counts"))
            if isinstance(report.get("aggregate_tagfile_ptch_target_status_counts"), Mapping)
            else {},
        },
        "reference_parity_summary": {
            "havok_xml_reference_categories": dict(report.get("aggregate_havok_xml_reference_category_counts"))
            if isinstance(report.get("aggregate_havok_xml_reference_category_counts"), Mapping)
            else {},
            "havok_xml_reference_resolution_sources": dict(
                report.get("aggregate_havok_xml_reference_resolution_source_counts")
            )
            if isinstance(report.get("aggregate_havok_xml_reference_resolution_source_counts"), Mapping)
            else {},
        },
        "top_ptch_match_kinds": _hkx_corpus_sorted_count_rows(
            report.get("aggregate_ptch_payload_match_kind_counts")
        ),
        "top_ptch_reference_categories": _hkx_corpus_sorted_count_rows(
            report.get("aggregate_ptch_semantics_reference_category_counts")
        ),
        "top_packed_varuint_statuses": _hkx_corpus_sorted_count_rows(
            report.get("aggregate_ptch_varuint_status_counts")
        ),
    }
    if source_path is not None:
        try:
            evidence["source_report_size"] = Path(source_path).stat().st_size
        except OSError:
            evidence["source_report_size"] = None
    return evidence


def load_hkx_corpus_evidence_json(path: Path | str) -> Dict[str, object]:
    """Load an existing .hkx-corpus.json report and return only compact decoder evidence."""

    report_path = Path(path)
    with report_path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, Mapping):
        raise ValueError("HKX corpus report JSON root must be an object.")
    return build_hkx_corpus_evidence_from_report(report, source_path=report_path)
