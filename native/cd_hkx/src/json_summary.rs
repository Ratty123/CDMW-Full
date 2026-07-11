use crate::*;

pub(crate) fn push_summary_header_json(out: &mut String, summary: &HkxSummary) {
    out.push('{');
    let _ = write!(
        out,
        "\"declared_size\":{},\"size_matches\":{},\"sdk_version\":\"{}\",\"tag0_offset\":{},",
        json_optional_u32(summary.declared_size),
        if summary.size_matches {
            "true"
        } else {
            "false"
        },
        json_escape(&summary.sdk_version),
        json_optional_usize(summary.tag0_offset)
    );
    out.push_str("\"tag_items\":[");
    for (index, item) in summary.tag_items.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"offset\":{},\"length_word_offset\":{},\"raw_length_word\":{},\"declared_length\":{},\"length_flags\":{},\"marker_end_offset\":{},\"word_end_offset\":{}}}",
            json_escape(&item.name),
            item.offset,
            json_optional_usize(item.length_word_offset),
            json_optional_u32(item.raw_length_word),
            json_optional_u32(item.declared_length),
            json_optional_u32(item.length_flags),
            json_optional_usize(item.marker_end_offset),
            json_optional_usize(item.word_end_offset)
        );
    }
    out.push_str("],\"string_table_names\":[");
    for (index, name) in summary.string_table_names.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(name));
    }
    out.push_str("],\"type_infos\":[");
    for (index, info) in summary.type_infos.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"index\":{},\"name\":\"{}\",\"display_name\":\"{}\",\"template_parameters\":[",
            info.index,
            json_escape(&info.name),
            json_escape(&info.display_name())
        );
        for (parameter_index, (name, value)) in info.template_parameters.iter().enumerate() {
            if parameter_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"value\":{}}}",
                json_escape(name),
                value
            );
        }
        out.push_str("]}");
    }
    out.push_str("],");
    let _ = write!(
        out,
        "\"declared_type_name_count\":{},",
        json_optional_u32(summary.declared_type_name_count)
    );
    out.push_str("\"type_names\":[");
    for (index, name) in summary.type_names.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(name));
    }
    out.push_str("],\"item_records\":[");
    for (index, record) in summary.item_records.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"index\":{},\"raw_type_flags\":{},\"type_index\":{},\"flags\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"count\":{},\"type_name\":\"{}\"}}",
            record.index,
            record.raw_type_flags,
            record.type_index,
            record.flags,
            record.data_offset,
            json_optional_usize(record.absolute_data_offset),
            record.count,
            json_escape(&record.type_name)
        );
    }
}

pub(crate) fn push_summary_objects_json(out: &mut String, summary: &HkxSummary) {
    out.push_str("],\"object_records\":[");
    for (index, object) in summary.object_records.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"record_index\":{},\"type_index\":{},\"type_name\":\"{}\",\"count\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"byte_length\":{},\"stride\":{},\"status\":\"{}\",\"raw_hex_prefix\":\"{}\",\"fields\":[",
            object.record_index,
            object.type_index,
            json_escape(&object.type_name),
            object.count,
            object.data_offset,
            json_optional_usize(object.absolute_data_offset),
            object.byte_length,
            json_optional_f32(object.stride),
            json_escape(&object.status),
            json_escape(&object.raw_hex_prefix)
        );
        for (field_index, field) in object.fields.iter().enumerate() {
            if field_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"offset\":{},\"hex_offset\":\"0x{:X}\",\"size\":{},\"data_type\":\"{}\",\"value\":{},\"description\":\"{}\",\"confidence\":\"{}\",\"editable\":{}}}",
                json_escape(&field.name),
                field.offset,
                field.offset,
                field.size,
                json_escape(&field.data_type),
                json_layout_value(&field.value),
                json_escape(&field.description),
                json_escape(&field.confidence),
                if field.editable { "true" } else { "false" }
            );
        }
        out.push_str("],\"references\":[");
        for (reference_index, reference) in object.references.iter().enumerate() {
            if reference_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"offset\":{},\"hex_offset\":\"0x{:X}\",\"reference_kind\":\"{}\",\"reference_category\":\"{}\",\"owner_field_name\":{},\"raw_value\":{},\"raw_value_hex\":\"0x{:X}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":\"{}\",\"confidence\":\"experimental\"}}",
                reference.offset,
                reference.offset,
                json_escape(&reference.reference_kind),
                json_escape(&reference.reference_category),
                json_optional_string(reference.owner_field_name.as_deref()),
                reference.raw_value,
                reference.raw_value,
                reference.target_record_index,
                reference.target_type_index,
                json_escape(&reference.target_type_name)
            );
        }
        out.push_str("]}");
    }
}

