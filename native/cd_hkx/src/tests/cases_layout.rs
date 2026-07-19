use super::fixtures::*;
use crate::*;

#[test]
fn decoder_evidence_v2_reports_owner_arrays_and_class_gaps() {
    let data = root_container_hkx();
    let summary = parse_summary(&data);
    let evidence = &summary.decoder_evidence_v2;
    assert!(evidence.owner_array_count >= 1);
    assert!(
        evidence
            .link_evidence_counts
            .get("declared_owner_array")
            .copied()
            .unwrap_or(0)
            >= 1
    );
    assert!(evidence.class_statuses.iter().any(|row| {
        row.type_name == "hkRootLevelContainer"
            && row
                .link_evidence
                .iter()
                .any(|value| value == "declared_owner_array")
    }));

    let mesh_data = compound_blocker_hkx();
    let mesh_summary = parse_summary(&mesh_data);
    let mesh_evidence = &mesh_summary.decoder_evidence_v2;
    assert!(mesh_evidence.class_statuses.iter().any(|row| {
        row.type_name == "hknpCompoundShape"
            && row.friendly_status.contains("compound child transform")
            && row.read_only
    }));
    let json = summary_to_json(&mesh_summary);
    assert!(json.contains("\"friendly_status\""));
    assert!(json.contains("compound child transform"));
}

#[test]
fn exports_physics_tuning_groups_for_motor_slots() {
    let data = motor_hkx();
    let summary = parse_summary(&data);

    assert_eq!(summary.physics_tuning_groups.len(), 1);
    let group = &summary.physics_tuning_groups[0];
    assert_eq!(group.category, "motor_force_response");
    assert_eq!(group.record_index, 0);
    assert!(group.slots.iter().any(|slot| {
        slot.offset == 0x28 && slot.name == "stiffness_or_strength" && slot.value == 0.8f32
    }));
    assert!(group
        .slots
        .iter()
        .any(|slot| slot.offset == 0x20 && slot.confidence == "strong inference"));
    let motor_object = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpPositionConstraintMotor")
        .unwrap();
    assert!(motor_object
        .fields
        .iter()
        .any(|field| field.name == "stiffness_or_strength[0]" && field.editable));
    let json = summary_to_json(&summary);
    assert!(json.contains("\"physics_tuning_groups\""));
    assert!(json.contains("\"edit_candidate_map_v1\""));
    assert!(json.contains("\"write_enabled\":true"));
    assert!(json.contains("\"new_editable_fields_enabled\":false"));
    assert!(json.contains("\"motor_force_response\""));
    assert!(json.contains("\"stiffness_or_strength\""));
}

#[test]
fn patches_supported_fixed_float_slots_only() {
    let data = motor_hkx();
    let patched = patch_fixed_float(&data, 0, 0, 0x28, 0.6).unwrap();
    let summary = parse_summary(&patched);
    let group = &summary.physics_tuning_groups[0];
    assert!(group
        .slots
        .iter()
        .any(|slot| slot.offset == 0x28 && (slot.value - 0.6).abs() < 0.000_001));
    assert_eq!(patched.len(), data.len());
    assert!(patch_fixed_float(&data, 0, 0, 0x04, 0.6).is_err());
    assert!(patch_fixed_float(&data, 0, 0, 0x28, f32::NAN).is_err());
}

#[test]
fn decodes_sphere_radius_layout() {
    let data = sphere_hkx();
    let summary = parse_summary(&data);
    let sphere = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpSphereShape")
        .unwrap();
    assert!(sphere.fields.iter().any(|field| {
        field.name == "radius" && field.value == Some(LayoutValue::F32(0.25)) && field.editable
    }));
}

#[test]
fn decodes_mass_properties_and_packed_vectors() {
    let data = compressed_mass_hkx();
    let summary = parse_summary(&data);
    let mass = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpShapeMassProperties")
        .unwrap();
    assert!(mass
        .fields
        .iter()
        .any(|field| field.name == "mass_properties_row3_center_mass_or_scale" && field.editable));
    let compressed = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkCompressedMassProperties")
        .unwrap();
    assert!(compressed
        .fields
        .iter()
        .any(|field| field.name == "compressed_mass_properties_sample" && !field.editable));
    let packed = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkPackedVector3")
        .unwrap();
    assert!(packed
        .fields
        .iter()
        .any(|field| field.name == "packed_vector3_rows" && !field.editable));
    let hard_target = summary
        .hard_internal_evidence
        .targets
        .iter()
        .find(|target| target.key == "compressed_mass_properties")
        .unwrap();
    assert_eq!(hard_target.status, "open_observed_unproven");
    assert!(hard_target.present_in_file);
    assert!(hard_target
        .observed_types
        .contains(&"hkCompressedMassProperties".to_string()));
    let json = summary_to_json(&summary);
    assert!(json.contains("compressed_mass_properties_sample"));
    assert!(json.contains("packed_vector3_rows"));
    assert!(json.contains("\"hard_internal_evidence\""));
    assert!(json.contains("\"compressed_mass_properties\""));
}

