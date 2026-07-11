use crate::*;

pub(crate) fn normalize_fixup_semantic_bucket(
    reference_category: &str,
    target_status: &str,
    match_kind: &str,
) -> &'static str {
    let category = reference_category.to_ascii_lowercase();
    let status = target_status.to_ascii_lowercase();
    let kind = match_kind.to_ascii_lowercase();
    if status.contains("null") || category.contains("null") {
        return "null_ref";
    }
    if category.contains("string") || kind.contains("string") {
        return "string_ref";
    }
    if category.contains("type")
        || category.contains("class")
        || kind.contains("type")
        || kind.contains("class")
    {
        return "type_class_ref";
    }
    if category.contains("section") || kind.contains("section") {
        return "section_local_ref";
    }
    if category.contains("data") || kind.contains("data") {
        return "data_ref";
    }
    if category.contains("packed")
        || category.contains("varuint")
        || kind.contains("packed")
        || kind.contains("varuint")
    {
        return "packed_or_varuint";
    }
    if status.contains("resolved") || category.contains("object") || kind.contains("object") {
        return "object_ref";
    }
    "unresolved"
}

pub(crate) fn push_fixup_semantics_v2_json(
    out: &mut String,
    fixups: &TagfileFixupSummary,
    report: &FixupSemanticsReport,
) {
    let mut bucket_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut tuple_shape_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut patch_site_total = 0usize;
    let mut patch_site_resolved = 0usize;
    let mut patch_site_unresolved = 0usize;
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            let tuple_shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            *tuple_shape_counts.entry(tuple_shape).or_insert(0) += table.patch_sites.len();
            for site in &table.patch_sites {
                patch_site_total += 1;
                if site.target_record_index.is_some() || site.target_status == "null" {
                    patch_site_resolved += 1;
                } else {
                    patch_site_unresolved += 1;
                }
                let bucket = normalize_fixup_semantic_bucket(
                    &site.reference_category,
                    &site.target_status,
                    "",
                );
                *bucket_counts.entry(bucket.to_string()).or_insert(0) += 1;
            }
        }
        for word in &section.resolved_references {
            let bucket = normalize_fixup_semantic_bucket(
                &word.reference_category,
                if word.target_record_index.is_some() {
                    "resolved"
                } else {
                    "unresolved"
                },
                &word.match_kind,
            );
            *bucket_counts.entry(bucket.to_string()).or_insert(0) += 1;
        }
    }
    for bucket in [
        "object_ref",
        "null_ref",
        "data_ref",
        "string_ref",
        "type_class_ref",
        "section_local_ref",
        "packed_or_varuint",
        "unresolved",
    ] {
        bucket_counts.entry(bucket.to_string()).or_insert(0);
    }
    let status = if patch_site_total > 0 {
        "ptch_patch_sites_normalized_read_only"
    } else if !report.ptch_reference_category_counts.is_empty() {
        "fixup_observations_normalized_read_only"
    } else {
        "no_fixup_semantics_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_fixup_semantics_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"patch_site_count\":{},\"resolved_patch_site_count\":{},\"unresolved_patch_site_count\":{}",
        status,
        json_escape(&report.format),
        json_bool(report.imported),
        patch_site_total,
        patch_site_resolved,
        patch_site_unresolved
    );
    out.push_str(",\"semantic_bucket_taxonomy\":[");
    for (index, (bucket, meaning, edit_policy)) in [
        (
            "object_ref",
            "Fixup points to another ITEM/object record.",
            "read_only_reference; edit blocked until semantic writer proof",
        ),
        (
            "null_ref",
            "Fixup represents a null reference slot.",
            "read_only_reference; null ref edits blocked",
        ),
        (
            "data_ref",
            "Fixup likely points to data/array storage rather than an object.",
            "corpus_proof_required",
        ),
        (
            "string_ref",
            "Fixup likely points to string storage/table data.",
            "corpus_proof_required",
        ),
        (
            "type_class_ref",
            "Fixup likely points to class/type metadata.",
            "corpus_proof_required",
        ),
        (
            "section_local_ref",
            "Fixup appears to use section-local indexing/addressing.",
            "corpus_proof_required",
        ),
        (
            "packed_or_varuint",
            "Fixup appears to use packed or variable-width index encoding.",
            "corpus_proof_required",
        ),
        (
            "unresolved",
            "Fixup could not be assigned a target or semantic bucket.",
            "decoder_work_required",
        ),
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"bucket\":\"{}\",\"meaning\":\"{}\",\"edit_policy\":\"{}\"}}",
            bucket,
            json_escape(meaning),
            edit_policy
        );
    }
    out.push(']');
    out.push_str(",\"semantic_bucket_counts\":");
    push_json_count_map(out, &bucket_counts);
    out.push_str(",\"tuple_shape_counts\":");
    push_json_count_map(out, &tuple_shape_counts);
    out.push_str(",\"source_tuple_shape_counts\":");
    push_json_count_map(out, &report.ptch_tuple_shape_counts);
    out.push_str(",\"source_payload_match_kind_counts\":");
    push_json_count_map(out, &report.ptch_payload_match_kind_counts);
    out.push_str(",\"source_reference_category_counts\":");
    push_json_count_map(out, &report.ptch_reference_category_counts);
    out.push_str(",\"patch_sites\":[");
    let mut emitted = 0usize;
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            let tuple_shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            for site in &table.patch_sites {
                if emitted > 0 {
                    out.push(',');
                }
                emitted += 1;
                let bucket = normalize_fixup_semantic_bucket(
                    &site.reference_category,
                    &site.target_status,
                    "",
                );
                let _ = write!(
                    out,
                    "{{\"index\":{},\"section\":\"{}\",\"ptch_section_offset\":{},\"ptch_section_hex_offset\":\"0x{:X}\",\"tuple_shape\":\"{}\",\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patched_slot_value\":{},\"patch_value\":{},\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_status\":\"{}\",\"semantic_bucket\":\"{}\",\"reference_category\":\"{}\",\"confidence\":\"{}\"}}",
                    site.index,
                    json_escape(&section.name),
                    table.offset,
                    table.offset,
                    tuple_shape,
                    json_optional_usize(site.owner_record_index),
                    json_optional_u32(site.owner_type_index),
                    json_optional_string(site.owner_type_name.as_deref()),
                    json_optional_usize(site.owner_local_offset),
                    site.patch_value
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "null".to_string()),
                    site.patch_value
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "null".to_string()),
                    json_optional_usize(site.target_record_index),
                    json_optional_u32(site.target_type_index),
                    json_optional_string(site.target_type_name.as_deref()),
                    json_escape(&site.target_status),
                    bucket,
                    json_escape(&site.reference_category),
                    json_escape(&site.confidence)
                );
            }
        }
    }
    out.push_str("],\"remaining_cases\":[");
    for (index, case_row) in report.ptch_remaining_case_priorities.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let bucket = normalize_fixup_semantic_bucket("", "unresolved", &case_row.case_name);
        let _ = write!(
            out,
            "{{\"priority_rank\":{},\"case\":\"{}\",\"semantic_bucket\":\"{}\",\"count\":{},\"description\":\"{}\"}}",
            case_row.priority_rank,
            json_escape(&case_row.case_name),
            bucket,
            case_row.count,
            json_escape(&case_row.description)
        );
    }
    out.push_str("],\"corpus_evidence_counters\":{");
    let mut emitted_counter = 0usize;
    for (name, value) in [
        ("patch_site_count", patch_site_total),
        ("resolved_patch_site_count", patch_site_resolved),
        ("unresolved_patch_site_count", patch_site_unresolved),
        (
            "unusual_tuple_shape_count",
            tuple_shape_counts
                .iter()
                .filter(|(shape, _)| shape.as_str() != "1,1,0,2")
                .count(),
        ),
        (
            "remaining_case_count",
            report.ptch_remaining_case_priorities.len(),
        ),
        (
            "data_ref_count",
            *bucket_counts.get("data_ref").unwrap_or(&0usize),
        ),
        (
            "string_ref_count",
            *bucket_counts.get("string_ref").unwrap_or(&0usize),
        ),
        (
            "type_class_ref_count",
            *bucket_counts.get("type_class_ref").unwrap_or(&0usize),
        ),
        (
            "section_local_ref_count",
            *bucket_counts.get("section_local_ref").unwrap_or(&0usize),
        ),
        (
            "packed_or_varuint_count",
            *bucket_counts.get("packed_or_varuint").unwrap_or(&0usize),
        ),
    ] {
        if emitted_counter > 0 {
            out.push(',');
        }
        emitted_counter += 1;
        let _ = write!(out, "\"{}\":{}", name, value);
    }
    out.push_str("},\"corpus_proof_targets\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"]}");
}

