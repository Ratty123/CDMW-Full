from __future__ import annotations

import csv
import io
import json
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_corpus_evidence import build_hkx_corpus_evidence_from_report
from cdmw.core.archive_hkx_corpus_files import scan_hkx_corpus_files
from cdmw.core.archive_hkx_corpus_planning import (
    _HKX_CORPUS_ROLE_LABELS,
    _HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES,
    _hkx_hard_decoder_corpus_proof_document,
    _hkx_ptch_semantics_proof_document,
    _hkx_representative_real_corpus_plan_document,
    _hkx_select_balanced_corpus_paths,
)
from cdmw.core.archive_hkx_corpus_scan import HkxCorpusScanState, _hkx_descriptor_hints_by_stem
from cdmw.core.common import raise_if_cancelled
from cdmw.models import RunCancelled


_HKX_CORPUS_DEFAULT_DETAIL_LIMIT = 1_000
_HKX_CORPUS_DEFAULT_ROUNDTRIP_LIMIT = 32


def _hkx_resolve_corpus_limit(
    value: Optional[int],
    env_name: str,
    default: int,
    *,
    nonnegative: bool = False,
) -> int:
    raw_value: object = value
    if value is None:
        env_value = os.environ.get(env_name)
        raw_value = env_value if env_value is not None and str(env_value).strip() else default
    try:
        resolved = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        resolved = default
    return max(0, resolved) if nonnegative else resolved


def _hkx_native_corpus_preflight(
    paths: Sequence[Path | str],
    discovery_limit: int,
    detail_scan_limit: int,
    *,
    stop_event: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, int, str], None]],
) -> Optional[Dict[str, object]]:
    try:
        from cdmw.core.hkx_native import scan_hkx_corpus_with_rust

        raise_if_cancelled(stop_event)
        if progress_callback is not None:
            progress_callback(0, 0, "Running native HKX corpus preflight...")
        candidates = [value for value in (discovery_limit, detail_scan_limit) if int(value) > 0]
        native_scan = scan_hkx_corpus_with_rust(
            paths,
            mode="corpus-stats-json",
            max_files=min(candidates) if candidates else None,
            timeout_seconds=60.0,
            stop_event=stop_event,
        )
        return dict(native_scan) if isinstance(native_scan, Mapping) else None
    except RunCancelled:
        raise
    except Exception:
        return None


def _hkx_discover_corpus_paths(
    paths: Sequence[Path | str],
    discovery_limit: int,
    *,
    stop_event: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, int, str], None]],
) -> List[Path]:
    hkx_paths: List[Path] = []
    for raw_path in paths:
        raise_if_cancelled(stop_event)
        if discovery_limit > 0 and len(hkx_paths) >= discovery_limit:
            break
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() == ".hkx":
            hkx_paths.append(path)
        elif path.is_dir():
            if progress_callback is not None:
                progress_callback(len(hkx_paths), discovery_limit or 0, f"Discovering .hkx files in {path}...")
            if discovery_limit > 0:
                for candidate in path.rglob("*.hkx"):
                    raise_if_cancelled(stop_event)
                    if candidate.is_file():
                        hkx_paths.append(candidate)
                        if len(hkx_paths) >= discovery_limit:
                            break
            else:
                discovered: List[Path] = []
                for candidate in path.rglob("*.hkx"):
                    raise_if_cancelled(stop_event)
                    if candidate.is_file():
                        discovered.append(candidate)
                        if progress_callback is not None and len(discovered) % 250 == 0:
                            progress_callback(len(discovered), 0, f"Discovered {len(discovered):,} HKX file(s)...")
                hkx_paths.extend(sorted(discovered))
    hkx_paths = sorted(dict.fromkeys(hkx_paths), key=lambda item: str(item).casefold())
    return hkx_paths[:discovery_limit] if discovery_limit > 0 and len(hkx_paths) > discovery_limit else hkx_paths


