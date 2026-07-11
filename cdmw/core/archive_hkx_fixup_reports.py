from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'HkxTagfileSummary',
    'List',
    '_hkx_process_fixup_section',
)
def _hkx_tagfile_reference_fixups_document(
    data: bytes,
    summary: HkxTagfileSummary,
    *,
    word_limit_per_section: int = 256,
    varuint_limit_per_section: int = 128,
) -> Dict[str, object]:
    record_by_data_offset = {
        int(record.data_offset): record
        for record in summary.item_records
        if int(record.data_offset) > 0
    }
    record_by_absolute_offset = {
        int(record.absolute_data_offset): record
        for record in summary.item_records
        if record.absolute_data_offset is not None and int(record.absolute_data_offset) > 0
    }
    type_name_by_index = {int(type_info.index): type_info.display_name for type_info in summary.type_infos}
    if not type_name_by_index:
        type_name_by_index = {index: name for index, name in enumerate(summary.type_names)}
    section_rows: List[Dict[str, object]] = []
    total_match_counts: Counter[str] = Counter()
    total_reference_category_counts: Counter[str] = Counter()
    state = {'total_ptch_table_count': 0, 'total_ptch_patch_site_count': 0, 'total_ptch_resolved_patch_site_count': 0, 'total_ptch_null_patch_site_count': 0, 'total_ptch_unresolved_patch_site_count': 0}
    for section_name in ("INDX", "TPAD"):
        _hkx_process_fixup_section(
            data, summary, section_name, record_by_data_offset, record_by_absolute_offset,
            type_name_by_index, section_rows, total_match_counts, total_reference_category_counts,
            state, word_limit_per_section, varuint_limit_per_section,
        )
    total_ptch_table_count, total_ptch_patch_site_count, total_ptch_resolved_patch_site_count, total_ptch_null_patch_site_count, total_ptch_unresolved_patch_site_count = (state['total_ptch_table_count'], state['total_ptch_patch_site_count'], state['total_ptch_resolved_patch_site_count'], state['total_ptch_null_patch_site_count'], state['total_ptch_unresolved_patch_site_count'])
    return {
        "format": "cdmw_hkx_tagfile_reference_fixups_v1",
        "status": "experimental_observation",
        "imported": False,
        "description": (
            "Read-only scan of tagfile reference/fixup-like sections. INDX semantics are not treated as editable yet; "
            "words are classified when they belong to nested ITEM descriptors, nested PTCH payloads, recovered ITEM offsets, TNA1 type indexes, strings, or nulls."
        ),
        "ptch_table_count": total_ptch_table_count,
        "ptch_patch_site_count": total_ptch_patch_site_count,
        "ptch_resolved_patch_site_count": total_ptch_resolved_patch_site_count,
        "ptch_null_patch_site_count": total_ptch_null_patch_site_count,
        "ptch_unresolved_patch_site_count": total_ptch_unresolved_patch_site_count,
        "match_kind_counts": dict(sorted(total_match_counts.items())),
        "reference_category_counts": dict(sorted(total_reference_category_counts.items())),
        "section_count": len(section_rows),
        "sections": section_rows,
    }


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'List',
    'Mapping',
    '_hkx_collect_fixup_semantics',
)
def _hkx_fixup_semantics_report_document(tagfile_reference_fixups: Mapping[str, object]) -> Dict[str, object]:
    sections = tagfile_reference_fixups.get("sections") if isinstance(tagfile_reference_fixups, Mapping) else None
    section_rows = sections if isinstance(sections, list) else []
    tuple_shape_counts: Counter[str] = Counter()
    payload_match_kind_counts: Counter[str] = Counter()
    reference_category_counts: Counter[str] = Counter()
    target_status_counts: Counter[str] = Counter()
    varuint_status_counts: Counter[str] = Counter()
    remaining_cases: Counter[str] = Counter()
    remaining_descriptions: Dict[str, str] = {}
    section_summaries: List[Dict[str, object]] = []
    expected_tuple_shapes = {"1,1,0,2"}
    known_ptch_word_kinds = {
        "ptch_length_word",
        "ptch_marker",
        "ptch_header_word",
        "ptch_patch_site_count",
        "ptch_object_patch_offset",
        "ptch_null_patch_offset",
    }
    _hkx_collect_fixup_semantics(
        section_rows, tuple_shape_counts, payload_match_kind_counts, reference_category_counts,
        target_status_counts, varuint_status_counts, remaining_cases, remaining_descriptions,
        section_summaries, expected_tuple_shapes, known_ptch_word_kinds,
    )
    remaining_case_rows = [
        {
            "priority_rank": index + 1,
            "case": case,
            "count": count,
            "description": remaining_descriptions.get(case, ""),
        }
        for index, (case, count) in enumerate(
            sorted(remaining_cases.items(), key=lambda item: (-int(item[1]), str(item[0])))
        )
    ]
    return {
        "format": "cdmw_hkx_fixup_semantics_report_v1",
        "status": "experimental_observation",
        "imported": False,
        "description": (
            "Read-only PTCH/INDX semantics tracker. It separates verified object/null PTCH patch sites from "
            "remaining tuple shapes and data/string/type-style candidates that still need corpus proof."
        ),
        "ptch_table_count": int(tagfile_reference_fixups.get("ptch_table_count") or 0)
        if isinstance(tagfile_reference_fixups, Mapping)
        else 0,
        "ptch_patch_site_count": int(tagfile_reference_fixups.get("ptch_patch_site_count") or 0)
        if isinstance(tagfile_reference_fixups, Mapping)
        else 0,
        "ptch_object_patch_site_count": int(tagfile_reference_fixups.get("ptch_resolved_patch_site_count") or 0)
        if isinstance(tagfile_reference_fixups, Mapping)
        else 0,
        "ptch_null_patch_site_count": int(tagfile_reference_fixups.get("ptch_null_patch_site_count") or 0)
        if isinstance(tagfile_reference_fixups, Mapping)
        else 0,
        "ptch_unresolved_patch_site_count": int(tagfile_reference_fixups.get("ptch_unresolved_patch_site_count") or 0)
        if isinstance(tagfile_reference_fixups, Mapping)
        else 0,
        "ptch_tuple_shape_counts": dict(sorted(tuple_shape_counts.items())),
        "ptch_payload_match_kind_counts": dict(sorted(payload_match_kind_counts.items())),
        "ptch_reference_category_counts": dict(sorted(reference_category_counts.items())),
        "ptch_target_status_counts": dict(sorted(target_status_counts.items())),
        "varuint_status_counts": dict(sorted(varuint_status_counts.items())),
        "ptch_remaining_case_priorities": remaining_case_rows,
        "section_summaries": section_summaries,
    }
