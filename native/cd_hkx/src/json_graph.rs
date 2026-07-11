use crate::*;

pub(crate) fn push_native_model_graph_json(out: &mut String, graph: &NativeModelGraph) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"node_count\":{},\"edge_count\":{},\"fixup_backed_reference_edge_count\":{},\"inferred_reference_edge_count\":{},\"owner_array_count\":{}",
        json_escape(&graph.format),
        json_escape(&graph.status),
        json_bool(graph.imported),
        graph.node_count,
        graph.edge_count,
        graph.fixup_backed_reference_edge_count,
        graph.inferred_reference_edge_count,
        graph.owner_array_count
    );
    out.push_str(",\"root\":");
    let root = &graph.root;
    let _ = write!(
        out,
        "{{\"record_index\":{},\"type_name\":{},\"method\":\"{}\",\"confidence\":\"{}\",\"named_variant_count\":{},\"named_variants\":[",
        json_optional_usize(root.record_index),
        json_optional_string(root.type_name.as_deref()),
        json_escape(&root.method),
        json_escape(&root.confidence),
        root.named_variant_count
    );
    for (index, variant) in root.named_variants.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"variant_record_index\":{},\"name\":{},\"class_name\":{},\"object_record_index\":{},\"object_type_name\":{},\"confidence\":\"{}\"}}",
            variant.variant_record_index,
            json_optional_string(variant.name.as_deref()),
            json_optional_string(variant.class_name.as_deref()),
            json_optional_usize(variant.object_record_index),
            json_optional_string(variant.object_type_name.as_deref()),
            json_escape(&variant.confidence)
        );
    }
    out.push_str("]}");
    out.push_str(",\"graph_order\":[");
    for (index, record_index) in graph.graph_order.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "{record_index}");
    }
    out.push_str("],\"nodes\":[");
    for (index, node) in graph.nodes.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"id\":\"{}\",\"kind\":\"{}\",\"label\":\"{}\",\"record_index\":{},\"type_index\":{},\"type_name\":{},\"data_offset\":{},\"count\":{},\"graph_order\":{}}}",
            json_escape(&node.id),
            json_escape(&node.kind),
            json_escape(&node.label),
            json_optional_usize(node.record_index),
            json_optional_u32(node.type_index),
            json_optional_string(node.type_name.as_deref()),
            json_optional_u32(node.data_offset),
            json_optional_u32(node.count),
            node.graph_order
        );
    }
    out.push_str("],\"edges\":[");
    for (index, edge) in graph.edges.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"source\":\"{}\",\"target\":\"{}\",\"relation\":\"{}\",\"source_record_index\":{},\"target_record_index\":{},\"owner_field_name\":{},\"owner_local_offset\":{},\"reference_category\":\"{}\",\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
            json_escape(&edge.source),
            json_escape(&edge.target),
            json_escape(&edge.relation),
            json_optional_usize(edge.source_record_index),
            json_optional_usize(edge.target_record_index),
            json_optional_string(edge.owner_field_name.as_deref()),
            json_optional_usize(edge.owner_local_offset),
            json_escape(&edge.reference_category),
            json_escape(&edge.resolution_source),
            json_escape(&edge.confidence)
        );
    }
    out.push_str("],\"owner_arrays\":[");
    for (index, array) in graph.owner_arrays.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"owner_record_index\":{},\"owner_type_name\":\"{}\",\"field_name\":\"{}\",\"target_record_index\":{},\"target_type_name\":\"{}\",\"array_type\":\"{}\",\"element_type\":\"{}\",\"numelements\":{},\"owner_local_offset\":{},\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
            array.owner_record_index,
            json_escape(&array.owner_type_name),
            json_escape(&array.field_name),
            array.target_record_index,
            json_escape(&array.target_type_name),
            json_escape(&array.array_type),
            json_escape(&array.element_type),
            json_optional_u32(array.numelements),
            array.owner_local_offset,
            json_escape(&array.resolution_source),
            json_escape(&array.confidence)
        );
    }
    out.push_str("]}");
}

