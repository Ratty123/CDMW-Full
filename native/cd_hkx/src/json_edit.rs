use crate::*;

pub(crate) fn representative_hkx_roles() -> [&'static str; 6] {
    [
        "object",
        "meshphysics",
        "character_physics",
        "ragdoll_body",
        "mesh_heavy",
        "animation",
    ]
}

pub(crate) fn push_semantic_writer_gate_v1_json(out: &mut String, readiness: &HkxModdingReadiness) {
    let gate = &readiness.semantic_writer_gate;
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_semantic_writer_gate_v1\",\"status\":\"semantic_writer_disabled_until_byte_identity_proof\",\"source_status\":\"{}\",\"enabled\":false,\"semantic_rebuild_supported\":false,\"havok_xml_import_unblocked\":false,\"raw_preserving_no_edit_writer_available\":true,\"fixed_size_patch_importable\":{},\"patchable_slot_count\":{},\"mismatch_offset\":null,\"unsupported_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\"],\"unsupported_ref_kinds\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"]",
        json_escape(&gate.status),
        json_bool(readiness.fixed_size_patch_importable),
        readiness.patchable_slot_count
    );
    out.push_str(",\"writer_modes\":[");
    for (index, (mode, status, enabled, reason)) in [
        (
            "raw_preserving_no_edit",
            "available",
            true,
            "lossless byte segment writer; not semantic Havok XML import",
        ),
        (
            "semantic_no_edit",
            "disabled_pending_representative_byte_identity",
            false,
            "requires semantic model write to match bytes for all representative roles",
        ),
        (
            "semantic_fixed_edit",
            "disabled_pending_fixed_edit_tests",
            false,
            "requires no-edit identity plus per-field fixed-edit proof",
        ),
        (
            "havok_xml_import",
            "blocked",
            false,
            "blocked until semantic writer gates pass",
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
            "{{\"mode\":\"{}\",\"status\":\"{}\",\"enabled\":{},\"reason\":\"{}\"}}",
            mode,
            status,
            json_bool(*enabled),
            json_escape(reason)
        );
    }
    out.push(']');
    out.push_str(",\"required_role_coverage\":[");
    for (index, role) in representative_hkx_roles().iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"no_edit_status\":\"required\",\"semantic_no_edit_status\":\"required_not_verified_by_semantic_writer\",\"fixed_edit_status\":\"required\",\"byte_identity_status\":\"required_not_verified_by_semantic_writer\",\"sample_required\":true,\"fixed_size_edits_allowed\":false,\"havok_xml_import_unblocked\":false}}",
            role
        );
    }
    out.push_str("],\"representative_role_gates\":[");
    for (index, role) in representative_hkx_roles().iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"required\":true,\"no_edit_byte_identity\":\"not_proven_by_semantic_writer\",\"mismatch_offset\":null,\"unsupported_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\"],\"unsupported_ref_kinds\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"],\"fixed_size_edits_allowed\":false,\"status\":\"representative_corpus_required\"}}",
            role
        );
    }
    out.push_str("],\"blocked_edit_classes\":");
    push_json_string_array(out, &gate.blocked_edits);
    out.push_str(",\"requirements\":");
    push_json_string_array(out, &gate.requirements);
    out.push('}');
}

pub(crate) fn write_type_for_slot_name(name: &str) -> &'static str {
    let lower = name.to_ascii_lowercase();
    if lower.contains("x") || lower.contains("y") || lower.contains("z") || lower.contains("w") {
        "f32_component"
    } else {
        "f32"
    }
}

pub(crate) fn edit_candidate_structural_kind(
    class_name: &str,
    member_name: &str,
    category: &str,
) -> &'static str {
    let haystack = format!(
        "{} {} {}",
        class_name.to_ascii_lowercase(),
        member_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if haystack.contains("primitive")
        || haystack.contains("topology")
        || haystack.contains("face")
        || haystack.contains("edge")
        || haystack.contains("count")
        || haystack.contains("array")
        || haystack.contains("ref")
        || haystack.contains("string")
    {
        "structural_blocked"
    } else if haystack.contains("radius")
        || haystack.contains("endpoint")
        || haystack.contains("transform")
        || haystack.contains("orientation")
        || haystack.contains("mass")
        || haystack.contains("friction")
        || haystack.contains("damping")
        || haystack.contains("motor")
        || haystack.contains("constraint")
        || haystack.contains("material")
    {
        "fixed_size_numeric"
    } else {
        "fixed_size_numeric_candidate"
    }
}

