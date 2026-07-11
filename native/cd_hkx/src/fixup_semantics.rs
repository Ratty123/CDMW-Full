use crate::*;

pub(crate) fn parse_fixup_section(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
    type_infos: &[TypeInfo],
    type_names: &[String],
    string_table_names: &[String],
    section_name: &str,
) -> Option<TagfileFixupSection> {
    let section_item = tag_item_by_name(items, section_name)?;
    let payload = tag_item_payload(data, items, section_name).unwrap_or(&[]);
    let section_payload_start = section_item.offset.saturating_add(4);
    let section_payload_end = section_payload_start.saturating_add(payload.len());
    let nested = |name| {
        tag_item_by_name(items, name).filter(|item| {
            item.length_word_offset.is_some_and(|offset| {
                offset >= section_payload_start && offset < section_payload_end
            }) || (item.offset >= section_payload_start && item.offset < section_payload_end)
        })
    };
    let nested_item = nested("ITEM");
    let nested_ptch = nested("PTCH");
    let word_count = payload.len() / 4;
    let shown_word_count = word_count.min(256);
    let mut words = Vec::new();
    let mut match_kind_counts = BTreeMap::<String, usize>::new();
    let mut reference_category_counts = BTreeMap::<String, usize>::new();
    let ptch_tables = nested_ptch
        .and_then(|item| decode_nested_ptch_table(data, section_item, item, records))
        .map(|table| vec![table])
        .unwrap_or_default();
    for word_index in 0..shown_word_count {
        let offset = word_index * 4;
        let value = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
        let word = nested_item
            .and_then(|item| {
                nested_item_word_match(word_index, offset, value, section_item, item, records)
            })
            .or_else(|| {
                nested_ptch.and_then(|item| {
                    nested_ptch_word_match(
                        data,
                        word_index,
                        offset,
                        value,
                        section_item,
                        item,
                        records,
                        type_infos,
                        type_names,
                        string_table_names,
                    )
                })
            })
            .unwrap_or_else(|| {
                match_fixup_word(
                    word_index,
                    offset,
                    value,
                    section_name,
                    records,
                    type_infos,
                    type_names,
                    string_table_names,
                )
            });
        increment_count(&mut match_kind_counts, &word.match_kind);
        increment_count(&mut reference_category_counts, &word.reference_category);
        words.push(word);
    }
    let resolved_references = words
        .iter()
        .filter(|word| {
            word.match_kind != "unresolved_word"
                && !matches!(
                    word.reference_category.as_str(),
                    "item_table_metadata"
                        | "item_count"
                        | "ptch_table_metadata"
                        | "patch_offset_candidate"
                )
        })
        .take(128)
        .cloned()
        .collect::<Vec<_>>();
    Some(TagfileFixupSection {
        name: section_name.to_string(),
        offset: section_item.offset,
        payload_byte_length: payload.len(),
        word_count,
        shown_word_count,
        truncated_word_count: word_count.saturating_sub(shown_word_count),
        record_offset_match_count: match_kind_counts.get("data_offset").copied().unwrap_or(0)
            + match_kind_counts
                .get("item_data_offset")
                .copied()
                .unwrap_or(0)
            + match_kind_counts
                .get("absolute_offset")
                .copied()
                .unwrap_or(0),
        null_word_count: match_kind_counts.get("null").copied().unwrap_or(0),
        type_index_match_count: match_kind_counts.get("type_index").copied().unwrap_or(0)
            + match_kind_counts
                .get("item_type_flags")
                .copied()
                .unwrap_or(0),
        string_table_index_match_count: match_kind_counts
            .get("string_table_index")
            .copied()
            .unwrap_or(0),
        ptch_tables,
        match_kind_counts,
        reference_category_counts,
        resolved_references,
        words,
    })
}