pub(crate) fn push_hard_internal_evidence_json(
    out: &mut String,
    report: &HardInternalEvidenceReport,
) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"target_count\":{},\"observed_target_count\":{},\"unresolved_target_count\":{},\"total_observed_byte_count\":{},\"targets\":[",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        report.target_count,
        report.observed_target_count,
        report.unresolved_target_count,
        report.total_observed_byte_count
    );
    for (target_index, target) in report.targets.iter().enumerate() {
        if target_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"description\":\"{}\",\"status\":\"{}\",\"proof_status\":\"{}\",\"present_in_file\":{},\"resolved\":{},\"import_blocking\":{},\"observed_record_count\":{},\"observed_byte_count\":{},\"confidence\":\"{}\",\"observed_types\":[",
            json_escape(&target.key),
            json_escape(&target.label),
            json_escape(&target.description),
            json_escape(&target.status),
            json_escape(&target.proof_status),
            json_bool(target.present_in_file),
            json_bool(target.resolved),
            json_bool(target.import_blocking),
            target.observed_record_count,
            target.observed_byte_count,
            json_escape(&target.confidence)
        );
        for (index, type_name) in target.observed_types.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(type_name));
        }
        out.push_str("],\"observed_fields\":[");
        for (index, field_name) in target.observed_fields.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(field_name));
        }
        out.push_str("],\"record_indices\":[");
        for (index, record_index) in target.record_indices.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "{record_index}");
        }
        out.push_str("],\"unresolved_blockers\":[");
        for (index, blocker) in target.unresolved_blockers.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(blocker));
        }
        out.push_str("]}");
    }
    out.push_str("]}");
}

pub(crate) fn push_real_hkclass_metadata_json(
    out: &mut String,
    report: &RealHkClassMetadataReport,
) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"class_count\":{},\"member_count\":{},\"enum_count\":{},\"recovered_requirements\":",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        report.class_count,
        report.member_count,
        report.enum_count
    );
    out.push('{');
    for (index, (key, value)) in report.recovered_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
    }
    out.push_str("},\"unresolved_requirements\":[");
    for (index, key) in report.unresolved_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(key));
    }
    out.push_str("],\"classes\":[");
    for (class_index, class_info) in report.classes.iter().enumerate() {
        if class_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"record_index\":{},\"parent_record_index\":{},\"parent_name\":{},\"object_size\":{},\"version\":{},\"flags\":{},\"signature\":{},\"signature_hex\":{},\"defaults_record_index\":{},\"attributes_record_index\":{},\"declared_enum_count\":{},\"declared_member_count\":{},\"members_record_index\":{},\"enums_record_index\":{},\"confidence\":\"{}\",\"recovered_requirements\":",
            json_escape(&class_info.name),
            class_info.record_index,
            json_optional_usize(class_info.parent_record_index),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_u32(class_info.object_size),
            json_optional_u32(class_info.version),
            json_optional_u32(class_info.flags),
            json_optional_u32(class_info.signature),
            class_info
                .signature
                .map(|value| format!("\"0x{value:08X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_usize(class_info.defaults_record_index),
            json_optional_usize(class_info.attributes_record_index),
            class_info.declared_enum_count,
            class_info.declared_member_count,
            json_optional_usize(class_info.members_record_index),
            json_optional_usize(class_info.enums_record_index),
            json_escape(&class_info.confidence)
        );
        out.push('{');
        for (index, (key, value)) in class_info.recovered_requirements.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
        }
        out.push_str("},\"unresolved_requirements\":[");
        for (index, key) in class_info.unresolved_requirements.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(key));
        }
        out.push_str("],\"members\":[");
        for (member_index, member) in class_info.members.iter().enumerate() {
            if member_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_index\":{},\"type_code\":{},\"type_name\":\"{}\",\"subtype_code\":{},\"subtype_name\":\"{}\",\"c_array_size\":{},\"flags\":{},\"flags_hex\":\"0x{:X}\",\"offset\":{},\"offset_hex\":\"0x{:X}\",\"class_ref_record_index\":{},\"class_ref_name\":{},\"enum_ref_record_index\":{},\"enum_ref_name\":{},\"attributes_ref_record_index\":{},\"template_ref\":{},\"confidence\":\"{}\"}}",
                json_escape(&member.name),
                member.record_index,
                member.item_index,
                member.type_code,
                json_escape(&member.type_name),
                member.subtype_code,
                json_escape(&member.subtype_name),
                member.c_array_size,
                member.flags,
                member.flags,
                member.offset,
                member.offset,
                json_optional_usize(member.class_ref_record_index),
                json_optional_string(member.class_ref_name.as_deref()),
                json_optional_usize(member.enum_ref_record_index),
                json_optional_string(member.enum_ref_name.as_deref()),
                json_optional_usize(member.attributes_ref_record_index),
                json_optional_string(member.template_ref.as_deref()),
                json_escape(&member.confidence)
            );
        }
        out.push_str("],\"enums\":[");
        for (enum_index, enum_info) in class_info.enums.iter().enumerate() {
            if enum_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_count\":{},\"items_record_index\":{},\"flags\":{},\"confidence\":\"{}\"}}",
                json_escape(&enum_info.name),
                enum_info.record_index,
                enum_info.item_count,
                json_optional_usize(enum_info.items_record_index),
                json_optional_u32(enum_info.flags),
                json_escape(&enum_info.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("]}");
}

pub(crate) fn hkclass_member_array_status(member: &RealHkClassMemberMetadata) -> &'static str {
    if member.type_name.contains("Array")
        || member
            .template_ref
            .as_deref()
            .unwrap_or("")
            .contains("Array")
    {
        "array"
    } else if member.c_array_size > 0 {
        "fixed_c_array"
    } else {
        "not_array"
    }
}