pub(crate) fn push_summary_fixups_json(out: &mut String, summary: &HkxSummary) {
    out.push_str("],\"tagfile_reference_fixups\":{");
    let fixups = &summary.tagfile_reference_fixups;
    let _ = write!(
        out,
        "\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"section_count\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_resolved_patch_site_count\":{},\"ptch_null_patch_site_count\":{},\"ptch_unresolved_patch_site_count\":{},\"match_kind_counts\":",
        json_escape(&fixups.format),
        json_escape(&fixups.status),
        if fixups.imported { "true" } else { "false" },
        fixups.section_count,
        fixups.ptch_table_count,
        fixups.ptch_patch_site_count,
        fixups.ptch_resolved_patch_site_count,
        fixups.ptch_null_patch_site_count,
        fixups.ptch_unresolved_patch_site_count
    );
    push_json_count_map(out, &fixups.match_kind_counts);
    out.push_str(",\"reference_category_counts\":");
    push_json_count_map(out, &fixups.reference_category_counts);
    out.push_str(",\"sections\":[");
    for (section_index, section) in fixups.sections.iter().enumerate() {
        if section_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"offset\":{},\"payload_byte_length\":{},\"word_count\":{},\"shown_word_count\":{},\"truncated_word_count\":{},\"match_kind_counts\":",
            json_escape(&section.name),
            section.offset,
            section.payload_byte_length,
            section.word_count,
            section.shown_word_count,
            section.truncated_word_count
        );
        push_json_count_map(out, &section.match_kind_counts);
        out.push_str(",\"reference_category_counts\":");
        push_json_count_map(out, &section.reference_category_counts);
        let _ = write!(
            out,
            ",\"record_offset_match_count\":{},\"null_word_count\":{},\"type_index_match_count\":{},\"string_table_index_match_count\":{},\"ptch_tables\":[",
            section.record_offset_match_count,
            section.null_word_count,
            section.type_index_match_count,
            section.string_table_index_match_count
        );
        for (table_index, table) in section.ptch_tables.iter().enumerate() {
            if table_index > 0 {
                out.push(',');
            }
            push_ptch_table_json(out, table);
        }
        out.push_str("],\"resolved_references\":[");
        for (word_index, word) in section.resolved_references.iter().enumerate() {
            if word_index > 0 {
                out.push(',');
            }
            push_fixup_word_json(out, word);
        }
        out.push_str("],\"words\":[");
        for (word_index, word) in section.words.iter().enumerate() {
            if word_index > 0 {
                out.push(',');
            }
            push_fixup_word_json(out, word);
        }
        out.push_str("]}");
    }
}