def _hkx_corpus_qualification(
    state: HkxCorpusScanState,
    roundtrip_limit: int,
    roundtrip_scan_limited: bool,
) -> Dict[str, object]:
    rows = state.rows
    ok_rows = [row for row in rows if row.get("ok") is True]
    role_status: Dict[str, Dict[str, object]] = {}
    missing_roles: List[str] = []
    incomplete_roles: List[str] = []
    for role in _HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES:
        count = int(state.aggregate_role_counts[role])
        roundtrip_count = int(state.aggregate_role_roundtrip_counts[role])
        covered = count > 0
        roundtrip_complete = covered and roundtrip_count == count
        if not covered:
            missing_roles.append(role)
        elif not roundtrip_complete:
            incomplete_roles.append(role)
        role_status[role] = {
            "label": _HKX_CORPUS_ROLE_LABELS.get(role, role),
            "required_for_full_compatibility": True,
            "covered": covered,
            "file_count": count,
            "roundtrip_identical_count": roundtrip_count,
            "roundtrip_complete": roundtrip_complete,
            "examples": list(state.role_examples.get(role, [])),
        }
    result: Dict[str, object] = {
        "status": "partial_converter_candidate",
        "all_files_exported": bool(rows) and len(ok_rows) == len(rows),
        "all_unknown_data_preserved": bool(ok_rows)
        and all(row.get("raw_records_cover_items") is True for row in ok_rows),
        "all_no_edit_json_roundtrips_identical": bool(ok_rows)
        and all(row.get("no_edit_json_roundtrip_identical") is True for row in ok_rows),
        "all_no_edit_xml_roundtrips_identical": bool(ok_rows)
        and all(row.get("no_edit_xml_roundtrip_identical") is True for row in ok_rows),
        "has_editable_fixed_size_records": any(int(row.get("editable_record_count") or 0) > 0 for row in ok_rows),
        "has_correlated_descriptor_context": any(
            int(row.get("physics_body_context_body_count") or 0) > 0
            or int(row.get("physics_body_context_constraint_hint_count") or 0) > 0
            for row in ok_rows
        ),
        "has_in_hkx_shape_names": any(int(row.get("physics_shape_name_count") or 0) > 0 for row in ok_rows),
        "has_body_summary": any(int(row.get("physics_body_summary_count") or 0) > 0 for row in ok_rows),
        "has_constraint_summary": any(
            int(row.get("physics_constraint_summary_count") or 0) > 0 for row in ok_rows
        ),
        "has_editable_field_catalog": any(
            int(row.get("editable_field_catalog_count") or 0) > 0 for row in ok_rows
        ),
        "has_byte_patch_map": any(int(row.get("byte_patch_map_count") or 0) > 0 for row in ok_rows),
        "has_readable_mesh_details": any(int(row.get("mesh_detail_shape_count") or 0) > 0 for row in ok_rows),
        "has_cdmw_value_editable_or_preview_linked_file": any(
            str(row.get("cdmw_hkx_compatibility_status") or "") in {"value_editable", "preview_linked"}
            for row in ok_rows
        ),
        "representative_role_counts": dict(sorted(state.aggregate_role_counts.items())),
        "representative_role_roundtrip_counts": dict(sorted(state.aggregate_role_roundtrip_counts.items())),
        "roundtrip_file_limit": roundtrip_limit if roundtrip_limit > 0 else None,
        "roundtrip_scan_limited": roundtrip_scan_limited,
        "roundtrip_verified_file_count": sum(
            1 for row in rows if str(row.get("no_edit_roundtrip_status") or "") == "verified"
        ),
        "roundtrip_skipped_file_count": sum(1 for row in rows if bool(row.get("no_edit_roundtrip_skipped"))),
        "required_representative_roles": list(_HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES),
        "representative_role_status": role_status,
        "missing_representative_roles": missing_roles,
        "incomplete_roundtrip_roles": incomplete_roles,
        "representative_role_examples": {
            role: list(examples) for role, examples in sorted(state.role_examples.items())
        },
        "has_small_object_convex_sample": state.aggregate_role_counts["small_object_convex"] > 0,
        "has_cloak_or_meshphysics_sample": state.aggregate_role_counts["cloak_or_meshphysics"] > 0,
        "has_character_havokphysics_or_ragdoll_sample": state.aggregate_role_counts[
            "character_havokphysics_or_ragdoll"
        ]
        > 0,
        "has_mesh_shape_heavy_sample": state.aggregate_role_counts["mesh_shape_heavy"] > 0,
        "has_animation_or_metadata_sample": state.aggregate_role_counts["animation_or_metadata"] > 0,
        "description": (
            "Crimson Desert HKX converter qualification checks for this local corpus. Full qualification still "
            "depends on representative coverage across objects, character physics, attachments, and future animation samples."
        ),
    }
    result["meets_current_converter_baseline"] = all(
        bool(result[key])
        for key in (
            "all_files_exported",
            "all_unknown_data_preserved",
            "all_no_edit_json_roundtrips_identical",
            "all_no_edit_xml_roundtrips_identical",
            "has_editable_fixed_size_records",
        )
    )
    result["meets_full_representative_compatibility_gate"] = (
        bool(ok_rows) and result["meets_current_converter_baseline"] and not missing_roles and not incomplete_roles
    )
    result["compatibility_gate_status"] = (
        "full_representative_gate_passed"
        if result["meets_full_representative_compatibility_gate"]
        else "needs_more_representative_coverage"
    )
    return result


