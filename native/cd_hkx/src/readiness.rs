use crate::*;

pub(crate) fn object_type_contains(objects: &[ObjectRecord], needles: &[&str]) -> usize {
    objects
        .iter()
        .filter(|object| {
            needles
                .iter()
                .any(|needle| object.type_name.contains(needle))
        })
        .count()
}

pub(crate) fn editable_field_count_for_types(objects: &[ObjectRecord], needles: &[&str]) -> usize {
    objects
        .iter()
        .filter(|object| {
            needles
                .iter()
                .any(|needle| object.type_name.contains(needle))
        })
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum()
}

pub(crate) fn tuning_slot_count_for_categories(
    groups: &[PhysicsTuningGroup],
    categories: &[&str],
) -> usize {
    groups
        .iter()
        .filter(|group| {
            categories
                .iter()
                .any(|category| group.category == *category)
        })
        .map(|group| group.slots.len())
        .sum()
}

pub(crate) fn tuning_group_count_for_categories(
    groups: &[PhysicsTuningGroup],
    categories: &[&str],
) -> usize {
    groups
        .iter()
        .filter(|group| {
            categories
                .iter()
                .any(|category| group.category == *category)
        })
        .count()
}

pub(crate) fn modding_task_group(
    key: &str,
    label: &str,
    patchable_slot_count: usize,
    context_record_count: usize,
    evidence: Vec<String>,
    risk: &str,
    description: &str,
) -> HkxModdingTaskGroup {
    let readiness_label = if patchable_slot_count > 0 {
        "Patchable tuning"
    } else if context_record_count > 0 {
        "Read-only decoded"
    } else {
        "No recovered rows"
    };
    HkxModdingTaskGroup {
        key: key.to_string(),
        label: label.to_string(),
        readiness_label: readiness_label.to_string(),
        patchable_slot_count,
        context_record_count,
        evidence,
        risk: risk.to_string(),
        import_safe: patchable_slot_count > 0,
        description: description.to_string(),
    }
}

pub(crate) fn build_modding_task_groups(
    objects: &[ObjectRecord],
    physics_tuning_groups: &[PhysicsTuningGroup],
) -> Vec<HkxModdingTaskGroup> {
    vec![
            modding_task_group(
                "collision_size",
                "Collision size",
                editable_field_count_for_types(
                    objects,
                    &[
                        "hknpConvexShape",
                        "hknpBoxShape",
                        "hknpSphereShape",
                        "hknpCapsuleShape",
                        "hknpTriangleShape",
                    ],
                ),
                object_type_contains(
                    objects,
                    &[
                        "hknpConvexShape",
                        "hknpBoxShape",
                        "hknpSphereShape",
                        "hknpCapsuleShape",
                        "hknpTriangleShape",
                        "hknpMeshShape",
                        "hknpCompoundShape",
                        "hknpShapeInstance",
                    ],
                ),
                vec!["typed_layout".to_string(), "raw_observation".to_string()],
                "Low when patchable",
                "Collision shape radius, extents, endpoints, and decoded geometry context.",
            ),
            modding_task_group(
                "body_transform",
                "Body transform",
                tuning_slot_count_for_categories(physics_tuning_groups, &["body_transform_mass"])
                    + editable_field_count_for_types(objects, &["ExtendedBodyCinfo"]),
                tuning_group_count_for_categories(physics_tuning_groups, &["body_transform_mass"])
                    + object_type_contains(objects, &["ExtendedBodyCinfo"]),
                vec!["typed_layout".to_string(), "native_tuning_slots".to_string()],
                "High",
                "Body frames, transform-like rows, mass/inertia-like rows, and solver body setup.",
            ),
            modding_task_group(
                "damping_motion",
                "Damping / motion",
                tuning_slot_count_for_categories(physics_tuning_groups, &["motion_damping_solver"]),
                tuning_group_count_for_categories(physics_tuning_groups, &["motion_damping_solver"])
                    + object_type_contains(objects, &["hknpSharedMotionProperties"]),
                vec!["native_tuning_slots".to_string(), "typed_layout".to_string()],
                "Medium",
                "Shared motion-property rows that can affect damping, response, and motion thresholds.",
            ),
            modding_task_group(
                "joint_limits_strength",
                "Joint limits / strength",
                tuning_slot_count_for_categories(
                    physics_tuning_groups,
                    &["joint_limits_strength", "motor_force_response"],
                ),
                tuning_group_count_for_categories(
                    physics_tuning_groups,
                    &["joint_limits_strength", "motor_force_response"],
                ) + object_type_contains(
                    objects,
                    &[
                        "hknpConstraint",
                        "hknpRagdollConstraintData",
                        "hknpLimitedHingeConstraintData",
                        "hknpPositionConstraintMotor",
                    ],
                ),
                vec![
                    "native_tuning_slots".to_string(),
                    "fixup_backed".to_string(),
                    "owner_array".to_string(),
                ],
                "Medium to High",
                "Constraint frames, limits, motor force/response rows, strength, and damping-like values.",
            ),
            modding_task_group(
                "materials",
                "Materials",
                editable_field_count_for_types(objects, &["hknpMaterial", "hknpShapeProperties::Entry"]),
                object_type_contains(
                    objects,
                    &["hknpMaterial", "hknpShapeProperties::Entry", "hkFreeListArrayElement"],
                ),
                vec!["typed_layout".to_string(), "declared_owner_array".to_string()],
                "Context only",
                "Physics material and shape-property tables. Currently useful for browsing/linking, not broad editing.",
            ),
            modding_task_group(
                "skeleton_animation",
                "Skeleton / animation",
                editable_field_count_for_types(objects, &["hkSkeleton", "hkaAnimationContainer"]),
                object_type_contains(
                    objects,
                    &[
                        "hkSkeleton",
                        "hkBone",
                        "hkQsTransform",
                        "hkaAnimationContainer",
                        "hkaSkeletonMapper",
                    ],
                ),
                vec!["typed_layout".to_string(), "raw_observation".to_string()],
                "Read-only",
                "Skeleton bones, transforms, animation containers, and mapper rows for browsing and relationship evidence.",
            ),
        ]
}