pub(crate) fn push_summary_reports_json(out: &mut String, summary: &HkxSummary) {
    out.push_str("]},\"fixup_semantics_report\":");
    push_fixup_semantics_report_json(out, &summary.fixup_semantics_report);
    out.push_str(",\"native_model_graph\":");
    push_native_model_graph_json(out, &summary.native_model_graph);
    out.push_str(",\"hard_internal_evidence\":");
    push_hard_internal_evidence_json(out, &summary.hard_internal_evidence);
    out.push_str(",\"real_hkclass_metadata\":");
    push_real_hkclass_metadata_json(out, &summary.real_hkclass_metadata);
    out.push_str(",\"real_hkclass_metadata_v2\":");
    push_real_hkclass_metadata_v2_json(out, &summary.real_hkclass_metadata);
    out.push_str(",\"fixup_semantics_v2\":");
    push_fixup_semantics_v2_json(
        out,
        &summary.tagfile_reference_fixups,
        &summary.fixup_semantics_report,
    );
    out.push_str(",\"semantic_model_v1\":");
    push_semantic_model_v1_json(
        out,
        &summary.object_records,
        &summary.native_model_graph,
        &summary.real_hkclass_metadata,
    );
    out.push_str(",\"decoder_evidence_v2\":");
    push_decoder_evidence_v2_json(out, &summary.decoder_evidence_v2);
    out.push_str(",\"modding_readiness\":");
    push_hkx_modding_readiness_json(out, &summary.modding_readiness);
    out.push_str(",\"semantic_writer_gate_v1\":");
    push_semantic_writer_gate_v1_json(out, &summary.modding_readiness);
    out.push_str(",\"edit_candidate_map_v1\":");
    push_edit_candidate_map_v1_json(out, &summary.physics_tuning_groups, &summary.object_records);
    out.push_str(",\"hkx_edit_gate_v1\":");
    push_hkx_edit_gate_v1_json(out, &summary.physics_tuning_groups, &summary.object_records);
    out.push_str(",\"class_decoder_evidence_v2\":");
    push_class_decoder_evidence_v2_json(
        out,
        &summary.decoder_evidence_v2,
        &summary.hard_internal_evidence,
    );
    out.push_str(",\"physics_tuning_groups\":[");
    for (group_index, group) in summary.physics_tuning_groups.iter().enumerate() {
        if group_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"category\":\"{}\",\"label\":\"{}\",\"type_name\":\"{}\",\"record_index\":{},\"count\":{},\"byte_length\":{},\"stride\":{},\"description\":\"{}\",\"confidence\":\"{}\",\"edit_rule\":\"{}\",\"slots\":[",
            json_escape(&group.category),
            json_escape(&group.label),
            json_escape(&group.type_name),
            group.record_index,
            group.count,
            group.byte_length,
            group.stride,
            json_escape(&group.description),
            json_escape(&group.confidence),
            json_escape(&group.edit_rule)
        );
        for (slot_index, slot) in group.slots.iter().enumerate() {
            if slot_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"item_index\":{},\"offset\":{},\"hex_offset\":\"0x{:X}\",\"name\":\"{}\",\"value\":{},\"description\":\"{}\",\"confidence\":\"{}\"}}",
                slot.item_index,
                slot.offset,
                slot.offset,
                json_escape(&slot.name),
                if slot.value.is_finite() { slot.value.to_string() } else { "null".to_string() },
                json_escape(&slot.description),
                json_escape(&slot.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("],\"warnings\":[");
    for (index, warning) in summary.warnings.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(warning));
    }
    out.push_str("]}");
}

pub fn summary_to_json(summary: &HkxSummary) -> String {
    let mut out = String::new();
    push_summary_header_json(&mut out, summary);
    push_summary_objects_json(&mut out, summary);
    push_summary_fixups_json(&mut out, summary);
    push_summary_reports_json(&mut out, summary);
    out
}

pub fn summary_to_json_with_no_edit_report(
    summary: &HkxSummary,
    report: &NoEditBinaryWriterReport,
) -> String {
    let mut out = summary_to_json(summary);
    if out.ends_with('}') {
        out.pop();
    }
    out.push_str(",\"no_edit_binary_writer\":");
    push_no_edit_binary_writer_report_json(&mut out, report);
    out.push('}');
    out
}
