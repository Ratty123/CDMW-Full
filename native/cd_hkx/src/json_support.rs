use crate::*;

pub(crate) fn json_escape(value: &str) -> String {
    let mut output = String::with_capacity(value.len() + 8);
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            c if c.is_control() => {
                let _ = write!(output, "\\u{:04x}", c as u32);
            }
            c => output.push(c),
        }
    }
    output
}

pub(crate) fn json_optional_u32(value: Option<u32>) -> String {
    value
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

pub(crate) fn json_optional_usize(value: Option<usize>) -> String {
    value
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

pub(crate) fn json_optional_f32(value: Option<f32>) -> String {
    value
        .filter(|item| item.is_finite())
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

pub(crate) fn json_optional_string(value: Option<&str>) -> String {
    value
        .map(|item| format!("\"{}\"", json_escape(item)))
        .unwrap_or_else(|| "null".to_string())
}

pub(crate) fn json_bool(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

pub(crate) fn push_no_edit_binary_writer_report_json(
    out: &mut String,
    report: &NoEditBinaryWriterReport,
) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"native_writer_status\":\"{}\",\"no_edit_roundtrip_mode\":\"{}\",\"read_model_write_pipeline\":\"{}\",\"available\":{},\"native_read_model_write_available\":{},\"parsed_model_available\":{},\"byte_identical\":{},\"byte_identical_no_edit_rebuild_supported\":{},\"semantic_rebuild_supported\":{},\"havok_xml_import_unblocked\":{},\"input_byte_length\":{},\"output_byte_length\":{},\"parsed_raw_segment_count\":{},\"parsed_tag_item_count\":{},\"parsed_item_record_count\":{},\"parsed_object_record_count\":{},\"first_mismatch_offset\":{},\"validation_errors\":[",
        json_escape(&report.format),
        json_escape(&report.status),
        json_escape(&report.native_writer_status),
        json_escape(&report.no_edit_roundtrip_mode),
        json_escape(&report.read_model_write_pipeline),
        json_bool(report.available),
        json_bool(report.native_read_model_write_available),
        json_bool(report.parsed_model_available),
        json_bool(report.byte_identical),
        json_bool(report.byte_identical_no_edit_rebuild_supported),
        json_bool(report.semantic_rebuild_supported),
        json_bool(report.havok_xml_import_unblocked),
        report.input_byte_length,
        report.output_byte_length,
        report.parsed_raw_segment_count,
        report.parsed_tag_item_count,
        report.parsed_item_record_count,
        report.parsed_object_record_count,
        json_optional_usize(report.first_mismatch_offset)
    );
    for (index, error) in report.validation_errors.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(error));
    }
    out.push_str("]}");
}

pub fn no_edit_binary_writer_report_to_json(report: &NoEditBinaryWriterReport) -> String {
    let mut out = String::new();
    push_no_edit_binary_writer_report_json(&mut out, report);
    out
}

pub(crate) fn json_layout_value(value: &Option<LayoutValue>) -> String {
    match value {
        Some(LayoutValue::U32(item)) => item.to_string(),
        Some(LayoutValue::U64(item)) => item.to_string(),
        Some(LayoutValue::F32(item)) if item.is_finite() => item.to_string(),
        Some(LayoutValue::Text(item)) => format!("\"{}\"", json_escape(item)),
        _ => "null".to_string(),
    }
}

pub(crate) fn push_json_count_map(out: &mut String, map: &BTreeMap<String, usize>) {
    out.push('{');
    for (index, (key, value)) in map.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), value);
    }
    out.push('}');
}

pub(crate) fn push_fixup_word_json(out: &mut String, word: &TagfileFixupWord) {
    let _ = write!(
        out,
        "{{\"index\":{},\"offset\":{},\"hex_offset\":\"0x{:X}\",\"value\":{},\"value_hex\":\"0x{:X}\",\"match_kind\":\"{}\",\"reference_category\":\"{}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_data_offset\":{},\"target_absolute_offset\":{},\"target_string_index\":{},\"target_string\":{},\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patch_value\":{},\"confidence\":\"{}\"}}",
        word.index,
        word.offset,
        word.offset,
        word.value,
        word.value,
        json_escape(&word.match_kind),
        json_escape(&word.reference_category),
        json_optional_usize(word.target_record_index),
        json_optional_u32(word.target_type_index),
        json_optional_string(word.target_type_name.as_deref()),
        json_optional_u32(word.target_data_offset),
        json_optional_usize(word.target_absolute_offset),
        json_optional_usize(word.target_string_index),
        json_optional_string(word.target_string.as_deref()),
        json_optional_usize(word.owner_record_index),
        json_optional_u32(word.owner_type_index),
        json_optional_string(word.owner_type_name.as_deref()),
        json_optional_usize(word.owner_local_offset),
        word.patch_value
            .map(|item| item.to_string())
            .unwrap_or_else(|| "null".to_string()),
        json_escape(&word.confidence)
    );
}

