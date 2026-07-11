from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_decode_nested_ptch_table',
    '_hkx_tag_item_by_name',
    '_hkx_tag_item_payload',
)
def _hkx_fixup_section_context(data, summary, section_name, section_item, state):
    payload = _hkx_tag_item_payload(data, summary.tag_items, section_name)
    section_payload_start = int(section_item.offset) + 4
    section_payload_end = section_payload_start + len(payload)
    nested_item = _hkx_tag_item_by_name(summary.tag_items, 'ITEM')
    if nested_item is not None:
        nested_length_offset = int(nested_item.length_word_offset) if nested_item.length_word_offset is not None else None
        nested_marker_offset = int(nested_item.offset)
        if not (nested_length_offset is not None and section_payload_start <= nested_length_offset < section_payload_end or section_payload_start <= nested_marker_offset < section_payload_end):
            nested_item = None
    nested_ptch = _hkx_tag_item_by_name(summary.tag_items, 'PTCH')
    ptch_payload = b''
    if nested_ptch is not None:
        nested_length_offset = int(nested_ptch.length_word_offset) if nested_ptch.length_word_offset is not None else None
        nested_marker_offset = int(nested_ptch.offset)
        if not (nested_length_offset is not None and section_payload_start <= nested_length_offset < section_payload_end or section_payload_start <= nested_marker_offset < section_payload_end):
            nested_ptch = None
        else:
            ptch_payload = _hkx_tag_item_payload(data, summary.tag_items, 'PTCH')
    ptch_tables: List[Dict[str, object]] = []
    if nested_ptch is not None:
        ptch_table = _hkx_decode_nested_ptch_table(data, section_item=section_item, ptch_item=nested_ptch, records=summary.item_records)
        if ptch_table is not None:
            ptch_tables.append(ptch_table)
            state['total_ptch_table_count'] += 1
            state['total_ptch_patch_site_count'] += int(ptch_table.get('patch_site_count') or 0)
            state['total_ptch_resolved_patch_site_count'] += int(ptch_table.get('resolved_patch_site_count') or 0)
            state['total_ptch_null_patch_site_count'] += int(ptch_table.get('null_patch_site_count') or 0)
            state['total_ptch_unresolved_patch_site_count'] += int(ptch_table.get('unresolved_patch_site_count') or 0)
    return payload, nested_item, nested_ptch, ptch_payload, ptch_tables


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'List',
    'Mapping',
    '_hkx_hex',
    '_hkx_tagfile_fixup_word_match',
    '_hkx_tagfile_nested_item_word_match',
    '_hkx_tagfile_nested_ptch_word_match',
    'struct',
)
def _hkx_fixup_section_words(data, summary, section_name, section_item, payload, nested_item, nested_ptch, ptch_payload, record_by_data_offset, record_by_absolute_offset, type_name_by_index, total_match_counts, total_reference_category_counts, word_limit_per_section):
    words: List[Dict[str, object]] = []
    word_counts: Counter[str] = Counter()
    for word_index in range(min(len(payload) // 4, word_limit_per_section)):
        offset = word_index * 4
        value = struct.unpack_from("<I", payload, offset)[0]
        match = (
            _hkx_tagfile_nested_item_word_match(
                word_index,
                offset,
                int(value),
                section_item=section_item,
                item_item=nested_item,
                records=summary.item_records,
            )
            if nested_item is not None
            else None
        )
        if match is None and nested_ptch is not None:
            match = _hkx_tagfile_nested_ptch_word_match(
                data,
                word_index,
                offset,
                int(value),
                section_item=section_item,
                ptch_item=nested_ptch,
                ptch_payload=ptch_payload,
                records=summary.item_records,
                record_by_data_offset=record_by_data_offset,
                record_by_absolute_offset=record_by_absolute_offset,
                type_name_by_index=type_name_by_index,
                string_table_names=summary.string_table_names,
            )
        if match is None:
            match = _hkx_tagfile_fixup_word_match(
                int(value),
                section_name=section_name,
                record_by_data_offset=record_by_data_offset,
                record_by_absolute_offset=record_by_absolute_offset,
                type_name_by_index=type_name_by_index,
                string_table_names=summary.string_table_names,
            )
        match_kind = str(match.get("match_kind") or "unresolved_word")
        word_counts[match_kind] += 1
        total_match_counts[match_kind] += 1
        reference_category = str(match.get("reference_category") or "")
        if reference_category:
            total_reference_category_counts[reference_category] += 1
        words.append(
            {
                "index": word_index,
                "offset": offset,
                "hex_offset": f"0x{offset:X}",
                "value": int(value),
                "value_hex": _hkx_hex(int(value)),
                **match,
            }
        )
    reference_category_counts = Counter(str(word.get("reference_category") or "") for word in words if str(word.get("reference_category") or ""))
    resolved_references = [
        {
            "section": section_name,
            "offset": word.get("offset"),
            "hex_offset": word.get("hex_offset"),
            "value": word.get("value"),
            "match_kind": word.get("match_kind"),
            "reference_category": word.get("reference_category"),
            "target_record_index": word.get("target_record_index"),
            "target_type_name": word.get("target_type_name"),
            "target_type_index": word.get("target_type_index"),
            "target_string": word.get("target_string"),
            "owner_record_index": word.get("owner_record_index"),
            "owner_type_index": word.get("owner_type_index"),
            "owner_type_name": word.get("owner_type_name"),
            "owner_local_offset": word.get("owner_local_offset"),
            "patch_value": word.get("patch_value"),
            "target_status": word.get("target_status"),
            "confidence": word.get("confidence"),
        }
        for word in words
        if isinstance(word, Mapping)
        and str(word.get("match_kind") or "") not in {"unresolved_word"}
        and str(word.get("reference_category") or "") not in {"item_table_metadata", "item_count", "ptch_table_metadata", "patch_offset_candidate"}
    ][:128]
    return words, word_counts, reference_category_counts, resolved_references


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_hex',
    '_hkx_tagfile_fixup_word_match',
    '_read_hkx_var_uint',
)
def _hkx_fixup_section_varuint(summary, section_name, payload, record_by_data_offset, record_by_absolute_offset, type_name_by_index, varuint_limit_per_section):
    varuint_values: List[Dict[str, object]] = []
    cursor = 0
    varuint_status = "not_decoded" if not payload else "decoded_sample"
    while payload and cursor < len(payload) and len(varuint_values) < varuint_limit_per_section:
        start = cursor
        try:
            value, cursor = _read_hkx_var_uint(payload, cursor)
        except ValueError as exc:
            varuint_status = f"stopped: {exc}"
            break
        match = _hkx_tagfile_fixup_word_match(
            int(value),
            section_name=section_name,
            record_by_data_offset=record_by_data_offset,
            record_by_absolute_offset=record_by_absolute_offset,
            type_name_by_index=type_name_by_index,
            string_table_names=summary.string_table_names,
        )
        varuint_values.append(
            {
                "index": len(varuint_values),
                "offset": start,
                "hex_offset": f"0x{start:X}",
                "byte_length": cursor - start,
                "value": int(value),
                "value_hex": _hkx_hex(int(value)),
                **match,
            }
        )
    return varuint_values, varuint_status


@bind_archive_hkx_globals(
    '_hkx_fixup_section_context',
    '_hkx_fixup_section_varuint',
    '_hkx_fixup_section_words',
    '_hkx_tag_item_by_name',
)
def _hkx_process_fixup_section(data, summary, section_name, record_by_data_offset, record_by_absolute_offset, type_name_by_index, section_rows, total_match_counts, total_reference_category_counts, state, word_limit_per_section, varuint_limit_per_section):
    section_item = _hkx_tag_item_by_name(summary.tag_items, section_name)
    if section_item is None:
        return
    payload, nested_item, nested_ptch, ptch_payload, ptch_tables = _hkx_fixup_section_context(
        data, summary, section_name, section_item, state
    )
    words, word_counts, reference_category_counts, resolved_references = _hkx_fixup_section_words(
        data, summary, section_name, section_item, payload, nested_item, nested_ptch, ptch_payload,
        record_by_data_offset, record_by_absolute_offset, type_name_by_index,
        total_match_counts, total_reference_category_counts, word_limit_per_section,
    )
    varuint_values, varuint_status = _hkx_fixup_section_varuint(
        summary, section_name, payload, record_by_data_offset, record_by_absolute_offset,
        type_name_by_index, varuint_limit_per_section,
    )
    section_rows.append(
        {
            "name": section_name,
            "offset": section_item.offset,
            "payload_byte_length": len(payload),
            "word_count": len(payload) // 4,
            "shown_word_count": len(words),
            "truncated_word_count": max(0, (len(payload) // 4) - len(words)),
            "match_kind_counts": dict(sorted(word_counts.items())),
            "reference_category_counts": dict(sorted(reference_category_counts.items())),
            "record_offset_match_count": (
                int(word_counts.get("data_offset") or 0)
                + int(word_counts.get("absolute_offset") or 0)
                + int(word_counts.get("item_data_offset") or 0)
            ),
            "null_word_count": int(word_counts.get("null") or 0),
            "type_index_match_count": int(word_counts.get("type_index") or 0) + int(word_counts.get("item_type_flags") or 0),
            "string_table_index_match_count": int(word_counts.get("string_table_index") or 0),
            "ptch_tables": ptch_tables,
            "varuint_status": varuint_status,
            "varuint_values": varuint_values,
            "resolved_references": resolved_references,
            "words": words,
        }
    )


@bind_archive_hkx_globals()
def _hkx_fixup_add_case(remaining_cases, remaining_descriptions, case: str, count: int, description: str) -> None:
    if count <= 0:
        return
    remaining_cases[case] += int(count)
    remaining_descriptions.setdefault(case, description)


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_fixup_add_case',
)
def _hkx_collect_fixup_semantics(section_rows, tuple_shape_counts, payload_match_kind_counts, reference_category_counts, target_status_counts, varuint_status_counts, remaining_cases, remaining_descriptions, section_summaries, expected_tuple_shapes, known_ptch_word_kinds):
    for section in section_rows:
        if not isinstance(section, Mapping):
            continue
        section_name = str(section.get("name") or "")
        section_match_counts = section.get("match_kind_counts")
        section_ref_counts = section.get("reference_category_counts")
        if isinstance(section_match_counts, Mapping):
            for kind, raw_count in section_match_counts.items():
                try:
                    count = int(raw_count)
                except (TypeError, ValueError, OverflowError):
                    continue
                kind_text = str(kind or "")
                if kind_text.startswith("ptch_"):
                    payload_match_kind_counts[kind_text] += count
                    if kind_text not in known_ptch_word_kinds:
                        _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                            f"ptch_match_kind:{kind_text}",
                            count,
                            "PTCH payload word matched a non-header/non-object shape that still needs corpus proof.",
                        )
        if isinstance(section_ref_counts, Mapping):
            for category, raw_count in section_ref_counts.items():
                try:
                    count = int(raw_count)
                except (TypeError, ValueError, OverflowError):
                    continue
                category_text = str(category or "")
                if not category_text:
                    continue
                reference_category_counts[category_text] += count
                if category_text in {
                    "data_reference_candidate",
                    "string_reference",
                    "type_reference",
                    "type_class_reference",
                    "patch_offset_candidate",
                    "unresolved_fixup_word",
                }:
                    _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                        f"reference_category:{category_text}",
                        count,
                        "Observed reference category is not yet promoted into a full Havok fixup semantic.",
                    )
        varuint_status = str(section.get("varuint_status") or "")
        if varuint_status:
            varuint_status_counts[varuint_status] += 1
            if varuint_status not in {"decoded_sample", "not_decoded"}:
                _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                    f"varuint_status:{varuint_status}",
                    1,
                    "Varuint probe did not cleanly decode through the sampled section payload.",
                )
        ptch_tables = section.get("ptch_tables")
        table_count = 0
        patch_site_count = 0
        resolved_site_count = 0
        unresolved_site_count = 0
        if isinstance(ptch_tables, list):
            for table in ptch_tables:
                if not isinstance(table, Mapping):
                    continue
                table_count += 1
                header = table.get("header")
                if isinstance(header, list):
                    shape = ",".join(str(value) for value in header)
                    tuple_shape_counts[shape] += 1
                    if shape not in expected_tuple_shapes:
                        _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                            f"ptch_tuple_shape:{shape}",
                            1,
                            "PTCH table header shape differs from the currently verified object/null patch tuple.",
                        )
                try:
                    patch_site_count += int(table.get("patch_site_count") or 0)
                    resolved_site_count += int(table.get("resolved_patch_site_count") or 0) + int(table.get("null_patch_site_count") or 0)
                    unresolved_site_count += int(table.get("unresolved_patch_site_count") or 0)
                except (TypeError, ValueError, OverflowError):
                    pass
                patch_sites = table.get("patch_sites")
                if not isinstance(patch_sites, list):
                    continue
                for site in patch_sites:
                    if not isinstance(site, Mapping):
                        continue
                    target_status = str(site.get("target_status") or "unresolved")
                    target_status_counts[target_status] += 1
                    reference_category = str(site.get("reference_category") or "")
                    if reference_category:
                        reference_category_counts[reference_category] += 1
                    if target_status == "unresolved":
                        _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                            "unresolved_ptch_patch_site",
                            1,
                            "PTCH patch-site offset was found but its patched slot value was not resolved to null or an ITEM record.",
                        )
                    elif target_status not in {"object", "null"}:
                        _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                            f"non_object_ptch_patch_site:{target_status}",
                            1,
                            "PTCH patch site resolved to a target status that is not yet modeled as object/null.",
                        )
                    if reference_category and reference_category not in {"object_reference", "null_reference"}:
                        _hkx_fixup_add_case(remaining_cases, remaining_descriptions,
                            f"patch_site_reference_category:{reference_category}",
                            1,
                            "PTCH patch site carries a non-object/null reference category that needs dedicated semantics.",
                        )
        section_summaries.append(
            {
                "name": section_name,
                "payload_byte_length": section.get("payload_byte_length"),
                "word_count": section.get("word_count"),
                "ptch_table_count": table_count,
                "ptch_patch_site_count": patch_site_count,
                "ptch_patch_site_resolved_count": resolved_site_count,
                "ptch_patch_site_unresolved_count": unresolved_site_count,
                "varuint_status": varuint_status,
                "match_kind_counts": dict(section_match_counts) if isinstance(section_match_counts, Mapping) else {},
                "reference_category_counts": dict(section_ref_counts) if isinstance(section_ref_counts, Mapping) else {},
            }
        )
