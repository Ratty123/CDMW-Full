from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from cdmw.core.archive_hkx_descriptor import _hkx_descriptor_hint_from_root
from cdmw.core.common import raise_if_cancelled


def _hkx_descriptor_hint_document(path: Path) -> Optional[Dict[str, object]]:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    return _hkx_descriptor_hint_from_root(root, str(path))


def _hkx_descriptor_hints_by_stem(
    paths: Sequence[Path | str],
    hkx_stems: set[str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, List[Dict[str, object]]]:
    descriptor_paths: List[Path] = []
    for raw_path in paths:
        raise_if_cancelled(stop_event)
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() == ".xml":
            descriptor_paths.append(path)
        elif path.is_dir():
            for candidate in path.rglob("*.xml"):
                raise_if_cancelled(stop_event)
                candidate_text = str(candidate).casefold()
                if candidate.stem in hkx_stems or "physics" in candidate_text:
                    descriptor_paths.append(candidate)
    hints_by_stem: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for path in sorted(dict.fromkeys(descriptor_paths), key=lambda item: str(item).casefold()):
        raise_if_cancelled(stop_event)
        hint = _hkx_descriptor_hint_document(path)
        if hint is not None:
            hints_by_stem[path.stem].append(hint)
    return dict(hints_by_stem)


@dataclass
class HkxCorpusScanState:
    rows: List[Dict[str, object]] = field(default_factory=list)
    aggregate_type_counts: Counter[str] = field(default_factory=Counter)
    aggregate_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_compatibility_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_editable_effect_counts: Counter[str] = field(default_factory=Counter)
    aggregate_mesh_detail_group_counts: Counter[str] = field(default_factory=Counter)
    aggregate_unknown_schema_record_counts: Counter[str] = field(default_factory=Counter)
    aggregate_unknown_schema_byte_counts: Counter[str] = field(default_factory=Counter)
    aggregate_role_counts: Counter[str] = field(default_factory=Counter)
    aggregate_role_roundtrip_counts: Counter[str] = field(default_factory=Counter)
    aggregate_havok_xml_parity_totals: Counter[str] = field(default_factory=Counter)
    aggregate_havok_xml_reference_category_counts: Counter[str] = field(default_factory=Counter)
    aggregate_havok_xml_reference_resolution_source_counts: Counter[str] = field(default_factory=Counter)
    aggregate_havok_xml_root_methods: Counter[str] = field(default_factory=Counter)
    aggregate_havok_xml_class_parity_counts: Dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    aggregate_hkclass_metadata_readiness_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_native_model_graph_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_native_low_level_parse_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_no_edit_binary_writer_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_biggest_remaining_gate_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_class_internals_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_class_internals_target_counts: Counter[str] = field(default_factory=Counter)
    aggregate_hard_decoder_target_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_hard_decoder_target_counts: Counter[str] = field(default_factory=Counter)
    aggregate_hard_decoder_target_byte_counts: Counter[str] = field(default_factory=Counter)
    aggregate_gui_readiness_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_gui_readiness_target_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_hkclass_metadata_missing_counts: Counter[str] = field(default_factory=Counter)
    aggregate_tagfile_fixup_match_counts: Counter[str] = field(default_factory=Counter)
    aggregate_tagfile_fixup_reference_category_counts: Counter[str] = field(default_factory=Counter)
    aggregate_tagfile_ptch_target_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_ptch_tuple_shape_counts: Counter[str] = field(default_factory=Counter)
    aggregate_ptch_payload_match_kind_counts: Counter[str] = field(default_factory=Counter)
    aggregate_ptch_semantics_reference_category_counts: Counter[str] = field(default_factory=Counter)
    aggregate_ptch_varuint_status_counts: Counter[str] = field(default_factory=Counter)
    aggregate_ptch_semantics_remaining_case_counts: Counter[str] = field(default_factory=Counter)
    aggregate_tagfile_ptch_table_count: int = 0
    aggregate_tagfile_ptch_patch_site_count: int = 0
    aggregate_tagfile_ptch_resolved_patch_site_count: int = 0
    aggregate_tagfile_ptch_null_patch_site_count: int = 0
    aggregate_tagfile_ptch_unresolved_patch_site_count: int = 0
    role_examples: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))