pub(crate) fn edit_candidate_task_key(
    class_name: &str,
    member_name: &str,
    category: &str,
) -> &'static str {
    let haystack = format!(
        "{} {} {}",
        class_name.to_ascii_lowercase(),
        member_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if haystack.contains("material")
        || haystack.contains("friction")
        || haystack.contains("restitution")
        || haystack.contains("surface")
    {
        "material_friction"
    } else if haystack.contains("damping")
        || haystack.contains("motion")
        || haystack.contains("velocity")
        || haystack.contains("sharedmotion")
    {
        "damping_motion"
    } else if haystack.contains("constraint")
        || haystack.contains("motor")
        || haystack.contains("stiffness")
        || haystack.contains("strength")
        || haystack.contains("force")
        || haystack.contains("torque")
        || haystack.contains("limit")
        || haystack.contains("hinge")
        || haystack.contains("ragdoll")
    {
        "joint_strength"
    } else if haystack.contains("body")
        || haystack.contains("transform")
        || haystack.contains("orientation")
        || haystack.contains("mass")
    {
        "body_transform"
    } else if haystack.contains("primitive")
        || haystack.contains("winding")
        || haystack.contains("aabb")
        || haystack.contains("topology")
    {
        "mesh_winding"
    } else if haystack.contains("shape")
        || haystack.contains("collision")
        || haystack.contains("radius")
        || haystack.contains("capsule")
        || haystack.contains("sphere")
        || haystack.contains("extent")
    {
        "collision_size"
    } else {
        "inspect_only"
    }
}

pub(crate) fn edit_candidate_task_label(task_key: &str) -> &'static str {
    match task_key {
        "collision_size" => "Collision Size",
        "body_transform" => "Body Transform",
        "joint_strength" => "Joint Strength",
        "damping_motion" => "Damping / Motion",
        "material_friction" => "Material / Friction",
        "mesh_winding" => "Mesh Winding",
        _ => "Inspect Only",
    }
}

pub(crate) fn edit_candidate_category_key(
    class_name: &str,
    member_name: &str,
    category: &str,
) -> String {
    if !category.is_empty() {
        return category.to_string();
    }
    match edit_candidate_task_key(class_name, member_name, category) {
        "collision_size" => "collision_size",
        "body_transform" => "body_transform_mass",
        "joint_strength" => "joint_limits_strength",
        "damping_motion" => "motion_damping_solver",
        "material_friction" => "material_surface_response",
        "mesh_winding" => "mesh_winding",
        _ => "native_scalar_candidate",
    }
    .to_string()
}

pub(crate) fn edit_candidate_linked_by(
    class_name: &str,
    category: &str,
    write_enabled: bool,
) -> &'static str {
    let haystack = format!(
        "{} {}",
        class_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if write_enabled {
        "existing_patch_map"
    } else if haystack.contains("array") {
        "owner_array"
    } else if haystack.contains("ref") {
        "fixup_backed_or_inferred"
    } else {
        "typed_layout"
    }
}