#[test]
fn decodes_scalar_arrays_and_enum_records() {
    let data = scalar_enum_hkx();
    let summary = parse_summary(&data);
    for (type_name, field_name) in [
        ("unsigned int", "uint32_values"),
        ("unsigned short", "uint16_values"),
        ("unsigned long long", "uint64_values"),
        ("hknpShapeType::Enum", "enum_or_flags_values"),
        ("hknpShape::FlagsEnum", "enum_or_flags_values"),
    ] {
        let object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == type_name)
            .unwrap();
        assert!(
            object
                .fields
                .iter()
                .any(|field| field.name == field_name && !field.editable),
            "missing {field_name} in {type_name}"
        );
    }
    let json = summary_to_json(&summary);
    assert!(json.contains("uint32_values"));
    assert!(json.contains("enum_or_flags_values"));
}

#[test]
fn decodes_box_shape_layout_fields() {
    let data = box_hkx();
    let summary = parse_summary(&data);
    let box_shape = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpBoxShape")
        .unwrap();
    assert!(box_shape
        .fields
        .iter()
        .any(|field| field.name == "box_vertices_offset_count"
            && field.confidence == "strong inference"));
    assert!(box_shape
        .fields
        .iter()
        .any(|field| field.name == "convex_radius_or_collision_margin"
            && field.value == Some(LayoutValue::F32(0.015))));
    assert!(box_shape
        .fields
        .iter()
        .any(|field| field.name == "box_local_frame_or_extents"));
}

#[test]
fn decodes_skeleton_and_material_support_layouts() {
    let data = skeleton_support_hkx();
    let summary = parse_summary(&data);
    for (type_name, field_name) in [
        ("HavokShapeNameProperty", "shape_name_reference"),
        ("hkQsTransform", "qs_transform[0]"),
        ("hkBone", "bone[0]"),
        ("hkInt16", "int16_values"),
        ("hkSkeleton", "bones_reference_or_count_pair"),
        ("hknpMaterial", "material[0]"),
        ("hknpMaterial", "material_surface_response_a[0]"),
    ] {
        let object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == type_name)
            .unwrap();
        assert!(
            object.fields.iter().any(|field| field.name == field_name),
            "missing {field_name} in {type_name}"
        );
    }
}

#[test]
fn decodes_skeleton_mapper_support_layouts() {
    let data = skeleton_mapper_support_hkx();
    let summary = parse_summary(&data);
    for (type_name, field_name) in [
        ("char", "ascii_or_utf8_text"),
        ("hkaSkeletonMapper", "source_skeleton_or_root_reference"),
        ("hkaSkeletonMapperData::SimpleMapping", "simple_mapping[0]"),
        ("hkaAnimationContainer", "animation_container_pair_0x18"),
        ("int", "int32_values"),
    ] {
        let object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == type_name)
            .unwrap();
        assert!(
            object.fields.iter().any(|field| field.name == field_name),
            "missing {field_name} in {type_name}"
        );
    }
}

#[test]
fn decodes_root_scene_and_constraint_container_layouts() {
    let data = root_container_hkx();
    let summary = parse_summary(&data);
    let root = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkRootLevelContainer")
        .unwrap();
    assert!(root
        .fields
        .iter()
        .any(|field| field.name == "named_variants_size"));
    let variant = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkRootLevelContainer::NamedVariant")
        .unwrap();
    assert!(variant
        .fields
        .iter()
        .any(|field| field.name == "object_reference"));
    let scene = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpPhysicsSceneData")
        .unwrap();
    assert!(scene
        .fields
        .iter()
        .any(|field| field.name == "u32_pair_0x0"));
    let constraint = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpConstraintCinfo")
        .unwrap();
    assert!(constraint
        .fields
        .iter()
        .any(|field| field.name == "body_a_reference_or_index_pair"));
    let graph = &summary.native_model_graph;
    assert_eq!(graph.root.record_index, Some(0));
    assert_eq!(graph.root.method, "native_hkRootLevelContainer");
    assert!(graph.owner_array_count >= 1);
    assert!(graph.owner_arrays.iter().any(|array| {
        array.owner_record_index == 0
            && array.field_name == "namedVariants"
            && array.array_type == "hkArray<hkRootLevelContainer::NamedVariant>"
            && array.numelements == Some(1)
    }));
    assert_eq!(graph.graph_order.first().copied(), Some(0));
}