def _hkx_unknown_schema_priorities(state: HkxCorpusScanState) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    total_bytes = sum(state.aggregate_unknown_schema_byte_counts.values())
    byte_priorities = [
        {
            "priority_rank": index + 1,
            "type_name": type_name,
            "record_count": int(state.aggregate_unknown_schema_record_counts[type_name]),
            "raw_preserved_byte_count": int(byte_count),
            "raw_preserved_byte_share": float(byte_count / total_bytes) if total_bytes else 0.0,
        }
        for index, (type_name, byte_count) in enumerate(
            sorted(state.aggregate_unknown_schema_byte_counts.items(), key=lambda item: (-int(item[1]), item[0]))
        )
    ]
    total_records = sum(state.aggregate_unknown_schema_record_counts.values())
    frequency_priorities = [
        {
            "priority_rank": index + 1,
            "type_name": type_name,
            "record_count": int(record_count),
            "raw_preserved_byte_count": int(state.aggregate_unknown_schema_byte_counts[type_name]),
            "record_count_share": float(record_count / total_records) if total_records else 0.0,
        }
        for index, (type_name, record_count) in enumerate(
            sorted(state.aggregate_unknown_schema_record_counts.items(), key=lambda item: (-int(item[1]), item[0]))
        )
    ]
    return byte_priorities, frequency_priorities


def _hkx_ptch_remaining_priorities(state: HkxCorpusScanState) -> List[Dict[str, object]]:
    non_object_count = sum(
        int(count)
        for status, count in state.aggregate_tagfile_ptch_target_status_counts.items()
        if str(status) not in {"object", "null"}
    )
    remaining: Counter[str] = Counter()
    if state.aggregate_tagfile_ptch_unresolved_patch_site_count:
        remaining["unresolved_ptch_patch_sites"] = state.aggregate_tagfile_ptch_unresolved_patch_site_count
    if non_object_count:
        remaining["non_object_or_null_ptch_patch_sites"] = non_object_count
    known_match_kinds = {
        "ptch_length_word",
        "ptch_marker",
        "ptch_header_word",
        "ptch_patch_site_count",
        "ptch_object_patch_offset",
        "ptch_null_patch_offset",
    }
    for match_kind, count in state.aggregate_tagfile_fixup_match_counts.items():
        match_text = str(match_kind)
        if match_text.startswith("ptch_") and match_text not in known_match_kinds:
            remaining[f"match_kind:{match_text}"] += int(count)
    for category, count in state.aggregate_tagfile_fixup_reference_category_counts.items():
        category_text = str(category)
        if category_text in {"data_reference_candidate", "type_reference", "type_class_reference", "string_reference"}:
            remaining[f"reference_category:{category_text}"] += int(count)
    for case, count in state.aggregate_ptch_semantics_remaining_case_counts.items():
        remaining[str(case)] = max(int(remaining.get(str(case)) or 0), int(count))
    descriptions = {
        "unresolved_ptch_patch_sites": "PTCH patch-site offsets were decoded, but their patched slot values did not resolve to object or null targets.",
        "non_object_or_null_ptch_patch_sites": "PTCH patch sites with a target status outside the current object/null model.",
        "match_kind:ptch_payload_word": "Nested PTCH payload words outside the recognized header/count/site tuple shape.",
        "match_kind:ptch_data_offset": "PTCH payload words that look like DATA-relative object/data offsets rather than patch-site offsets.",
        "match_kind:ptch_type_index": "PTCH payload words that look like type-table references.",
        "match_kind:ptch_string_table_index": "PTCH payload words that look like string-table references.",
    }
    return [
        {
            "priority_rank": index + 1,
            "case": case,
            "count": int(count),
            "description": descriptions.get(case, "Remaining PTCH/fixup observation that needs corpus review."),
        }
        for index, (case, count) in enumerate(sorted(remaining.items(), key=lambda item: (-int(item[1]), item[0])))
    ]