pub(crate) fn push_tuning_edit_candidates_json(
    out: &mut String,
    physics_tuning_groups: &[PhysicsTuningGroup],
    objects: &[ObjectRecord],
    mut emitted: usize,
) -> usize {
    for group in physics_tuning_groups {
        let object = objects
            .iter()
            .find(|object| object.record_index == group.record_index);
        let record_absolute_offset = object.and_then(|object| object.absolute_data_offset);
        for slot in &group.slots {
            if emitted > 0 {
                out.push(',');
            }
            emitted += 1;
            let risk_label =
                if slot.confidence == "confirmed" || slot.confidence == "strong inference" {
                    "medium"
                } else {
                    "high"
                };
            let record_relative_offset = slot.item_index * group.stride + slot.offset;
            let absolute_offset = record_absolute_offset.map(|base| base + record_relative_offset);
            let structural_kind =
                edit_candidate_structural_kind(&group.type_name, &slot.name, &group.category);
            let linked_by = edit_candidate_linked_by(&group.type_name, &group.category, true);
            let task_key = edit_candidate_task_key(&group.type_name, &slot.name, &group.category);
            let task_label = edit_candidate_task_label(task_key);
            let _ = write!(
                    out,
                    "{{\"class\":\"{}\",\"owner_class\":\"{}\",\"category\":\"{}\",\"category_label\":\"{}\",\"task_category\":\"{}\",\"task_label\":\"{}\",\"member\":\"{}\",\"field\":\"{}\",\"name\":\"{}\",\"record\":{},\"record_index\":{},\"item_index\":{},\"local_offset\":{},\"record_relative_offset\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"absolute_offset\":{},\"absolute_offset_hex\":\"{}\",\"byte_size\":4,\"original_value\":{},\"supported_write_type\":\"{}\",\"write_type\":\"{}\",\"value_kind\":\"fixed_size_numeric\",\"structural_kind\":\"{}\",\"import_safety\":\"import_safe\",\"risk_label\":\"{}\",\"risk\":\"{}\",\"confidence\":\"{}\",\"evidence\":\"native physics tuning fixed-size float scan; exact record/item/local offset recovered\",\"link_evidence\":\"{}\",\"linked_by\":\"{}\",\"linked_target\":\"{}\",\"import_path\":\"existing_fixed_size_patch\",\"import_behavior\":\"CDMW fixed-size float patch into original HKX bytes\",\"write_enabled\":true,\"gate_status\":\"enabled\",\"gate_reason\":\"covered by existing fixed-size CDMW patch route\",\"edit_rule\":\"{}\"}}",
                    json_escape(&group.type_name),
                    json_escape(&group.type_name),
                    json_escape(&group.category),
                    json_escape(task_label),
                    json_escape(task_key),
                    json_escape(task_label),
                    json_escape(&slot.name),
                    json_escape(&slot.name),
                    json_escape(&slot.name),
                    group.record_index,
                    group.record_index,
                    slot.item_index,
                    slot.offset,
                    record_relative_offset,
                    slot.offset,
                    slot.offset,
                    json_optional_usize(absolute_offset),
                    absolute_offset
                        .map(|offset| format!("0x{:X}", offset))
                        .unwrap_or_default(),
                    if slot.value.is_finite() { slot.value.to_string() } else { "null".to_string() },
                    write_type_for_slot_name(&slot.name),
                    write_type_for_slot_name(&slot.name),
                    structural_kind,
                    risk_label,
                    risk_label,
                    json_escape(&slot.confidence),
                    linked_by,
                    linked_by,
                    json_escape(&group.label),
                    json_escape(&group.edit_rule)
                );
        }
    }
    emitted
}

pub(crate) fn push_layout_edit_candidates_json(
    out: &mut String,
    objects: &[ObjectRecord],
    mut emitted: usize,
) -> usize {
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            if emitted > 0 {
                out.push(',');
            }
            emitted += 1;
            let absolute_offset = object.absolute_data_offset.map(|base| base + field.offset);
            let structural_kind =
                edit_candidate_structural_kind(&object.type_name, &field.name, "");
            let linked_by = edit_candidate_linked_by(&object.type_name, "", false);
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let task_label = edit_candidate_task_label(task_key);
            let write_type = if field.data_type.contains("float") {
                "f32"
            } else {
                "fixed_size_numeric"
            };
            let _ = write!(
                    out,
                    "{{\"class\":\"{}\",\"owner_class\":\"{}\",\"category\":\"{}\",\"category_label\":\"{}\",\"task_category\":\"{}\",\"task_label\":\"{}\",\"member\":\"{}\",\"field\":\"{}\",\"name\":\"{}\",\"record\":{},\"record_index\":{},\"item_index\":null,\"local_offset\":{},\"record_relative_offset\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"absolute_offset\":{},\"absolute_offset_hex\":\"{}\",\"byte_size\":{},\"original_value\":{},\"supported_write_type\":\"{}\",\"write_type\":\"{}\",\"value_kind\":\"fixed_size_numeric_candidate\",\"structural_kind\":\"{}\",\"import_safety\":\"read_only\",\"risk_label\":\"high\",\"risk\":\"high\",\"confidence\":\"{}\",\"evidence\":\"typed layout editable flag; exact byte span observed, but write route requires fixed-edit proof\",\"link_evidence\":\"{}\",\"linked_by\":\"{}\",\"linked_target\":\"record/{}\",\"import_path\":\"blocked_until_fixed_edit_test\",\"import_behavior\":\"read-only until fixed-edit tests prove byte patch safety\",\"write_enabled\":false,\"gate_status\":\"candidate_only\",\"gate_reason\":\"decoded fixed-size field candidate lacks approved import route\",\"edit_rule\":\"candidate_only\"}}",
                    json_escape(&object.type_name),
                    json_escape(&object.type_name),
                    json_escape(&category),
                    json_escape(task_label),
                    json_escape(task_key),
                    json_escape(task_label),
                    json_escape(&field.name),
                    json_escape(&field.name),
                    json_escape(&field.name),
                    object.record_index,
                    object.record_index,
                    field.offset,
                    field.offset,
                    field.offset,
                    field.offset,
                    json_optional_usize(absolute_offset),
                    absolute_offset
                        .map(|offset| format!("0x{:X}", offset))
                        .unwrap_or_default(),
                    field.size,
                    json_layout_value(&field.value),
                    write_type,
                    write_type,
                    structural_kind,
                    json_escape(&field.confidence),
                    linked_by,
                    linked_by,
                    object.record_index
                );
        }
    }
    emitted
}