#[test]
fn decodes_root_reference_and_physics_system_payloads() {
    let data = root_reference_payload_hkx();
    let summary = parse_summary(&data);
    for (type_name, field_name) in [
        ("hkRefVariant", "referenced_value"),
        ("hkStringPtr", "reference_metadata_pair"),
        ("hkMemoryResourceContainer", "reference_or_value_pair_0x0"),
        ("hknpPhysicsSystemData", "materials_array_or_reference_pair"),
        ("hknpConstraintData", "reference_or_value_pair_0x0"),
        ("hknpRefDragProperties", "finite_float_candidates"),
        ("hknpRefMassDistribution", "finite_float_candidates"),
    ] {
        let object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == type_name)
            .unwrap();
        assert!(
            object
                .fields
                .iter()
                .any(|field| field.name == field_name && !field.editable),
            "missing {field_name} in {type_name}"
        );
    }
}

#[test]
fn decodes_real_hkclass_member_metadata_records() {
    let data = real_hkclass_metadata_hkx();
    let summary = parse_summary(&data);
    let metadata = &summary.real_hkclass_metadata;

    assert_eq!(metadata.format, "cd_hkx_real_hkclass_metadata_v1");
    assert_eq!(metadata.status, "real_hkclass_records_decoded");
    assert_eq!(metadata.class_count, 1);
    assert_eq!(metadata.member_count, 2);
    assert_eq!(
        metadata.recovered_requirements.get("member_type_codes"),
        Some(&true)
    );
    assert_eq!(
        metadata.recovered_requirements.get("member_flags"),
        Some(&true)
    );
    assert_eq!(
        metadata.recovered_requirements.get("signatures"),
        Some(&true)
    );
    assert_eq!(metadata.recovered_requirements.get("versions"), Some(&true));
    assert_eq!(
        metadata.recovered_requirements.get("template_refs"),
        Some(&true)
    );

    let class_info = &metadata.classes[0];
    assert_eq!(class_info.name, "hknpFoo");
    assert_eq!(class_info.object_size, Some(64));
    assert_eq!(class_info.version, Some(3));
    assert_eq!(class_info.flags, Some(4));
    assert_eq!(class_info.signature, Some(0xABCDEF01));
    assert_eq!(class_info.declared_member_count, 2);
    assert_eq!(class_info.members_record_index, Some(4));
    let mass = class_info
        .members
        .iter()
        .find(|member| member.name == "mass")
        .unwrap();
    assert_eq!(mass.type_code, 11);
    assert_eq!(mass.type_name, "TYPE_REAL");
    assert_eq!(mass.flags, 0x1234);
    assert_eq!(mass.offset, 0x20);
    let child = class_info
        .members
        .iter()
        .find(|member| member.name == "child")
        .unwrap();
    assert_eq!(child.type_name, "TYPE_POINTER");
    assert_eq!(child.subtype_name, "TYPE_STRUCT");
    assert_eq!(child.class_ref_name.as_deref(), Some("hknpFoo"));
    assert_eq!(child.template_ref.as_deref(), Some("hknpFoo"));

    let json = summary_to_json(&summary);
    assert!(json.contains("\"real_hkclass_metadata\""));
    assert!(json.contains("\"real_hkclass_metadata_v2\""));
    assert!(json.contains("\"havok_member_type_code\":11"));
    assert!(json.contains("\"reference_status\":\"reference\""));
    assert!(json.contains("\"synthetic_fallback_required\":false"));
    assert!(json.contains("\"type_code\":11"));
    assert!(json.contains("\"flags_hex\":\"0x1234\""));
    assert!(json.contains("\"signature_hex\":\"0xABCDEF01\""));
}

#[test]
fn decodes_body_and_constraint_reference_fields() {
    let data = body_constraint_reference_hkx();
    let summary = parse_summary(&data);
    for (type_name, field_name) in [
        (
            "hknpPhysicsSystemData",
            "body_cinfo_array_or_reference_pair",
        ),
        (
            "hknpPhysicsSystemData::ExtendedBodyCinfo",
            "shape_reference_or_key_pair",
        ),
        (
            "hknpPhysicsSystemData::ExtendedBodyCinfo",
            "motion_properties_reference_pair",
        ),
        (
            "hknpPhysicsSystemData::ExtendedBodyCinfo",
            "body_transform_or_orientation_row0_x[0]",
        ),
        ("hknpConstraintCinfo", "body_a_reference_or_index_pair"),
        ("hknpConstraintCinfo", "constraint_data_reference_pair"),
    ] {
        let object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == type_name)
            .unwrap();
        assert!(
            object.fields.iter().any(|field| field.name == field_name),
            "missing {field_name} in {type_name}"
        );
    }
}