pub(crate) fn push_ptch_patch_site_json(out: &mut String, site: &TagfilePtchPatchSite) {
    let _ = write!(
        out,
        "{{\"index\":{},\"ptch_word_index\":{},\"section_word_index\":{},\"section_word_offset\":{},\"patch_site_offset\":{},\"patch_site_hex_offset\":\"0x{:X}\",\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patch_value\":{},\"target_status\":\"{}\",\"reference_category\":\"{}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_data_offset\":{},\"target_absolute_offset\":{},\"confidence\":\"{}\"}}",
        site.index,
        site.ptch_word_index,
        json_optional_usize(site.section_word_index),
        json_optional_usize(site.section_word_offset),
        site.patch_site_offset,
        site.patch_site_offset,
        json_optional_usize(site.owner_record_index),
        json_optional_u32(site.owner_type_index),
        json_optional_string(site.owner_type_name.as_deref()),
        json_optional_usize(site.owner_local_offset),
        site.patch_value
            .map(|item| item.to_string())
            .unwrap_or_else(|| "null".to_string()),
        json_escape(&site.target_status),
        json_escape(&site.reference_category),
        json_optional_usize(site.target_record_index),
        json_optional_u32(site.target_type_index),
        json_optional_string(site.target_type_name.as_deref()),
        json_optional_u32(site.target_data_offset),
        json_optional_usize(site.target_absolute_offset),
        json_escape(&site.confidence)
    );
}

pub(crate) fn push_ptch_table_json(out: &mut String, table: &TagfilePtchTable) {
    let _ = write!(
        out,
        "{{\"offset\":{},\"hex_offset\":\"0x{:X}\",\"payload_offset\":{},\"payload_hex_offset\":\"0x{:X}\",\"payload_byte_length\":{},\"word_count\":{},\"header\":[{},{},{},{}],\"patch_site_count\":{},\"resolved_patch_site_count\":{},\"null_patch_site_count\":{},\"unresolved_patch_site_count\":{},\"confidence\":\"{}\",\"patch_sites\":[",
        table.offset,
        table.offset,
        table.payload_offset,
        table.payload_offset,
        table.payload_byte_length,
        table.word_count,
        table.header[0],
        table.header[1],
        table.header[2],
        table.header[3],
        table.patch_site_count,
        table.resolved_patch_site_count,
        table.null_patch_site_count,
        table.unresolved_patch_site_count,
        json_escape(&table.confidence)
    );
    for (index, site) in table.patch_sites.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        push_ptch_patch_site_json(out, site);
    }
    out.push_str("]}");
}

pub(crate) fn push_fixup_semantics_report_json(out: &mut String, report: &FixupSemanticsReport) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_object_patch_site_count\":{},\"ptch_null_patch_site_count\":{},\"ptch_unresolved_patch_site_count\":{},\"ptch_tuple_shape_counts\":",
        json_escape(&report.format),
        json_escape(&report.status),
        if report.imported { "true" } else { "false" },
        report.ptch_table_count,
        report.ptch_patch_site_count,
        report.ptch_object_patch_site_count,
        report.ptch_null_patch_site_count,
        report.ptch_unresolved_patch_site_count,
    );
    push_json_count_map(out, &report.ptch_tuple_shape_counts);
    out.push_str(",\"ptch_payload_match_kind_counts\":");
    push_json_count_map(out, &report.ptch_payload_match_kind_counts);
    out.push_str(",\"ptch_reference_category_counts\":");
    push_json_count_map(out, &report.ptch_reference_category_counts);
    out.push_str(",\"ptch_target_status_counts\":");
    push_json_count_map(out, &report.ptch_target_status_counts);
    out.push_str(",\"varuint_status_counts\":");
    push_json_count_map(out, &report.varuint_status_counts);
    out.push_str(",\"ptch_remaining_case_priorities\":[");
    for (index, case_row) in report.ptch_remaining_case_priorities.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"priority_rank\":{},\"case\":\"{}\",\"count\":{},\"description\":\"{}\"}}",
            case_row.priority_rank,
            json_escape(&case_row.case_name),
            case_row.count,
            json_escape(&case_row.description)
        );
    }
    out.push_str("],\"section_summaries\":[");
    for (index, section) in report.section_summaries.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"payload_byte_length\":{},\"word_count\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_patch_site_resolved_count\":{},\"ptch_patch_site_unresolved_count\":{},\"match_kind_counts\":",
            json_escape(&section.name),
            section.payload_byte_length,
            section.word_count,
            section.ptch_table_count,
            section.ptch_patch_site_count,
            section.ptch_patch_site_resolved_count,
            section.ptch_patch_site_unresolved_count
        );
        push_json_count_map(out, &section.match_kind_counts);
        out.push_str(",\"reference_category_counts\":");
        push_json_count_map(out, &section.reference_category_counts);
        out.push('}');
    }
    out.push_str("]}");
}