pub(crate) fn build_hkx_modding_readiness(
    objects: &[ObjectRecord],
    graph: &NativeModelGraph,
    hard_internal_evidence: &HardInternalEvidenceReport,
    real_hkclass_metadata: &RealHkClassMetadataReport,
    decoder_evidence: &DecoderEvidenceV2,
    physics_tuning_groups: &[PhysicsTuningGroup],
) -> HkxModdingReadiness {
    let decoded_object_count = objects
        .iter()
        .filter(|object| object.status != "raw_preserved" && object.status != "raw")
        .count();
    let native_editable_field_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let tuning_slot_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let patchable_slot_count = native_editable_field_count + tuning_slot_count;

    let mut readiness_labels = Vec::<String>::new();
    if patchable_slot_count > 0 {
        readiness_labels.push("Patchable tuning".to_string());
    }
    if decoded_object_count > 0 || !decoder_evidence.class_statuses.is_empty() {
        readiness_labels.push("Read-only decoded".to_string());
    }
    if decoder_evidence.priority_class_count > 0
        || hard_internal_evidence.unresolved_target_count > 0
        || !real_hkclass_metadata.unresolved_requirements.is_empty()
        || graph.edge_count > graph.fixup_backed_reference_edge_count
    {
        readiness_labels.push("Needs semantic rebuild".to_string());
    }
    if objects.is_empty() && physics_tuning_groups.is_empty() {
        readiness_labels.push("Unsupported structure".to_string());
    }
    if readiness_labels.is_empty() {
        readiness_labels.push("Read-only decoded".to_string());
    }

    let per_file_label = if patchable_slot_count > 0 {
        "Patchable tuning"
    } else if decoded_object_count > 0 {
        "Read-only decoded"
    } else if objects.is_empty() {
        "Unsupported structure"
    } else {
        "Needs semantic rebuild"
    }
    .to_string();
    let status = if patchable_slot_count > 0 {
        "fixed_size_patchable"
    } else if decoded_object_count > 0 {
        "read_only_decoded"
    } else {
        "unsupported_structure"
    };

    let task_groups = build_modding_task_groups(objects, physics_tuning_groups);

    HkxModdingReadiness {
        format: "cd_hkx_modding_readiness_v1".to_string(),
        status: status.to_string(),
        imported: false,
        read_only: true,
        per_file_label,
        readiness_labels,
        fixed_size_patch_importable: patchable_slot_count > 0,
        havok_xml_importable: false,
        new_editable_fields_enabled: false,
        decoded_object_count,
        patchable_slot_count,
        fixup_backed_reference_edge_count: graph.fixup_backed_reference_edge_count,
        owner_array_count: graph.owner_array_count,
        unresolved_or_packed_case_count: decoder_evidence.unresolved_or_packed_case_count,
        semantic_writer_gate: HkxSemanticWriterGate {
            status: "disabled_pending_semantic_rebuild".to_string(),
            mode: "fixed_size_patch_only".to_string(),
            enabled: false,
            raw_preserving_no_edit_writer_required: true,
            semantic_rebuild_supported: false,
            fixed_size_value_edits_allowed: true,
            allowed_edits: vec!["existing fixed-size CDMW patch rows".to_string()],
            blocked_edits: vec![
                "Havok XML import".to_string(),
                "array count edits".to_string(),
                "reference edits".to_string(),
                "string edits".to_string(),
                "mesh topology edits".to_string(),
                "semantic object graph rebuild".to_string(),
            ],
            requirements: vec![
                "byte-identical no-edit rebuild across representative corpus".to_string(),
                "fixup-backed object/data/string/type reference semantics".to_string(),
                "owner-array element typing".to_string(),
                "root/container/named-variant semantics".to_string(),
                "fixed-edit byte identity tests".to_string(),
            ],
        },
        task_groups,
    }
}