pub(crate) fn parse_tagfile_reference_fixups(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
    type_infos: &[TypeInfo],
    type_names: &[String],
    string_table_names: &[String],
) -> TagfileFixupSummary {
    let mut sections = Vec::new();
    let mut total_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut total_reference_category_counts = BTreeMap::<String, usize>::new();
    for section_name in ["INDX", "TPAD"] {
        let Some(section) = parse_fixup_section(
            data,
            items,
            records,
            type_infos,
            type_names,
            string_table_names,
            section_name,
        ) else {
            continue;
        };
        for (kind, count) in &section.match_kind_counts {
            increment_count_by(&mut total_match_kind_counts, kind, *count);
        }
        for (category, count) in &section.reference_category_counts {
            increment_count_by(&mut total_reference_category_counts, category, *count);
        }
        sections.push(section);
    }
    let ptch_table_count = sections
        .iter()
        .map(|section| section.ptch_tables.len())
        .sum::<usize>();
    let ptch_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.patch_site_count)
        .sum::<usize>();
    let ptch_resolved_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.resolved_patch_site_count)
        .sum::<usize>();
    let ptch_null_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.null_patch_site_count)
        .sum::<usize>();
    let ptch_unresolved_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.unresolved_patch_site_count)
        .sum::<usize>();
    TagfileFixupSummary {
        format: "cd_hkx_tagfile_reference_fixups_v1".to_string(),
        status: "experimental_observation".to_string(),
        imported: false,
        section_count: sections.len(),
        match_kind_counts: total_match_kind_counts,
        reference_category_counts: total_reference_category_counts,
        ptch_table_count,
        ptch_patch_site_count,
        ptch_resolved_patch_site_count,
        ptch_null_patch_site_count,
        ptch_unresolved_patch_site_count,
        sections,
    }
}

pub(crate) fn add_fixup_remaining_case(
    cases: &mut BTreeMap<String, (usize, String)>,
    case_name: &str,
    count: usize,
    description: &str,
) {
    if count == 0 {
        return;
    }
    let entry = cases
        .entry(case_name.to_string())
        .or_insert_with(|| (0, description.to_string()));
    entry.0 += count;
    if entry.1.is_empty() {
        entry.1 = description.to_string();
    }
}

pub(crate) fn finish_fixup_semantics_report(
    fixups: &TagfileFixupSummary,
    tuple_shape_counts: BTreeMap<String, usize>,
    payload_match_kind_counts: BTreeMap<String, usize>,
    reference_category_counts: BTreeMap<String, usize>,
    target_status_counts: BTreeMap<String, usize>,
    varuint_status_counts: BTreeMap<String, usize>,
    remaining_cases: BTreeMap<String, (usize, String)>,
    section_summaries: Vec<FixupSemanticsSectionSummary>,
) -> FixupSemanticsReport {
    let mut remaining_rows = remaining_cases
        .into_iter()
        .map(|(case_name, (count, description))| (case_name, count, description))
        .collect::<Vec<_>>();
    remaining_rows.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    let ptch_remaining_case_priorities = remaining_rows
        .into_iter()
        .enumerate()
        .map(
            |(index, (case_name, count, description))| FixupSemanticsRemainingCase {
                priority_rank: index + 1,
                case_name,
                count,
                description,
            },
        )
        .collect::<Vec<_>>();
    FixupSemanticsReport {
        format: "cd_hkx_fixup_semantics_report_v1".to_string(),
        status: "experimental_observation".to_string(),
        imported: false,
        ptch_table_count: fixups.ptch_table_count,
        ptch_patch_site_count: fixups.ptch_patch_site_count,
        ptch_object_patch_site_count: fixups.ptch_resolved_patch_site_count,
        ptch_null_patch_site_count: fixups.ptch_null_patch_site_count,
        ptch_unresolved_patch_site_count: fixups.ptch_unresolved_patch_site_count,
        ptch_tuple_shape_counts: tuple_shape_counts,
        ptch_payload_match_kind_counts: payload_match_kind_counts,
        ptch_reference_category_counts: reference_category_counts,
        ptch_target_status_counts: target_status_counts,
        varuint_status_counts,
        ptch_remaining_case_priorities,
        section_summaries,
    }
}