def _hkx_tagfile_reference_fixup_summary(
    tagfile_reference_fixups: object,
    state: HkxCorpusScanState,
) -> Dict[str, object]:
    if not isinstance(tagfile_reference_fixups, Mapping):
        return {}
    section_summaries: List[Dict[str, object]] = []
    total_words = 0
    total_record_offset_matches = 0
    total_unresolved_words = 0
    total_ptch_table_count = int(tagfile_reference_fixups.get("ptch_table_count") or 0)
    total_ptch_patch_site_count = int(tagfile_reference_fixups.get("ptch_patch_site_count") or 0)
    total_ptch_resolved_patch_site_count = int(
        tagfile_reference_fixups.get("ptch_resolved_patch_site_count") or 0
    )
    total_ptch_null_patch_site_count = int(tagfile_reference_fixups.get("ptch_null_patch_site_count") or 0)
    total_ptch_unresolved_patch_site_count = int(
        tagfile_reference_fixups.get("ptch_unresolved_patch_site_count") or 0
    )
    state.aggregate_tagfile_ptch_table_count += total_ptch_table_count
    state.aggregate_tagfile_ptch_patch_site_count += total_ptch_patch_site_count
    state.aggregate_tagfile_ptch_resolved_patch_site_count += total_ptch_resolved_patch_site_count
    state.aggregate_tagfile_ptch_null_patch_site_count += total_ptch_null_patch_site_count
    state.aggregate_tagfile_ptch_unresolved_patch_site_count += total_ptch_unresolved_patch_site_count
    sections = tagfile_reference_fixups.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            try:
                total_words += int(section.get("word_count") or 0)
                total_record_offset_matches += int(section.get("record_offset_match_count") or 0)
            except (TypeError, ValueError, OverflowError):
                pass
            match_counts = section.get("match_kind_counts")
            if isinstance(match_counts, Mapping):
                for match_kind, count in match_counts.items():
                    try:
                        int_count = int(count or 0)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    state.aggregate_tagfile_fixup_match_counts[str(match_kind)] += int_count
                    if str(match_kind) == "unresolved_word":
                        total_unresolved_words += int_count
            words = section.get("words")
            if isinstance(words, list):
                for word in words:
                    if isinstance(word, Mapping) and str(word.get("reference_category") or ""):
                        state.aggregate_tagfile_fixup_reference_category_counts[
                            str(word.get("reference_category"))
                        ] += 1
            ptch_tables = section.get("ptch_tables")
            if isinstance(ptch_tables, list):
                for table in ptch_tables:
                    patch_sites = table.get("patch_sites") if isinstance(table, Mapping) else None
                    if isinstance(patch_sites, list):
                        for site in patch_sites:
                            status = str(site.get("target_status") or "") if isinstance(site, Mapping) else ""
                            if status:
                                state.aggregate_tagfile_ptch_target_status_counts[status] += 1
            section_summaries.append(
                {
                    "name": section.get("name"),
                    "word_count": section.get("word_count"),
                    "record_offset_match_count": section.get("record_offset_match_count"),
                    "null_word_count": section.get("null_word_count"),
                    "type_index_match_count": section.get("type_index_match_count"),
                    "string_table_index_match_count": section.get("string_table_index_match_count"),
                    "ptch_table_count": len(section.get("ptch_tables") or [])
                    if isinstance(section.get("ptch_tables"), list)
                    else 0,
                    "varuint_status": section.get("varuint_status"),
                }
            )
    return {
        "status": tagfile_reference_fixups.get("status"),
        "section_count": tagfile_reference_fixups.get("section_count"),
        "word_count": total_words,
        "record_offset_match_count": total_record_offset_matches,
        "unresolved_word_count": total_unresolved_words,
        "ptch_table_count": total_ptch_table_count,
        "ptch_patch_site_count": total_ptch_patch_site_count,
        "ptch_resolved_patch_site_count": total_ptch_resolved_patch_site_count,
        "ptch_null_patch_site_count": total_ptch_null_patch_site_count,
        "ptch_unresolved_patch_site_count": total_ptch_unresolved_patch_site_count,
        "sections": section_summaries[:8],
    }