pub(crate) fn semantic_field_kind(field: &LayoutField) -> &'static str {
    let name = field.name.to_ascii_lowercase();
    let data_type = field.data_type.to_ascii_lowercase();
    if name.contains("string") || data_type.contains("string") {
        "string"
    } else if name.contains("ref") || data_type.contains("ref") {
        "ref"
    } else if name.contains("array")
        || data_type.contains("array")
        || field.description.contains("row")
    {
        "array"
    } else if data_type.contains("float3")
        || data_type.contains("float4")
        || data_type.contains("vector")
    {
        "vector"
    } else if data_type.contains("enum") {
        "enum"
    } else if data_type.contains("struct") {
        "struct"
    } else if data_type.contains("raw") || field.value.is_none() {
        "raw_span"
    } else {
        "scalar"
    }
}

pub(crate) fn push_semantic_model_v1_json(
    out: &mut String,
    objects: &[ObjectRecord],
    graph: &NativeModelGraph,
    metadata: &RealHkClassMetadataReport,
) {
    let mut real_class_names = BTreeMap::new();
    for class_info in &metadata.classes {
        real_class_names.insert(class_info.name.clone(), true);
    }
    let field_count: usize = objects.iter().map(|object| object.fields.len()).sum();
    let raw_fallback_count = objects
        .iter()
        .filter(|object| object.fields.is_empty() || object.status == "raw_preserved")
        .count();
    let status = if objects.is_empty() {
        "no_semantic_objects_recovered"
    } else {
        "read_only_semantic_model_from_native_records"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_semantic_model_v1\",\"status\":\"{}\",\"imported\":false,\"read_only\":true,\"object_count\":{},\"field_count\":{},\"raw_fallback_count\":{},\"graph_order_count\":{},\"root_record_index\":{},\"root_type_name\":{}",
        status,
        objects.len(),
        field_count,
        raw_fallback_count,
        graph.graph_order.len(),
        json_optional_usize(graph.root.record_index),
        json_optional_string(graph.root.type_name.as_deref())
    );
    out.push_str(",\"source_priority\":[\"real_hkclass_metadata_v2\",\"typed_layout_decoder\",\"raw_preserved_payload\"]");
    out.push_str(",\"field_kind_taxonomy\":[\"scalar\",\"vector\",\"array\",\"ref\",\"string\",\"enum\",\"struct\",\"raw_span\"]");
    out.push_str(",\"graph_order\":[");
    for (index, record_index) in graph.graph_order.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "{record_index}");
    }
    out.push_str("],\"objects\":[");
    for (object_index, object) in objects.iter().take(512).enumerate() {
        if object_index > 0 {
            out.push(',');
        }
        let class_metadata_source = if real_class_names.contains_key(&object.type_name) {
            "real_hkclass_metadata_v2"
        } else if !object.fields.is_empty() {
            "typed_layout_decoder"
        } else {
            "raw_preserved_payload"
        };
        let raw_span_count = object
            .fields
            .iter()
            .filter(|field| semantic_field_kind(field) == "raw_span")
            .count();
        let byte_range_end = object
            .absolute_data_offset
            .map(|offset| offset.saturating_add(object.byte_length));
        let _ = write!(
            out,
            "{{\"record_index\":{},\"type_index\":{},\"type_name\":\"{}\",\"count\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"byte_length\":{},\"byte_range_start\":{},\"byte_range_end\":{},\"status\":\"{}\",\"class_metadata_source\":\"{}\",\"semantic_source\":\"{}\",\"field_count\":{},\"reference_count\":{},\"raw_span_count\":{}",
            object.record_index,
            object.type_index,
            json_escape(&object.type_name),
            object.count,
            object.data_offset,
            json_optional_usize(object.absolute_data_offset),
            object.byte_length,
            json_optional_usize(object.absolute_data_offset),
            json_optional_usize(byte_range_end),
            json_escape(&object.status),
            class_metadata_source,
            class_metadata_source,
            object.fields.len(),
            object.references.len(),
            raw_span_count
        );
        out.push_str(",\"fields\":[");
        for (field_index, field) in object.fields.iter().enumerate() {
            if field_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"kind\":\"{}\",\"offset\":{},\"offset_hex\":\"0x{:X}\",\"size\":{},\"byte_range_start\":{},\"byte_range_end\":{},\"data_type\":\"{}\",\"value\":{},\"confidence\":\"{}\",\"editable_candidate\":{},\"write_enabled\":false,\"write_gate_status\":\"{}\",\"description\":\"{}\"}}",
                json_escape(&field.name),
                semantic_field_kind(field),
                field.offset,
                field.offset,
                field.size,
                json_optional_usize(object.absolute_data_offset.map(|base| base + field.offset)),
                json_optional_usize(
                    object
                        .absolute_data_offset
                        .map(|base| base + field.offset + field.size)
                ),
                json_escape(&field.data_type),
                json_layout_value(&field.value),
                json_escape(&field.confidence),
                json_bool(field.editable),
                if field.editable {
                    "candidate_only_until_edit_gate"
                } else {
                    "read_only"
                },
                json_escape(&field.description)
            );
        }
        out.push_str("],\"refs\":[");
        let mut emitted_ref = 0usize;
        for edge in graph
            .edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(object.record_index))
        {
            if emitted_ref > 0 {
                out.push(',');
            }
            emitted_ref += 1;
            let _ = write!(
                out,
                "{{\"target_record_index\":{},\"owner_field_name\":{},\"owner_local_offset\":{},\"reference_category\":\"{}\",\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
                json_optional_usize(edge.target_record_index),
                json_optional_string(edge.owner_field_name.as_deref()),
                json_optional_usize(edge.owner_local_offset),
                json_escape(&edge.reference_category),
                json_escape(&edge.resolution_source),
                json_escape(&edge.confidence)
            );
        }
        out.push_str("]}");
    }
    let _ = write!(
        out,
        "],\"truncated_object_count\":{},\"edit_policy\":{{\"havok_xml_importable\":false,\"semantic_writer_required\":true,\"blocked_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"class_metadata\"]}}}}",
        objects.len().saturating_sub(512)
    );
}