pub(crate) fn build_fixup_semantics_report(fixups: &TagfileFixupSummary) -> FixupSemanticsReport {
    let mut tuple_shape_counts = BTreeMap::<String, usize>::new();
    let mut payload_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut reference_category_counts = BTreeMap::<String, usize>::new();
    let mut target_status_counts = BTreeMap::<String, usize>::new();
    let mut varuint_status_counts = BTreeMap::<String, usize>::new();
    let mut remaining_cases = BTreeMap::<String, (usize, String)>::new();
    let mut section_summaries = Vec::new();
    let known_ptch_word_kinds = [
        "ptch_length_word",
        "ptch_marker",
        "ptch_header_word",
        "ptch_patch_site_count",
        "ptch_object_patch_offset",
        "ptch_null_patch_offset",
    ];
    let expected_tuple_shapes = ["1,1,0,2"];
    for section in &fixups.sections {
        for (kind, count) in &section.match_kind_counts {
            if kind.starts_with("ptch_") {
                increment_count_by(&mut payload_match_kind_counts, kind, *count);
                if !known_ptch_word_kinds.contains(&kind.as_str()) {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("ptch_match_kind:{kind}"),
                        *count,
                        "PTCH payload word matched a non-header/non-object shape that still needs corpus proof.",
                    );
                }
            }
        }
        for (category, count) in &section.reference_category_counts {
            increment_count_by(&mut reference_category_counts, category, *count);
            if matches!(
                category.as_str(),
                "data_reference_candidate"
                    | "string_reference"
                    | "type_reference"
                    | "type_class_reference"
                    | "patch_offset_candidate"
                    | "unresolved_fixup_word"
            ) {
                add_fixup_remaining_case(
                    &mut remaining_cases,
                    &format!("reference_category:{category}"),
                    *count,
                    "Observed reference category is not yet promoted into a full Havok fixup semantic.",
                );
            }
        }
        increment_count(&mut varuint_status_counts, "native_not_decoded");
        add_fixup_remaining_case(
            &mut remaining_cases,
            "varuint_status:native_not_decoded",
            1,
            "Native PTCH/fixup parser does not yet model section varuint streams.",
        );
        let mut patch_site_count = 0usize;
        let mut resolved_site_count = 0usize;
        let mut unresolved_site_count = 0usize;
        for table in &section.ptch_tables {
            let shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            increment_count(&mut tuple_shape_counts, &shape);
            if !expected_tuple_shapes.contains(&shape.as_str()) {
                add_fixup_remaining_case(
                    &mut remaining_cases,
                    &format!("ptch_tuple_shape:{shape}"),
                    1,
                    "PTCH table header shape differs from the currently verified object/null patch tuple.",
                );
            }
            patch_site_count += table.patch_site_count;
            resolved_site_count += table.resolved_patch_site_count + table.null_patch_site_count;
            unresolved_site_count += table.unresolved_patch_site_count;
            for site in &table.patch_sites {
                let target_status = if site.target_status.is_empty() {
                    "unresolved"
                } else {
                    site.target_status.as_str()
                };
                increment_count(&mut target_status_counts, target_status);
                if !site.reference_category.is_empty() {
                    increment_count(&mut reference_category_counts, &site.reference_category);
                }
                if target_status == "unresolved" {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        "unresolved_ptch_patch_site",
                        1,
                        "PTCH patch-site offset was found but its patched slot value was not resolved to null or an ITEM record.",
                    );
                } else if !matches!(target_status, "object" | "null") {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("non_object_ptch_patch_site:{target_status}"),
                        1,
                        "PTCH patch site resolved to a target status that is not yet modeled as object/null.",
                    );
                }
                if !site.reference_category.is_empty()
                    && !matches!(
                        site.reference_category.as_str(),
                        "object_reference" | "null_reference"
                    )
                {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("patch_site_reference_category:{}", site.reference_category),
                        1,
                        "PTCH patch site carries a non-object/null reference category that needs dedicated semantics.",
                    );
                }
            }
        }
        section_summaries.push(FixupSemanticsSectionSummary {
            name: section.name.clone(),
            payload_byte_length: section.payload_byte_length,
            word_count: section.word_count,
            ptch_table_count: section.ptch_tables.len(),
            ptch_patch_site_count: patch_site_count,
            ptch_patch_site_resolved_count: resolved_site_count,
            ptch_patch_site_unresolved_count: unresolved_site_count,
            match_kind_counts: section.match_kind_counts.clone(),
            reference_category_counts: section.reference_category_counts.clone(),
        });
    }
    finish_fixup_semantics_report(
        fixups,
        tuple_shape_counts,
        payload_match_kind_counts,
        reference_category_counts,
        target_status_counts,
        varuint_status_counts,
        remaining_cases,
        section_summaries,
    )
}
