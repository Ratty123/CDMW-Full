use super::fixtures::*;
use crate::*;

#[test]
fn parses_modern_tagfile_sections_types_and_items() {
    let data = sample_hkx();
    let summary = parse_summary(&data);
    assert_eq!(summary.sdk_version, "20240200");
    assert!(summary.size_matches);
    assert_eq!(summary.declared_type_name_count, Some(4));
    assert_eq!(
        summary.type_names,
        vec!["hknpCompoundShape", "hknpConvexShape", "hkFloat3"]
    );
    assert_eq!(summary.item_records.len(), 2);
    assert_eq!(summary.item_records[1].type_name, "hknpConvexShape");
    assert_eq!(summary.item_records[1].data_offset, 32);
    assert_eq!(summary.item_records[1].count, 4);
    assert_eq!(summary.object_records.len(), 2);
    assert_eq!(summary.object_records[1].byte_length, 32);
    assert!(summary_to_json(&summary).contains("\"item_records\""));
    assert!(summary_to_json(&summary).contains("\"object_records\""));
    assert!(summary_to_json(&summary).contains("\"semantic_model_v1\""));
    assert!(summary_to_json(&summary).contains("\"semantic_writer_gate_v1\""));
    assert!(summary_to_json(&summary).contains("\"class_decoder_evidence_v2\""));
    assert_eq!(
        summary.modding_readiness.format,
        "cd_hkx_modding_readiness_v1"
    );
    assert!(!summary.modding_readiness.havok_xml_importable);
    assert!(
        !summary
            .modding_readiness
            .semantic_writer_gate
            .semantic_rebuild_supported
    );
    assert!(summary_to_json(&summary).contains("\"modding_readiness\""));
}

#[test]
fn no_edit_binary_model_writes_identical_bytes() {
    let data = sample_hkx();
    let model = read_no_edit_model(&data).unwrap();
    assert_eq!(model.summary.item_records.len(), 2);
    assert!(!model.raw_segments.is_empty());
    assert_eq!(
        model
            .raw_segments
            .iter()
            .map(|segment| segment.byte_length)
            .sum::<usize>(),
        data.len()
    );
    let output = write_no_edit_model(&model).unwrap();
    assert_eq!(output, data);

    let (roundtrip, report) = roundtrip_no_edit(&data);
    assert_eq!(roundtrip, data);
    assert_eq!(report.format, "cd_hkx_no_edit_binary_writer_v1");
    assert_eq!(report.status, "byte_identical");
    assert_eq!(report.native_writer_status, "available");
    assert_eq!(
        report.no_edit_roundtrip_mode,
        "native_read_model_write_lossless_bytes"
    );
    assert!(report.native_read_model_write_available);
    assert!(report.byte_identical_no_edit_rebuild_supported);
    assert!(!report.semantic_rebuild_supported);
    assert!(report.parsed_raw_segment_count > 0);
    assert_eq!(report.first_mismatch_offset, None);

    let summary = parse_summary(&data);
    let json = summary_to_json_with_no_edit_report(&summary, &report);
    assert!(json.contains("\"no_edit_binary_writer\""));
    assert!(json.contains("\"status\":\"byte_identical\""));
}
#[test]
fn no_edit_binary_model_rejects_non_hkx_input() {
    let report = verify_no_edit_roundtrip(b"not hkx");
    assert_eq!(report.status, "read_error");
    assert!(!report.native_read_model_write_available);
    assert!(!report.byte_identical_no_edit_rebuild_supported);
    assert!(!report.validation_errors.is_empty());
}

#[test]
fn decodes_object_layouts_and_reference_candidates() {
    let data = array_ref_hkx();
    let summary = parse_summary(&data);
    assert_eq!(summary.object_records.len(), 3);

    let array = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkArray")
        .unwrap();
    assert_eq!(array.status, "partially_decoded");
    assert!(array
        .fields
        .iter()
        .any(|field| field.name == "size" && field.value == Some(LayoutValue::U32(3))));
    assert!(array
        .references
        .iter()
        .any(|reference| reference.target_record_index == 2
            && reference.reference_kind == "data_offset"
            && reference.reference_category == "array_data_reference"
            && reference.owner_field_name == Some("data".to_string())));

    let reference = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkRefPtr")
        .unwrap();
    assert!(reference
        .fields
        .iter()
        .any(|field| field.name == "referenced_object"));
    assert!(reference
        .references
        .iter()
        .any(|link| link.target_type_name == "hknpShape"
            && link.reference_category == "object_reference"));

    let shape = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpShape")
        .unwrap();
    assert!(shape
        .fields
        .iter()
        .any(|field| field.name == "finite_float_0x0"));
    let json = summary_to_json(&summary);
    assert!(json.contains("\"references\""));
    assert!(json.contains("\"reference_category\":\"array_data_reference\""));
    assert!(json.contains("\"tagfile_reference_fixups\""));
    assert_eq!(summary.tagfile_reference_fixups.section_count, 1);
    let indx = &summary.tagfile_reference_fixups.sections[0];
    assert_eq!(indx.name, "INDX");
    assert_eq!(indx.null_word_count, 1);
    assert!(indx.record_offset_match_count >= 1);
    assert!(indx.type_index_match_count >= 1);
    assert!(indx
        .resolved_references
        .iter()
        .any(|word| word.reference_category == "object_reference"));
    assert!(json.contains("\"finite_float_0x0\""));
}

