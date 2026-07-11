use crate::*;

pub(crate) fn decode_shape_property_entry_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpShapeProperties::Entry" && record.count > 0 && payload.len() >= 16 {
        let entry_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * entry_stride;
            if base + 16 > payload.len() {
                break;
            }
            let key = le_u32(&payload[base..base + 4]).unwrap_or(0);
            let value = le_u32(&payload[base + 4..base + 8]).unwrap_or(0);
            let flags = le_u32(&payload[base + 8..base + 12]).unwrap_or(0);
            let user = le_u32(&payload[base + 12..base + 16]).unwrap_or(0);
            fields.push(layout_field(
                &format!("property_entry[{item_index}]"),
                base,
                entry_stride.min(16),
                "uint32[4]",
                Some(LayoutValue::Text(format!(
                    "key_or_id={key}, value_or_reference={value}, flags_or_type={flags}, user_data={user}"
                ))),
                "Likely hknp shape-property entry row. Exact key/value/flags names are not confirmed.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_free_list_element_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name.starts_with("hkFreeListArrayElement") && record.count > 0 {
        let element_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * element_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..element_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("free_list_element[{item_index}]"),
                base,
                element_stride,
                "uint32[]/free-list-element",
                Some(LayoutValue::Text(words)),
                "Free-list element backing compound/shape-instance storage. List rebuilding is not supported.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_compound_shape_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpCompoundShape" && payload.len() >= 32 {
        for (offset, name, description) in [
            (
                0x00usize,
                "base_or_vtable_words",
                "Initial object/base words for hknpCompoundShape.",
            ),
            (
                0x20usize,
                "shape_instances_or_storage_pair",
                "Possible child shape instance storage offset/count or reference pair.",
            ),
            (
                0x30usize,
                "simd_tree_or_bounds_pair",
                "Possible tree/bounds reference or count pair.",
            ),
            (
                0x40usize,
                "free_list_or_child_metadata_pair",
                "Possible free-list/child metadata pair.",
            ),
            (
                0x50usize,
                "shape_property_or_flags_pair",
                "Possible property/flags pair.",
            ),
            (
                0x60usize,
                "compound_runtime_pair",
                "Possible runtime/cache pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let first = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let second = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!("{first}, {second}"))),
                description,
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_shape_instance_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpShapeInstance" && record.count > 0 {
        let instance_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * instance_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..instance_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("shape_instance[{item_index}]"),
                base,
                instance_stride,
                "uint32[]/shape-instance",
                Some(LayoutValue::Text(words)),
                "Child shape-instance row. Likely links child shape data, transform/filter metadata, and shape keys.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_simd_tree_node_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkcdSimdTreeNamespace::Node" && record.count > 0 {
        let node_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(128) {
            let base = item_index * node_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..node_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("simd_tree_node[{item_index}]"),
                base,
                node_stride,
                "uint32[]/float32[]/tree-node",
                Some(LayoutValue::Text(words)),
                "Spatial acceleration tree node used by compound/mesh shapes. Bounds/child encoding is not fully named yet.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_root_container_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkRootLevelContainer" && payload.len() >= 16 {
        fields.push(layout_field(
            "named_variants_data_reference",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely array/reference to hkRootLevelContainer::NamedVariant records.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "named_variants_size",
            8,
            4,
            "uint32",
            le_u32(&payload[8..12]).map(LayoutValue::U32),
            "Likely number of root named variants.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "named_variants_capacity_and_flags",
            12,
            4,
            "uint32",
            le_u32(&payload[12..16]).map(LayoutValue::U32),
            "Likely Havok array capacity/flags for root variants. Structural edits are not supported.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_named_variant_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkRootLevelContainer::NamedVariant" && payload.len() >= 24 {
        for (offset, name, description) in [
            (
                0usize,
                "name_reference",
                "Likely reference to variant name string.",
            ),
            (
                8usize,
                "class_name_reference",
                "Likely reference to Havok class/type name string.",
            ),
            (
                16usize,
                "object_reference",
                "Likely reference to the root object for this named variant.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint64/reference",
                le_u64(&payload[offset..offset + 8]).map(LayoutValue::U64),
                description,
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_physics_system_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpPhysicsSystemData" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "materials_array_or_reference_pair",
                "Likely reference/count pair for hknpMaterial rows.",
            ),
            (
                0x08usize,
                "motion_properties_array_or_reference_pair",
                "Likely reference/count pair for hknpSharedMotionProperties rows.",
            ),
            (
                0x10usize,
                "body_cinfo_array_or_reference_pair",
                "Likely reference/count pair for ExtendedBodyCinfo body rows.",
            ),
            (
                0x18usize,
                "constraint_cinfo_array_or_reference_pair",
                "Likely reference/count pair for hknpConstraintCinfo rows.",
            ),
            (
                0x20usize,
                "shape_reference_array_or_pair",
                "Likely reference/count pair for shape references.",
            ),
            (
                0x28usize,
                "system_metadata_or_flags_pair",
                "Likely physics-system metadata, flags, or runtime pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/reference_count",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Structural array/reference edits are not supported."),
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_extended_body_cinfo_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "body_base_flags_or_type_pair",
                "Likely body type, flags, or base metadata pair.",
            ),
            (
                0x08usize,
                "shape_reference_or_key_pair",
                "Likely shape reference/index plus shape-key or flags.",
            ),
            (
                0x10usize,
                "motion_properties_reference_pair",
                "Likely reference/index to hknpSharedMotionProperties.",
            ),
            (
                0x18usize,
                "material_or_collision_filter_pair",
                "Likely material/filter/collision-layer metadata.",
            ),
            (
                0x20usize,
                "body_name_user_data_or_bone_pair",
                "Likely body name, user data, bone, or attachment index metadata.",
            ),
            (
                0x28usize,
                "body_transform_header_pair",
                "Likely header before transform/orientation float block.",
            ),
            (
                0x50usize,
                "body_runtime_or_quality_pair",
                "Likely runtime quality/motion/activation metadata.",
            ),
            (
                0x60usize,
                "body_mass_or_inertia_header_pair",
                "Likely header near mass/inertia-related fields.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/body-cinfo",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Kept read-only until exact body schema is confirmed."),
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_constraint_cinfo_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpConstraintCinfo" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "body_a_reference_or_index_pair",
                "Likely first constrained body reference/index pair.",
            ),
            (
                0x08usize,
                "body_b_reference_or_index_pair",
                "Likely second constrained body reference/index pair.",
            ),
            (
                0x10usize,
                "constraint_data_reference_pair",
                "Likely reference/index to hknpConstraintData or concrete constraint data.",
            ),
            (
                0x18usize,
                "constraint_priority_flags_pair",
                "Likely priority, collision, enable, or runtime flags.",
            ),
            (
                0x20usize,
                "constraint_user_data_or_metadata_pair",
                "Likely user data or constraint metadata pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/constraint-cinfo",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Constraint reference edits are not supported."),
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_scene_or_ragdoll_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if matches!(type_name, "hknpPhysicsSceneData" | "hknpRagdollData") {
        for offset in (0..payload.len().min(128)).step_by(8) {
            if offset + 8 > payload.len() {
                break;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            let description = match type_name {
                "hknpConstraintCinfo" => {
                    "Possible body/constraint reference or flags pair. Structural reference edits are not supported."
                }
                "hknpPhysicsSceneData" => {
                    "Possible physics-system/body/constraint array reference or count pair."
                }
                "hknpRagdollData" => {
                    "Possible ragdoll body/constraint/skeleton array reference or count pair."
                }
                _ => "Unverified pair of 32-bit words.",
            };
            fields.push(layout_field(
                &format!("u32_pair_0x{offset:X}"),
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                description,
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}