pub(crate) fn push_edit_candidate_map_v1_json(
    out: &mut String,
    physics_tuning_groups: &[PhysicsTuningGroup],
    objects: &[ObjectRecord],
) {
    let tuning_candidate_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let layout_candidate_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let candidate_count = tuning_candidate_count + layout_candidate_count;
    let mut task_categories: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for group in physics_tuning_groups {
        let task_key = edit_candidate_task_key(&group.type_name, "", &group.category);
        let entry = task_categories
            .entry(task_key.to_string())
            .or_insert((0, 0));
        entry.0 += group.slots.len();
    }
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let entry = task_categories
                .entry(task_key.to_string())
                .or_insert((0, 0));
            entry.1 += 1;
        }
    }
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_edit_candidate_map_v1\",\"status\":\"fixed_size_numeric_candidates_only\",\"imported\":false,\"read_only\":false,\"new_editable_fields_enabled\":false,\"existing_patchable_slots_exposed\":{},\"candidate_count\":{},\"write_enabled_candidate_count\":{}",
        json_bool(tuning_candidate_count > 0),
        candidate_count,
        tuning_candidate_count
    );
    out.push_str(",\"blocked_kinds\":[\"arrays\",\"references\",\"strings\",\"topology\",\"counts\",\"compressed_tables\",\"class_metadata\"],\"task_categories\":[");
    for (index, task_key) in [
        "collision_size",
        "material_friction",
        "damping_motion",
        "joint_strength",
        "body_transform",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let (enabled_count, candidate_count) =
            task_categories.get(*task_key).copied().unwrap_or((0, 0));
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{}}}",
            task_key,
            edit_candidate_task_label(task_key),
            status,
            enabled_count,
            candidate_count
        );
    }
    out.push_str("],\"candidates\":[");
    let mut emitted = 0usize;
    emitted = push_tuning_edit_candidates_json(out, physics_tuning_groups, objects, emitted);
    let _ = push_layout_edit_candidates_json(out, objects, emitted);
    out.push_str("]}");
}

