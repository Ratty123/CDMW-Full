use crate::*;

pub(crate) fn scalar_array_spec(
    type_name: &str,
) -> Option<(&'static str, &'static str, usize, &'static str)> {
    match type_name {
        "unsigned char" => Some((
            "uint8_values",
            "uint8[]",
            1,
            "Read-only unsigned-byte array. These records commonly back compact flags, shape-key bytes, or mesh/physics index data.",
        )),
        "unsigned short" => Some((
            "uint16_values",
            "uint16[]",
            2,
            "Read-only unsigned-short array. These records commonly store compact indices, flags, or mesh/physics lookup values.",
        )),
        "unsigned int" => Some((
            "uint32_values",
            "uint32[]",
            4,
            "Read-only unsigned-int array. These records commonly store references, flags, counts, shape keys, or table words.",
        )),
        "unsigned long long" => Some((
            "uint64_values",
            "uint64[]",
            8,
            "Read-only unsigned 64-bit array. These records commonly store large identifiers, masks, or packed references.",
        )),
        "long long" => Some((
            "int64_values",
            "int64[]",
            8,
            "Read-only signed 64-bit array. These records are exported for comparison and reference recovery.",
        )),
        _ => None,
    }
}

pub(crate) fn enum_record_description(type_name: &str) -> Option<&'static str> {
    match type_name {
        "hknpShapeType::Enum" => Some("Shape kind enum values used by hknp shapes."),
        "hknpCollisionDispatchType::Enum" => {
            Some("Collision dispatch enum values used by hknp broad/narrow phase routing.")
        }
        "hknpShape::FlagsEnum" => Some("Shape flag bitfields used by hknp shape records."),
        "hkcdSimdTreeNamespace::Node::FlagsEnum" => Some("Spatial tree node flag bitfields."),
        _ => None,
    }
}

pub(crate) fn scalar_sample(payload: &[u8], byte_width: usize, count: u32, limit: usize) -> String {
    let decoded_count = (payload.len() / byte_width).min(count as usize);
    let values = (0..decoded_count.min(limit))
        .map(|index| {
            let offset = index * byte_width;
            match byte_width {
                1 => payload[offset].to_string(),
                2 => le_u16(&payload[offset..offset + 2])
                    .unwrap_or(0)
                    .to_string(),
                4 => le_u32(&payload[offset..offset + 4])
                    .unwrap_or(0)
                    .to_string(),
                8 => le_u64(&payload[offset..offset + 8])
                    .unwrap_or(0)
                    .to_string(),
                _ => "0".to_string(),
            }
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!("value_count={count}, decoded_count={decoded_count}, values=[{values}]")
}

pub(crate) fn decode_layout_fields(payload: &[u8], record: &ItemRecord) -> Vec<LayoutField> {
    let mut fields = Vec::new();
    let _decoded = decode_array_layout(payload, record, &mut fields)
        || decode_ref_ptr_layout(payload, record, &mut fields)
        || decode_float3_layout(payload, record, &mut fields)
        || decode_vector4_layout(payload, record, &mut fields)
        || decode_qs_transform_layout(payload, record, &mut fields)
        || decode_bone_layout(payload, record, &mut fields)
        || decode_int16_layout(payload, record, &mut fields)
        || decode_scalar_array_layout(payload, record, &mut fields)
        || decode_enum_record_layout(payload, record, &mut fields)
        || decode_int32_layout(payload, record, &mut fields)
        || decode_string_layout(payload, record, &mut fields)
        || decode_convex_face_layout(payload, record, &mut fields)
        || decode_uint8_layout(payload, record, &mut fields)
        || decode_convex_edge_layout(payload, record, &mut fields)
        || decode_mass_properties_layout(payload, record, &mut fields)
        || decode_compressed_mass_properties_layout(payload, record, &mut fields)
        || decode_packed_vector3_layout(payload, record, &mut fields)
        || decode_shape_name_property_layout(payload, record, &mut fields)
        || decode_material_layout(payload, record, &mut fields)
        || decode_skeleton_layout(payload, record, &mut fields)
        || decode_skeleton_mapper_layout(payload, record, &mut fields)
        || decode_simple_mapping_layout(payload, record, &mut fields)
        || decode_animation_container_layout(payload, record, &mut fields)
        || decode_ref_variant_layout(payload, record, &mut fields)
        || decode_reference_value_pairs_layout(payload, record, &mut fields)
        || decode_shape_property_entry_layout(payload, record, &mut fields)
        || decode_free_list_element_layout(payload, record, &mut fields)
        || decode_compound_shape_layout(payload, record, &mut fields)
        || decode_shape_instance_layout(payload, record, &mut fields)
        || decode_simd_tree_node_layout(payload, record, &mut fields)
        || decode_root_container_layout(payload, record, &mut fields)
        || decode_named_variant_layout(payload, record, &mut fields)
        || decode_physics_system_layout(payload, record, &mut fields)
        || decode_extended_body_cinfo_layout(payload, record, &mut fields)
        || decode_constraint_cinfo_layout(payload, record, &mut fields)
        || decode_scene_or_ragdoll_layout(payload, record, &mut fields);
    add_tuning_floats_layout(payload, record, &mut fields);
    add_sphere_capsule_radius_layout(payload, record, &mut fields);
    add_mesh_shape_header_layout(payload, record, &mut fields);
    add_geometry_section_layout(payload, record, &mut fields);
    add_mesh_primitive_layout(payload, record, &mut fields);
    add_aabb_tree_layout(payload, record, &mut fields);
    add_convex_shape_layout(payload, record, &mut fields);
    add_box_shape_layout(payload, record, &mut fields);
    add_box_sample_layout(payload, record, &mut fields);
    add_hknp_fallback_layout(payload, record, &mut fields);
    add_word_fallback_layout(payload, record, &mut fields);
    add_raw_fallback_layout(payload, record, &mut fields);
    fields
}