#[test]
fn decodes_compound_tree_instance_and_property_blocker_layouts() {
    let data = compound_blocker_hkx();
    let summary = parse_summary(&data);
    let compound = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpCompoundShape")
        .unwrap();
    assert!(compound
        .fields
        .iter()
        .any(|field| field.name == "shape_instances_or_storage_pair"));
    let instance = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpShapeInstance")
        .unwrap();
    assert!(instance
        .fields
        .iter()
        .any(|field| field.name == "shape_instance[0]"));
    let node = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hkcdSimdTreeNamespace::Node")
        .unwrap();
    assert!(node
        .fields
        .iter()
        .any(|field| field.name == "simd_tree_node[0]"));
    let property = summary
        .object_records
        .iter()
        .find(|record| record.type_name == "hknpShapeProperties::Entry")
        .unwrap();
    assert!(property
        .fields
        .iter()
        .any(|field| field.name == "property_entry[0]"));
    let hard = &summary.hard_internal_evidence;
    assert_eq!(hard.format, "cd_hkx_hard_internal_evidence_v1");
    assert_eq!(hard.status, "hard_internals_observed_unproven");
    for key in [
        "compound_child_transforms",
        "hknp_mesh_aabb_tree",
        "material_property_entries",
        "compressed_mass_properties",
    ] {
        let target = hard
            .targets
            .iter()
            .find(|target| target.key == key)
            .unwrap();
        assert!(target.present_in_file, "missing hard target {key}");
        assert_eq!(target.proof_status, "needs_corpus_proof");
        assert!(!target.resolved);
        assert!(target.observed_record_count > 0);
    }
}

#[test]
fn builds_native_skeleton_preview_from_reference_pose() {
    let preview = build_hkx_preview(&skeleton_support_hkx());
    assert_eq!(preview.status, "ok");
    assert_eq!(preview.preview_kind, "skeleton");
    assert_eq!(preview.bone_count, 2);
    assert_eq!(preview.bones[0].parent_index, -1);
    assert_eq!(preview.bones[1].parent_index, 0);
    assert_eq!(preview.bones[0].position, [0.0, 1.0, 2.0]);
    assert_eq!(preview.bones[1].position, [1.0, 2.0, 4.0]);
    let json = hkx_preview_to_json(&preview);
    assert!(json.contains("\"preview_kind\":\"skeleton\""));
    assert!(json.contains("\"bone_count\":2"));
}

#[test]
fn builds_native_sphere_collision_preview_without_proxy_nodes() {
    let preview = build_hkx_preview(&sphere_hkx());
    assert_eq!(preview.status, "ok");
    assert_eq!(preview.preview_kind, "collision");
    assert_eq!(preview.shape_count, 1);
    assert_eq!(preview.shapes[0].shape_type, "sphere");
    assert_eq!(preview.shapes[0].center, Some([0.0, 0.0, 0.0]));
    assert_eq!(preview.shapes[0].radius, Some(0.25));
    let json = hkx_preview_to_json(&preview);
    assert!(json.contains("\"format\":\"cd_hkx_preview_v2\""));
    assert!(json.contains("\"shape_type\":\"sphere\""));
    assert!(!json.contains("\"nodes\""));
}

#[test]
fn builds_native_box_collision_preview_from_recovered_extents() {
    let preview = build_hkx_preview(&box_hkx());
    assert_eq!(preview.status, "ok");
    assert_eq!(preview.preview_kind, "collision");
    assert_eq!(preview.shape_count, 1);
    assert_eq!(preview.shapes[0].shape_type, "box");
    assert_eq!(preview.shapes[0].center, Some([-4.5, 1.0, 6.25]));
    assert_eq!(preview.shapes[0].half_extents, Some([0.075, 0.048, 0.009]));
}

#[test]
fn arbitrary_object_graph_is_not_rendered_as_proxy_bones() {
    let preview = build_hkx_preview(&sample_hkx());
    assert_eq!(preview.status, "unsupported");
    assert_eq!(preview.preview_kind, "unsupported");
    assert!(preview.bones.is_empty());
    assert!(preview.shapes.is_empty());
    let json = hkx_preview_to_json(&preview);
    assert!(!json.contains("\"nodes\""));
    assert!(!json.contains("\"edges\""));
}