fn assert_nested_fixup_json(summary: &HkxSummary) {
    let json = summary_to_json(summary);
    for expected in [
        "\"fixup_semantics_report\"",
        "\"fixup_semantics_v2\"",
        "\"semantic_bucket\":\"object_ref\"",
        "\"semantic_bucket_counts\"",
        "\"semantic_bucket_taxonomy\"",
        "\"data_ref\"",
        "\"string_ref\"",
        "\"type_class_ref\"",
        "\"section_local_ref\"",
        "\"packed_or_varuint\"",
        "\"corpus_evidence_counters\"",
        "\"patch_site_count\":1",
        "\"cd_hkx_fixup_semantics_report_v1\"",
        "\"ptch_object_patch_offset\"",
        "\"ptch_tables\"",
        "\"target_status\":\"object\"",
        "\"owner_record_index\":1",
        "\"native_model_graph\"",
        "\"resolution_source\":\"ptch\"",
        "\"decoder_evidence_v2\"",
        "\"fixup_backed\"",
        "\"object\"",
        "\"semantic_model_v1\"",
        "\"source_priority\"",
        "\"field_kind_taxonomy\"",
        "\"semantic_writer_gate_v1\"",
        "\"writer_modes\"",
        "\"representative_role_gates\"",
        "\"semantic_no_edit_status\"",
    ] {
        assert!(json.contains(expected), "missing JSON evidence: {expected}");
    }
}