pub(crate) fn hkclass_member_reference_status(member: &RealHkClassMemberMetadata) -> &'static str {
    if member.class_ref_record_index.is_some()
        || member.class_ref_name.is_some()
        || member.type_name.contains("Ref")
        || member.type_name.contains("Pointer")
        || member.template_ref.as_deref().unwrap_or("").contains("Ref")
    {
        "reference"
    } else {
        "not_reference"
    }
}

pub(crate) fn push_real_hkclass_metadata_v2_json(
    out: &mut String,
    report: &RealHkClassMetadataReport,
) {
    let status = if report.class_count > 0 {
        "real_metadata_available_read_only"
    } else {
        "real_metadata_not_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_real_hkclass_metadata_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"class_count\":{},\"member_count\":{},\"enum_count\":{},\"synthetic_fallback_required\":{}",
        status,
        json_escape(&report.format),
        json_bool(report.imported),
        report.class_count,
        report.member_count,
        report.enum_count,
        json_bool(report.class_count == 0)
    );
    out.push_str(",\"recovered_requirements\":");
    out.push('{');
    for (index, (key, value)) in report.recovered_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
    }
    out.push_str("},\"unresolved_requirements\":");
    push_json_string_array(out, &report.unresolved_requirements);
    out.push_str(",\"classes\":[");
    for (class_index, class_info) in report.classes.iter().enumerate() {
        if class_index > 0 {
            out.push(',');
        }
        let metadata_source =
            if class_info.members.is_empty() && class_info.declared_member_count > 0 {
                "real_class_header_members_unresolved"
            } else {
                "real_hkclass_metadata"
            };
        let template_parameter_count = class_info
            .members
            .iter()
            .filter(|member| member.template_ref.is_some())
            .count();
        let _ = write!(
            out,
            "{{\"class_name\":\"{}\",\"name\":\"{}\",\"record_index\":{},\"parent_record_index\":{},\"parent_name\":{},\"base_class\":{},\"object_size\":{},\"version\":{},\"flags\":{},\"flags_hex\":{},\"signature\":{},\"signature_hex\":{},\"defaults_record_index\":{},\"attributes_record_index\":{},\"declared_enum_count\":{},\"declared_member_count\":{},\"member_count\":{},\"enum_count\":{},\"template_parameter_count\":{},\"metadata_source\":\"{}\",\"confidence\":\"{}\"",
            json_escape(&class_info.name),
            json_escape(&class_info.name),
            class_info.record_index,
            json_optional_usize(class_info.parent_record_index),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_u32(class_info.object_size),
            json_optional_u32(class_info.version),
            json_optional_u32(class_info.flags),
            class_info
                .flags
                .map(|value| format!("\"0x{value:X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_u32(class_info.signature),
            class_info
                .signature
                .map(|value| format!("\"0x{value:08X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_usize(class_info.defaults_record_index),
            json_optional_usize(class_info.attributes_record_index),
            class_info.declared_enum_count,
            class_info.declared_member_count,
            class_info.members.len(),
            class_info.enums.len(),
            template_parameter_count,
            metadata_source,
            json_escape(&class_info.confidence)
        );
        out.push_str(",\"unresolved_requirements\":");
        push_json_string_array(out, &class_info.unresolved_requirements);
        out.push_str(",\"members\":[");
        for (member_index, member) in class_info.members.iter().enumerate() {
            if member_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"member_name\":\"{}\",\"record_index\":{},\"item_index\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"byte_size\":{},\"havok_member_type_code\":{},\"member_type_code\":{},\"member_type_name\":\"{}\",\"subtype_code\":{},\"subtype_name\":\"{}\",\"subtype_template_target\":{},\"flags\":{},\"flags_hex\":\"0x{:X}\",\"c_array_size\":{},\"array_status\":\"{}\",\"reference_status\":\"{}\",\"class_ref_record_index\":{},\"class_ref_name\":{},\"enum_ref_record_index\":{},\"enum_ref_name\":{},\"attributes_ref_record_index\":{},\"template_ref\":{},\"confidence\":\"{}\",\"editable\":false,\"edit_policy\":\"read_only_metadata\"}}",
                json_escape(&member.name),
                json_escape(&member.name),
                member.record_index,
                member.item_index,
                member.offset,
                member.offset,
                member.c_array_size,
                member.type_code,
                member.type_code,
                json_escape(&member.type_name),
                member.subtype_code,
                json_escape(&member.subtype_name),
                json_optional_string(member.template_ref.as_deref()),
                member.flags,
                member.flags,
                member.c_array_size,
                hkclass_member_array_status(member),
                hkclass_member_reference_status(member),
                json_optional_usize(member.class_ref_record_index),
                json_optional_string(member.class_ref_name.as_deref()),
                json_optional_usize(member.enum_ref_record_index),
                json_optional_string(member.enum_ref_name.as_deref()),
                json_optional_usize(member.attributes_ref_record_index),
                json_optional_string(member.template_ref.as_deref()),
                json_escape(&member.confidence)
            );
        }
        out.push_str("],\"enums\":[");
        for (enum_index, enum_info) in class_info.enums.iter().enumerate() {
            if enum_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_count\":{},\"items_record_index\":{},\"flags\":{},\"flags_hex\":{},\"confidence\":\"{}\"}}",
                json_escape(&enum_info.name),
                enum_info.record_index,
                enum_info.item_count,
                json_optional_usize(enum_info.items_record_index),
                json_optional_u32(enum_info.flags),
                enum_info
                    .flags
                    .map(|value| format!("\"0x{value:X}\""))
                    .unwrap_or_else(|| "null".to_string()),
                json_escape(&enum_info.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("],\"fallback_policy\":{\"synthetic_types_label\":\"recovered/synthetic\",\"havok_xml_importable\":false}}");
}