def _hkx_fixup_semantics_summary(
    fixup_semantics_report: object,
    state: HkxCorpusScanState,
) -> Dict[str, object]:
    if not isinstance(fixup_semantics_report, Mapping):
        return {}
    for source_key, target_counter in (
        ("ptch_tuple_shape_counts", state.aggregate_ptch_tuple_shape_counts),
        ("ptch_payload_match_kind_counts", state.aggregate_ptch_payload_match_kind_counts),
        ("ptch_reference_category_counts", state.aggregate_ptch_semantics_reference_category_counts),
        ("varuint_status_counts", state.aggregate_ptch_varuint_status_counts),
    ):
        counts = fixup_semantics_report.get(source_key)
        if isinstance(counts, Mapping):
            for name, count in counts.items():
                try:
                    target_counter[str(name)] += int(count or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
    remaining_cases = fixup_semantics_report.get("ptch_remaining_case_priorities")
    if isinstance(remaining_cases, list):
        for case in remaining_cases:
            case_name = str(case.get("case") or "") if isinstance(case, Mapping) else ""
            if not case_name:
                continue
            try:
                state.aggregate_ptch_semantics_remaining_case_counts[case_name] += int(case.get("count") or 0)
            except (TypeError, ValueError, OverflowError):
                continue
    return {
        "status": fixup_semantics_report.get("status"),
        "ptch_table_count": fixup_semantics_report.get("ptch_table_count"),
        "ptch_patch_site_count": fixup_semantics_report.get("ptch_patch_site_count"),
        "ptch_object_patch_site_count": fixup_semantics_report.get("ptch_object_patch_site_count"),
        "ptch_null_patch_site_count": fixup_semantics_report.get("ptch_null_patch_site_count"),
        "ptch_unresolved_patch_site_count": fixup_semantics_report.get("ptch_unresolved_patch_site_count"),
        "ptch_tuple_shape_counts": fixup_semantics_report.get("ptch_tuple_shape_counts") or {},
        "ptch_payload_match_kind_counts": fixup_semantics_report.get("ptch_payload_match_kind_counts") or {},
        "ptch_reference_category_counts": fixup_semantics_report.get("ptch_reference_category_counts") or {},
        "varuint_status_counts": fixup_semantics_report.get("varuint_status_counts") or {},
        "ptch_remaining_case_priorities": remaining_cases if isinstance(remaining_cases, list) else [],
    }


def _hkx_xml_parity_summary(parity_report: object, state: HkxCorpusScanState) -> Dict[str, object]:
    if not isinstance(parity_report, Mapping):
        return {}
    summary: Dict[str, object] = {}
    for key in (
        "exact_fields_decoded",
        "layout_fields_available",
        "havok_like_params_emitted",
        "havok_named_params_emitted",
        "unknown_fields_preserved_as_cdmw_raw_metadata",
        "raw_preserved_byte_count",
        "references_resolved",
        "references_unresolved",
        "ptch_patch_sites_found",
        "ptch_patch_sites_resolved",
        "ptch_patch_sites_object_resolved",
        "ptch_patch_sites_null",
        "ptch_patch_sites_unresolved",
        "ptch_fixup_backed_references",
        "object_references_resolved_by_ptch",
        "object_references_resolved_by_inference",
    ):
        try:
            value = int(parity_report.get(key) or 0)
        except (TypeError, ValueError, OverflowError):
            value = 0
        state.aggregate_havok_xml_parity_totals[key] += value
        summary[key] = value
    for source_key, target_key, target_counter in (
        (
            "reference_category_counts",
            "reference_category_counts",
            state.aggregate_havok_xml_reference_category_counts,
        ),
        (
            "reference_resolution_source_counts",
            "reference_resolution_source_counts",
            state.aggregate_havok_xml_reference_resolution_source_counts,
        ),
    ):
        counts = parity_report.get(source_key)
        if isinstance(counts, Mapping):
            summary[target_key] = dict(counts)
            for name, count in counts.items():
                try:
                    target_counter[str(name)] += int(count or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
    ptch_status_counts = parity_report.get("ptch_target_status_counts")
    if isinstance(ptch_status_counts, Mapping):
        summary["ptch_target_status_counts"] = dict(ptch_status_counts)
    fixup_fields = parity_report.get("fixup_backed_fields_by_class")
    if isinstance(fixup_fields, Mapping):
        summary["fixup_backed_fields_by_class"] = {
            str(class_name): list(fields)[:24] if isinstance(fields, list) else []
            for class_name, fields in fixup_fields.items()
        }
    root_object = parity_report.get("root_object")
    if isinstance(root_object, Mapping):
        root_method = str(root_object.get("method") or "")
        if root_method:
            state.aggregate_havok_xml_root_methods[root_method] += 1
        summary["root_object"] = {
            "toplevelobject": root_object.get("toplevelobject"),
            "class": root_object.get("class"),
            "method": root_method,
            "confidence": root_object.get("confidence"),
        }
    class_parity = parity_report.get("class_parity")
    if isinstance(class_parity, list):
        class_rows: List[Dict[str, object]] = []
        for class_row in class_parity:
            if not isinstance(class_row, Mapping):
                continue
            class_name = str(class_row.get("class") or "")
            confidence = str(class_row.get("parity_confidence") or "")
            if class_name and confidence:
                state.aggregate_havok_xml_class_parity_counts[class_name][confidence] += int(
                    class_row.get("object_count") or 1
                )
            if len(class_rows) < 24:
                class_rows.append(
                    {
                        "class": class_name,
                        "object_count": class_row.get("object_count"),
                        "emitted_param_count": class_row.get("emitted_param_count"),
                        "parity_confidence": confidence,
                        "resolved_reference_count": class_row.get("resolved_reference_count"),
                        "raw_metadata_param_count": class_row.get("raw_metadata_param_count"),
                    }
                )
        summary["class_parity"] = class_rows
    return summary