#[test]
fn decodes_nested_indx_item_and_ptch_tables() {
    let data = nested_indx_ptch_hkx();
    let summary = parse_summary(&data);

    assert!(summary.tag_items.iter().any(|item| item.name == "PTCH"));
    assert_eq!(summary.item_records.len(), 3);
    let section = summary
        .tagfile_reference_fixups
        .sections
        .iter()
        .find(|section| section.name == "INDX")
        .unwrap();
    assert_eq!(
        section.match_kind_counts.get("item_type_flags").copied(),
        Some(3)
    );
    assert_eq!(
        section.match_kind_counts.get("item_data_offset").copied(),
        Some(3)
    );
    assert_eq!(
        section.match_kind_counts.get("ptch_length_word").copied(),
        Some(1)
    );
    assert_eq!(
        section.match_kind_counts.get("ptch_marker").copied(),
        Some(1)
    );
    assert_eq!(
        section.match_kind_counts.get("ptch_header_word").copied(),
        Some(4)
    );
    assert_eq!(
        section
            .match_kind_counts
            .get("ptch_patch_site_count")
            .copied(),
        Some(1)
    );
    assert_eq!(
        section
            .match_kind_counts
            .get("ptch_object_patch_offset")
            .copied(),
        Some(1)
    );
    assert_eq!(summary.tagfile_reference_fixups.ptch_table_count, 1);
    assert_eq!(summary.tagfile_reference_fixups.ptch_patch_site_count, 1);
    assert_eq!(
        summary
            .tagfile_reference_fixups
            .ptch_resolved_patch_site_count,
        1
    );
    assert_eq!(
        summary.tagfile_reference_fixups.ptch_null_patch_site_count,
        0
    );
    assert_eq!(
        summary
            .tagfile_reference_fixups
            .ptch_unresolved_patch_site_count,
        0
    );
    assert_eq!(section.ptch_tables.len(), 1);
    let ptch_table = &section.ptch_tables[0];
    let ptch_item = summary
        .tag_items
        .iter()
        .find(|item| item.name == "PTCH")
        .unwrap();
    assert_eq!(ptch_table.offset, ptch_item.offset);
    assert_eq!(ptch_table.payload_byte_length, 24);
    assert_eq!(ptch_table.header, [1, 1, 0, 2]);
    assert_eq!(ptch_table.patch_site_count, 1);
    assert_eq!(ptch_table.resolved_patch_site_count, 1);
    assert_eq!(ptch_table.patch_sites.len(), 1);
    let patch_site = &ptch_table.patch_sites[0];
    assert_eq!(patch_site.ptch_word_index, 5);
    assert_eq!(patch_site.section_word_index, Some(21));
    assert_eq!(patch_site.patch_site_offset, 16);
    assert_eq!(patch_site.owner_record_index, Some(1));
    assert_eq!(patch_site.owner_local_offset, Some(0));
    assert_eq!(patch_site.patch_value, Some(2));
    assert_eq!(patch_site.target_status, "object");
    assert_eq!(patch_site.target_record_index, Some(2));
    assert!(!section.match_kind_counts.contains_key("unresolved_word"));
    let patch_word = section
        .words
        .iter()
        .find(|word| word.match_kind == "ptch_object_patch_offset")
        .unwrap();
    assert_eq!(patch_word.owner_record_index, Some(1));
    assert_eq!(patch_word.owner_local_offset, Some(0));
    assert_eq!(patch_word.patch_value, Some(2));
    assert_eq!(patch_word.target_record_index, Some(2));
    assert_eq!(patch_word.reference_category, "object_reference");
    let graph = &summary.native_model_graph;
    assert_eq!(graph.format, "cd_hkx_native_model_graph_v1");
    assert_eq!(graph.node_count, 3);
    assert_eq!(graph.fixup_backed_reference_edge_count, 1);
    assert!(graph.edges.iter().any(|edge| {
        edge.source_record_index == Some(1)
            && edge.target_record_index == Some(2)
            && edge.owner_field_name.as_deref() == Some("ptr")
            && edge.reference_category == "object_reference"
            && edge.resolution_source == "ptch"
    }));
    assert!(graph.graph_order.contains(&2));
    let semantics = &summary.fixup_semantics_report;
    assert_eq!(semantics.format, "cd_hkx_fixup_semantics_report_v1");
    assert_eq!(semantics.ptch_table_count, 1);
    assert_eq!(semantics.ptch_patch_site_count, 1);
    assert_eq!(semantics.ptch_object_patch_site_count, 1);
    assert_eq!(
        semantics.ptch_tuple_shape_counts.get("1,1,0,2").copied(),
        Some(1)
    );
    assert_eq!(
        semantics
            .ptch_payload_match_kind_counts
            .get("ptch_object_patch_offset")
            .copied(),
        Some(1)
    );
    assert_eq!(
        semantics.ptch_target_status_counts.get("object").copied(),
        Some(1)
    );

    assert_nested_fixup_json(&summary);
}

#[test]
fn normalizes_decoder_evidence_v2_reference_and_link_semantics() {
    assert_eq!(
        decoder_reference_semantic_from_parts("object_reference", "data_offset", ""),
        "object"
    );
    assert_eq!(
        decoder_reference_semantic_from_parts("null_reference", "null", "null"),
        "null"
    );
    assert_eq!(
        decoder_reference_semantic_from_parts("array_data_reference", "data_offset", ""),
        "data_candidate"
    );
    assert_eq!(
        decoder_reference_semantic_from_parts("string_reference", "string_table_index", ""),
        "string_candidate"
    );
    assert_eq!(
        decoder_reference_semantic_from_parts("type_class_reference", "string_table_index", ""),
        "type_class"
    );
    assert_eq!(
        decoder_reference_semantic_from_parts("unresolved_fixup_word", "packed_varuint", ""),
        "packed_or_varuint"
    );

    let data = nested_indx_ptch_hkx();
    let summary = parse_summary(&data);
    let evidence = &summary.decoder_evidence_v2;
    assert_eq!(evidence.format, "cd_hkx_decoder_evidence_v2");
    assert_eq!(evidence.status, "read_only_native_evidence");
    assert!(evidence.read_only);
    assert!(
        evidence
            .reference_semantic_counts
            .get("object")
            .copied()
            .unwrap_or(0)
            >= 1
    );
    assert!(
        evidence
            .link_evidence_counts
            .get("fixup_backed")
            .copied()
            .unwrap_or(0)
            >= 1
    );
    assert!(evidence.fixup_backed_fields.iter().any(|field| {
        field.class_name == "hkRefPtr"
            && field.field_name == "ptr"
            && field.reference_category == "object_reference"
    }));
    assert!(evidence
        .class_statuses
        .iter()
        .any(|row| row.type_name == "hkRefPtr"
            && row
                .link_evidence
                .iter()
                .any(|value| value == "fixup_backed")));
}