pub(crate) fn push_hkx_edit_gate_v1_json(
    out: &mut String,
    physics_tuning_groups: &[PhysicsTuningGroup],
    objects: &[ObjectRecord],
) {
    let write_enabled_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let candidate_only_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_edit_gate_v1\",\"status\":\"fixed_size_patch_gate\",\"read_only\":true,\"new_editable_fields_enabled\":false,\"write_enabled_candidate_count\":{},\"candidate_only_count\":{},\"blocked_policy\":\"arrays, strings, references, topology, counts, compressed tables, and class metadata remain blocked until semantic rebuild proof\"",
        write_enabled_count,
        candidate_only_count
    );
    out.push_str(",\"required_role_coverage\":[");
    for (index, role) in [
        "object",
        "meshphysics",
        "character_physics",
        "ragdoll_body",
        "mesh_heavy",
        "animation",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"no_edit_status\":\"required\",\"fixed_edit_status\":\"required\",\"status\":\"representative_corpus_required\"}}",
            role
        );
    }
    out.push_str("],\"categories\":[");
    let mut emitted = 0usize;
    let mut categories: BTreeMap<String, (usize, usize, String)> = BTreeMap::new();
    let mut task_categories: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for group in physics_tuning_groups {
        let entry = categories
            .entry(group.category.clone())
            .or_insert_with(|| (0, 0, group.type_name.clone()));
        entry.0 += group.slots.len();
        let task_key = edit_candidate_task_key(&group.type_name, "", &group.category);
        let task_entry = task_categories
            .entry(task_key.to_string())
            .or_insert((0, 0));
        task_entry.0 += group.slots.len();
    }
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let entry = categories
                .entry(category.clone())
                .or_insert_with(|| (0, 0, object.type_name.clone()));
            entry.1 += 1;
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let task_entry = task_categories
                .entry(task_key.to_string())
                .or_insert((0, 0));
            task_entry.1 += 1;
        }
    }
    for (category, (enabled_count, candidate_count, owner_class)) in categories {
        if emitted > 0 {
            out.push(',');
        }
        emitted += 1;
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let reason = if enabled_count > 0 {
            "existing fixed-size patch route"
        } else if candidate_count > 0 {
            "decoded candidate lacks fixed-edit corpus proof"
        } else {
            "no approved fixed-size patch target"
        };
        let _ = write!(
            out,
            "{{\"category\":\"{}\",\"owner_class\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{},\"fixed_edit_test_status\":\"{}\",\"gate_reason\":\"{}\"}}",
            json_escape(&category),
            json_escape(&owner_class),
            status,
            enabled_count,
            candidate_count,
            if enabled_count > 0 { "existing_route" } else { "required" },
            reason
        );
    }
    if emitted > 0 {
        out.push(',');
    }
    out.push_str("{\"category\":\"structural_edits\",\"owner_class\":\"*\",\"status\":\"blocked\",\"write_enabled_count\":0,\"candidate_only_count\":0,\"fixed_edit_test_status\":\"blocked\",\"gate_reason\":\"topology/count/reference/string/array edits require semantic rebuild proof\"}");
    out.push_str("],\"task_categories\":[");
    for (index, task_key) in [
        "collision_size",
        "material_friction",
        "damping_motion",
        "joint_strength",
        "body_transform",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let (enabled_count, candidate_count) =
            task_categories.get(*task_key).copied().unwrap_or((0, 0));
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let reason = if enabled_count > 0 {
            "existing fixed-size patch route"
        } else if candidate_count > 0 {
            "decoded candidate lacks fixed-edit corpus proof"
        } else {
            "no approved fixed-size patch target"
        };
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{},\"fixed_edit_test_status\":\"{}\",\"gate_reason\":\"{}\"}}",
            task_key,
            edit_candidate_task_label(task_key),
            status,
            enabled_count,
            candidate_count,
            if enabled_count > 0 { "existing_route" } else { "required" },
            reason
        );
    }
    out.push_str("],\"blocked_kinds\":[\"array\",\"string\",\"reference\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\",\"shape_primitive_count\"]}");
}