def _hkx_corpus_proofs(
    state: HkxCorpusScanState,
    discovered_file_count: int,
    native_fast_scan: Optional[Mapping[str, object]],
    qualification: Dict[str, object],
    ptch_priorities: List[Dict[str, object]],
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    representative_gate_passed = bool(qualification["meets_full_representative_compatibility_gate"])
    ptch_proof = _hkx_ptch_semantics_proof_document(
        discovered_hkx_file_count=discovered_file_count,
        scanned_file_count=len(state.rows),
        representative_gate_passed=representative_gate_passed,
        aggregate_ptch_tuple_shape_counts=state.aggregate_ptch_tuple_shape_counts,
        aggregate_ptch_payload_match_kind_counts=state.aggregate_ptch_payload_match_kind_counts,
        aggregate_ptch_reference_category_counts=state.aggregate_ptch_semantics_reference_category_counts,
        aggregate_ptch_varuint_status_counts=state.aggregate_ptch_varuint_status_counts,
        aggregate_tagfile_ptch_target_status_counts=state.aggregate_tagfile_ptch_target_status_counts,
        aggregate_ptch_remaining_case_priorities=ptch_priorities,
    )
    qualification["ptch_semantics_proof_status"] = ptch_proof["status"]
    qualification["ptch_semantics_proven"] = bool(ptch_proof.get("proven"))
    hard_proof = _hkx_hard_decoder_corpus_proof_document(
        discovered_hkx_file_count=discovered_file_count,
        scanned_file_count=len(state.rows),
        representative_gate_passed=representative_gate_passed,
        aggregate_hard_decoder_target_counts=state.aggregate_hard_decoder_target_counts,
        aggregate_hard_decoder_target_byte_counts=state.aggregate_hard_decoder_target_byte_counts,
        aggregate_hard_decoder_target_status_counts=state.aggregate_hard_decoder_target_status_counts,
        native_fast_scan=native_fast_scan,
    )
    qualification["hard_decoder_corpus_proof_status"] = hard_proof["status"]
    qualification["hard_decoder_corpus_proven"] = bool(hard_proof.get("proven"))
    representative_plan = _hkx_representative_real_corpus_plan_document(
        discovered_hkx_file_count=discovered_file_count,
        scanned_file_count=len(state.rows),
        rows=state.rows,
        ptch_semantics_proof=ptch_proof,
        hard_decoder_corpus_proof=hard_proof,
    )
    qualification["required_representative_real_hkx_roles"] = list(
        representative_plan.get("required_roles") or []
    )
    qualification["representative_real_hkx_role_status"] = dict(representative_plan.get("role_status") or {})
    qualification["missing_representative_real_hkx_roles"] = list(
        representative_plan.get("missing_roles") or []
    )
    qualification["representative_real_hkx_corpus_status"] = representative_plan["status"]
    qualification["representative_real_hkx_corpus_ready"] = (
        representative_plan["status"] == "representative_real_corpus_ready"
    )
    return ptch_proof, hard_proof, representative_plan


def _hkx_corpus_report_document(
    state: HkxCorpusScanState,
    *,
    native_fast_scan: Optional[Dict[str, object]],
    discovered_file_count: int,
    discovery_limit: int,
    discovery_scan_limited: bool,
    detail_scan_limit: int,
    roundtrip_limit: int,
    roundtrip_scan_limited: bool,
    qualification: Dict[str, object],
    ptch_proof: Dict[str, object],
    hard_proof: Dict[str, object],
    representative_plan: Dict[str, object],
    unknown_byte_priorities: List[Dict[str, object]],
    unknown_frequency_priorities: List[Dict[str, object]],
    ptch_priorities: List[Dict[str, object]],
    descriptor_hints_by_stem: Mapping[str, List[Dict[str, object]]],
) -> Dict[str, object]:
    rows = state.rows
    return {
        "format": "cdmw_hkx_converter_corpus_report_v1",
        "description": "Local Crimson Desert HKX converter corpus scan. Source files are not embedded.",
        "native_fast_scan": native_fast_scan,
        "discovered_file_count": discovered_file_count,
        "discovery_file_limit": discovery_limit if discovery_limit > 0 else None,
        "discovery_scan_limited": discovery_scan_limited,
        "detail_file_limit": detail_scan_limit if detail_scan_limit > 0 else None,
        "detail_scan_truncated": discovered_file_count > len(rows),
        "roundtrip_file_limit": roundtrip_limit if roundtrip_limit > 0 else None,
        "roundtrip_scan_limited": roundtrip_scan_limited,
        "roundtrip_verified_file_count": sum(
            1 for row in rows if str(row.get("no_edit_roundtrip_status") or "") == "verified"
        ),
        "roundtrip_skipped_file_count": sum(1 for row in rows if bool(row.get("no_edit_roundtrip_skipped"))),
        "file_count": len(rows),
        "ok_count": sum(1 for row in rows if row.get("ok") is True),
        "error_count": sum(1 for row in rows if row.get("ok") is not True),
        "qualification": qualification,
        "ptch_semantics_proof": ptch_proof,
        "hard_decoder_corpus_proof": hard_proof,
        "representative_real_hkx_corpus_plan": representative_plan,
        "aggregate_type_counts": dict(sorted(state.aggregate_type_counts.items())),
        "aggregate_record_status_counts": dict(sorted(state.aggregate_status_counts.items())),
        "aggregate_compatibility_status_counts": dict(
            sorted(state.aggregate_compatibility_status_counts.items())
        ),
        "aggregate_unknown_schema_type_priorities": unknown_byte_priorities,
        "aggregate_unknown_schema_frequency_priorities": unknown_frequency_priorities,
        "aggregate_corpus_role_counts": dict(sorted(state.aggregate_role_counts.items())),
        "aggregate_corpus_role_roundtrip_counts": dict(sorted(state.aggregate_role_roundtrip_counts.items())),
        "aggregate_editable_effect_counts": dict(sorted(state.aggregate_editable_effect_counts.items())),
        "aggregate_mesh_detail_group_counts": dict(sorted(state.aggregate_mesh_detail_group_counts.items())),
        "aggregate_havok_xml_parity_totals": dict(sorted(state.aggregate_havok_xml_parity_totals.items())),
        "aggregate_havok_xml_reference_category_counts": dict(
            sorted(state.aggregate_havok_xml_reference_category_counts.items())
        ),
        "aggregate_havok_xml_reference_resolution_source_counts": dict(
            sorted(state.aggregate_havok_xml_reference_resolution_source_counts.items())
        ),
        "aggregate_havok_xml_root_methods": dict(sorted(state.aggregate_havok_xml_root_methods.items())),
        "aggregate_havok_xml_class_parity_counts": {
            class_name: dict(sorted(counts.items()))
            for class_name, counts in sorted(state.aggregate_havok_xml_class_parity_counts.items())
        },
        "aggregate_hkclass_metadata_readiness_status_counts": dict(
            sorted(state.aggregate_hkclass_metadata_readiness_status_counts.items())
        ),
        "aggregate_native_model_graph_status_counts": dict(
            sorted(state.aggregate_native_model_graph_status_counts.items())
        ),
        "aggregate_native_low_level_parse_status_counts": dict(
            sorted(state.aggregate_native_low_level_parse_status_counts.items())
        ),
        "aggregate_no_edit_binary_writer_status_counts": dict(
            sorted(state.aggregate_no_edit_binary_writer_status_counts.items())
        ),
        "aggregate_biggest_remaining_gate_status_counts": dict(
            sorted(state.aggregate_biggest_remaining_gate_status_counts.items())
        ),
        "aggregate_class_internals_status_counts": dict(
            sorted(state.aggregate_class_internals_status_counts.items())
        ),
        "aggregate_class_internals_target_counts": dict(
            sorted(state.aggregate_class_internals_target_counts.items())
        ),
        "aggregate_hard_decoder_target_status_counts": dict(
            sorted(state.aggregate_hard_decoder_target_status_counts.items())
        ),
        "aggregate_hard_decoder_target_counts": dict(sorted(state.aggregate_hard_decoder_target_counts.items())),
        "aggregate_hard_decoder_target_byte_counts": dict(
            sorted(state.aggregate_hard_decoder_target_byte_counts.items())
        ),
        "aggregate_gui_readiness_status_counts": dict(
            sorted(state.aggregate_gui_readiness_status_counts.items())
        ),
        "aggregate_gui_readiness_target_status_counts": dict(
            sorted(state.aggregate_gui_readiness_target_status_counts.items())
        ),
        "aggregate_hkclass_metadata_missing_counts": dict(
            sorted(state.aggregate_hkclass_metadata_missing_counts.items())
        ),
        "aggregate_tagfile_fixup_match_counts": dict(
            sorted(state.aggregate_tagfile_fixup_match_counts.items())
        ),
        "aggregate_tagfile_fixup_reference_category_counts": dict(
            sorted(state.aggregate_tagfile_fixup_reference_category_counts.items())
        ),
        "aggregate_tagfile_ptch_table_count": state.aggregate_tagfile_ptch_table_count,
        "aggregate_tagfile_ptch_patch_site_count": state.aggregate_tagfile_ptch_patch_site_count,
        "aggregate_tagfile_ptch_resolved_patch_site_count": state.aggregate_tagfile_ptch_resolved_patch_site_count,
        "aggregate_tagfile_ptch_null_patch_site_count": state.aggregate_tagfile_ptch_null_patch_site_count,
        "aggregate_tagfile_ptch_unresolved_patch_site_count": state.aggregate_tagfile_ptch_unresolved_patch_site_count,
        "aggregate_tagfile_ptch_target_status_counts": dict(
            sorted(state.aggregate_tagfile_ptch_target_status_counts.items())
        ),
        "aggregate_ptch_tuple_shape_counts": dict(sorted(state.aggregate_ptch_tuple_shape_counts.items())),
        "aggregate_ptch_payload_match_kind_counts": dict(
            sorted(state.aggregate_ptch_payload_match_kind_counts.items())
        ),
        "aggregate_ptch_semantics_reference_category_counts": dict(
            sorted(state.aggregate_ptch_semantics_reference_category_counts.items())
        ),
        "aggregate_ptch_varuint_status_counts": dict(sorted(state.aggregate_ptch_varuint_status_counts.items())),
        "aggregate_ptch_remaining_case_priorities": ptch_priorities,
        "descriptor_hint_count": sum(len(hints) for hints in descriptor_hints_by_stem.values()),
        "descriptor_hints_by_stem": dict(sorted(descriptor_hints_by_stem.items())),
        "files": rows,
    }


def build_hkx_converter_corpus_report(
    paths: Sequence[Path | str],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = None,
    roundtrip_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    """Scan local HKX files and summarize converter coverage.

    This is intended for uncommitted local game extracts and smoke testing; it does not write files.
    """

    discovery_limit = _hkx_resolve_corpus_limit(
        discovery_limit,
        "CDMW_HKX_CORPUS_DISCOVERY_LIMIT",
        0,
        nonnegative=True,
    )
    detail_scan_limit = _hkx_resolve_corpus_limit(
        detail_scan_limit,
        "CDMW_HKX_CORPUS_DETAIL_LIMIT",
        _HKX_CORPUS_DEFAULT_DETAIL_LIMIT,
    )
    roundtrip_limit = _hkx_resolve_corpus_limit(
        roundtrip_limit,
        "CDMW_HKX_CORPUS_ROUNDTRIP_LIMIT",
        _HKX_CORPUS_DEFAULT_ROUNDTRIP_LIMIT,
    )
    native_fast_scan = _hkx_native_corpus_preflight(
        paths,
        discovery_limit,
        detail_scan_limit,
        stop_event=stop_event,
        progress_callback=progress_callback,
    )
    hkx_paths = _hkx_discover_corpus_paths(
        paths,
        discovery_limit,
        stop_event=stop_event,
        progress_callback=progress_callback,
    )
    discovered_file_count = len(hkx_paths)
    discovery_scan_limited = discovery_limit > 0 and discovered_file_count >= discovery_limit
    if detail_scan_limit > 0 and len(hkx_paths) > detail_scan_limit:
        if progress_callback is not None:
            progress_callback(0, len(hkx_paths), "Selecting balanced representative HKX files for detailed scan...")
        hkx_paths = _hkx_select_balanced_corpus_paths(hkx_paths, detail_scan_limit, stop_event=stop_event)
    roundtrip_scan_limited = roundtrip_limit > 0 and len(hkx_paths) > roundtrip_limit
    descriptor_hints_by_stem = _hkx_descriptor_hints_by_stem(
        paths,
        {path.stem for path in hkx_paths},
        stop_event=stop_event,
    )
    state = HkxCorpusScanState()
    scan_hkx_corpus_files(
        hkx_paths,
        descriptor_hints_by_stem,
        roundtrip_limit,
        state,
        stop_event=stop_event,
        progress_callback=progress_callback,
    )
    qualification = _hkx_corpus_qualification(state, roundtrip_limit, roundtrip_scan_limited)
    unknown_bytes, unknown_frequency = _hkx_unknown_schema_priorities(state)
    ptch_priorities = _hkx_ptch_remaining_priorities(state)
    ptch_proof, hard_proof, representative_plan = _hkx_corpus_proofs(
        state,
        discovered_file_count,
        native_fast_scan,
        qualification,
        ptch_priorities,
    )
    report = _hkx_corpus_report_document(
        state,
        native_fast_scan=native_fast_scan,
        discovered_file_count=discovered_file_count,
        discovery_limit=discovery_limit,
        discovery_scan_limited=discovery_scan_limited,
        detail_scan_limit=detail_scan_limit,
        roundtrip_limit=roundtrip_limit,
        roundtrip_scan_limited=roundtrip_scan_limited,
        qualification=qualification,
        ptch_proof=ptch_proof,
        hard_proof=hard_proof,
        representative_plan=representative_plan,
        unknown_byte_priorities=unknown_bytes,
        unknown_frequency_priorities=unknown_frequency,
        ptch_priorities=ptch_priorities,
        descriptor_hints_by_stem=descriptor_hints_by_stem,
    )
    report["corpus_evidence"] = build_hkx_corpus_evidence_from_report(report)
    return report


def build_hkx_converter_corpus_json(
    paths: Sequence[Path | str],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = None,
    roundtrip_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_hkx_converter_corpus_report(
            paths,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            roundtrip_limit=roundtrip_limit,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
        sort_keys=True,
    )


def build_hkx_converter_corpus_csv(
    paths: Sequence[Path | str],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = None,
    roundtrip_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    report = build_hkx_converter_corpus_report(
        paths,
        discovery_limit=discovery_limit,
        detail_scan_limit=detail_scan_limit,
        roundtrip_limit=roundtrip_limit,
        stop_event=stop_event,
        progress_callback=progress_callback,
    )
    output = io.StringIO()
    fieldnames = (
        "path",
        "ok",
        "size",
        "corpus_role",
        "sdk_version",
        "cdmw_hkx_compatibility_status",
        "type_count",
        "item_record_count",
        "editable_record_count",
        "decoded_or_partial_record_count",
        "decoded_coverage",
        "raw_record_count",
        "raw_records_cover_items",
        "no_edit_json_roundtrip_identical",
        "no_edit_xml_roundtrip_identical",
        "no_edit_roundtrip_status",
        "no_edit_roundtrip_skipped",
        "scan_seconds",
        "record_status_counts",
        "unknown_schema_areas",
        "companion_descriptor_hint_count",
        "physics_shape_name_count",
        "physics_named_collision_shape_count",
        "physics_body_summary_count",
        "physics_constraint_summary_count",
        "editable_field_catalog_count",
        "byte_patch_map_count",
        "editable_field_effect_counts",
        "mesh_shape_count",
        "mesh_detail_shape_count",
        "mesh_detail_group_counts",
        "hkx_xml_parity_summary",
        "hkclass_metadata_readiness_summary",
        "tagfile_reference_fixup_summary",
        "fixup_semantics_summary",
        "physics_body_context_body_count",
        "physics_body_context_constraint_hint_count",
        "physics_body_context_matched_shape_count",
        "error",
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    files = report.get("files")
    if isinstance(files, list):
        for row in files:
            if not isinstance(row, Mapping):
                continue
            csv_row = {key: row.get(key, "") for key in fieldnames}
            if isinstance(csv_row.get("editable_field_effect_counts"), Mapping):
                csv_row["editable_field_effect_counts"] = json.dumps(
                    csv_row["editable_field_effect_counts"],
                    sort_keys=True,
                    separators=(",", ":"),
                )
            for json_field in (
                "record_status_counts",
                "unknown_schema_areas",
                "mesh_detail_group_counts",
                "hkx_xml_parity_summary",
                "hkclass_metadata_readiness_summary",
                "tagfile_reference_fixup_summary",
                "fixup_semantics_summary",
            ):
                if isinstance(csv_row.get(json_field), (Mapping, list)):
                    csv_row[json_field] = json.dumps(
                        csv_row[json_field],
                        sort_keys=True,
                        separators=(",", ":"),
                    )
            writer.writerow(csv_row)
    return output.getvalue()