pub(crate) fn push_class_decoder_evidence_v2_json(
    out: &mut String,
    decoder: &DecoderEvidenceV2,
    hard: &HardInternalEvidenceReport,
) {
    let mut hard_by_type: BTreeMap<String, Vec<&HardInternalEvidenceTarget>> = BTreeMap::new();
    for target in &hard.targets {
        for type_name in &target.observed_types {
            hard_by_type
                .entry(type_name.clone())
                .or_default()
                .push(target);
        }
    }
    let status = if decoder.class_status_count > 0 {
        "class_specific_decode_evidence_available"
    } else {
        "class_specific_decode_evidence_not_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_class_decoder_evidence_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"class_status_count\":{},\"hard_target_count\":{},\"observed_hard_target_count\":{}",
        status,
        json_escape(&decoder.format),
        json_bool(decoder.imported),
        decoder.class_status_count,
        hard.target_count,
        hard.observed_target_count
    );
    out.push_str(",\"class_statuses\":[");
    for (index, row) in decoder.class_statuses.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let hard_targets = hard_by_type.get(&row.type_name);
        let _ = write!(
            out,
            "{{\"class\":\"{}\",\"type_name\":\"{}\",\"record_count\":{},\"byte_count\":{},\"decoded_field_count\":{},\"reference_count\":{},\"editable_candidate_count\":{},\"status\":\"{}\",\"friendly_status\":\"{}\",\"read_only\":{},\"corpus_priority_score\":{}",
            json_escape(&row.type_name),
            json_escape(&row.type_name),
            row.record_count,
            row.byte_count,
            row.decoded_field_count,
            row.reference_count,
            row.editable_field_count,
            json_escape(&row.status),
            json_escape(&row.friendly_status),
            json_bool(row.read_only),
            row.corpus_priority_score
        );
        out.push_str(",\"missing_requirements\":");
        push_json_string_array(out, &row.missing_requirements);
        out.push_str(",\"link_evidence\":");
        push_json_string_array(out, &row.link_evidence);
        out.push_str(",\"hard_internal_targets\":[");
        if let Some(targets) = hard_targets {
            for (target_index, target) in targets.iter().enumerate() {
                if target_index > 0 {
                    out.push(',');
                }
                let _ = write!(
                    out,
                    "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"proof_status\":\"{}\",\"resolved\":{},\"confidence\":\"{}\"}}",
                    json_escape(&target.key),
                    json_escape(&target.label),
                    json_escape(&target.status),
                    json_escape(&target.proof_status),
                    json_bool(target.resolved),
                    json_escape(&target.confidence)
                );
            }
        }
        out.push_str("]}");
    }
    out.push_str("],\"missing_semantics_policy\":\"read-only until class layout, refs, arrays, and writer gate are proven\"}");
}

pub(crate) fn push_decoder_evidence_v2_json(out: &mut String, report: &DecoderEvidenceV2) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"read_only\":{},\"class_status_count\":{},\"priority_class_count\":{},\"total_partial_byte_count\":{},\"unresolved_or_packed_case_count\":{},\"owner_array_count\":{}",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        json_bool(report.read_only),
        report.class_status_count,
        report.priority_class_count,
        report.total_partial_byte_count,
        report.unresolved_or_packed_case_count,
        report.owner_array_count
    );
    out.push_str(",\"reference_semantic_counts\":");
    push_json_count_map(out, &report.reference_semantic_counts);
    out.push_str(",\"link_evidence_counts\":");
    push_json_count_map(out, &report.link_evidence_counts);
    out.push_str(",\"class_statuses\":[");
    for (index, row) in report.class_statuses.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"type_name\":\"{}\",\"record_count\":{},\"byte_count\":{},\"decoded_field_count\":{},\"reference_count\":{},\"editable_field_count\":{},\"status\":\"{}\",\"friendly_status\":\"{}\",\"corpus_priority_score\":{},\"read_only\":{}",
            json_escape(&row.type_name),
            row.record_count,
            row.byte_count,
            row.decoded_field_count,
            row.reference_count,
            row.editable_field_count,
            json_escape(&row.status),
            json_escape(&row.friendly_status),
            row.corpus_priority_score,
            json_bool(row.read_only)
        );
        out.push_str(",\"missing_requirements\":[");
        for (requirement_index, requirement) in row.missing_requirements.iter().enumerate() {
            if requirement_index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(requirement));
        }
        out.push_str("],\"link_evidence\":[");
        for (evidence_index, evidence) in row.link_evidence.iter().enumerate() {
            if evidence_index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(evidence));
        }
        out.push_str("]}");
    }
    out.push_str("],\"fixup_backed_fields\":[");
    for (index, field) in report.fixup_backed_fields.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"class_name\":\"{}\",\"field_name\":\"{}\",\"reference_category\":\"{}\",\"count\":{},\"confidence\":\"{}\"}}",
            json_escape(&field.class_name),
            json_escape(&field.field_name),
            json_escape(&field.reference_category),
            field.count,
            json_escape(&field.confidence)
        );
    }
    out.push_str("]}");
}
