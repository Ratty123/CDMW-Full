use crate::*;

pub(crate) fn decode_array_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name.starts_with("hkArray") && payload.len() >= 16 {
        fields.push(layout_field(
            "data_reference_or_offset",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely Havok array data reference or offset. Exact 2024.2 reference encoding is still unconfirmed.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "size",
            8,
            4,
            "uint32",
            le_u32(&payload[8..12]).map(LayoutValue::U32),
            "Likely current array element count.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "capacity_and_flags",
            12,
            4,
            "uint32",
            le_u32(&payload[12..16]).map(LayoutValue::U32),
            "Likely Havok array capacity and flags word. Rebuilding this safely is not supported yet.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_ref_ptr_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name.starts_with("hkRefPtr") && payload.len() >= 8 {
        fields.push(layout_field(
            "referenced_object",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely Havok reference pointer payload.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_float3_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkFloat3" && record.count > 0 && payload.len() >= record.count as usize * 12 {
        fields.push(layout_field(
            "float3_rows",
            0,
            record.count as usize * 12,
            "float32[3][]",
            Some(LayoutValue::Text(format!(
                "row_count={}, stride=12",
                record.count
            ))),
            "Local-space vector rows. For decoded convex shapes these are usually vertices.",
            "strong inference",
            true,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_vector4_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkVector4" && record.count > 0 && payload.len() >= record.count as usize * 16 {
        fields.push(layout_field(
            "float4_rows",
            0,
            record.count as usize * 16,
            "float32[4][]",
            Some(LayoutValue::Text(format!(
                "row_count={}, stride=16",
                record.count
            ))),
            "Four-float vector rows. For decoded convex shapes these are usually plane equations.",
            "strong inference",
            true,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_qs_transform_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkQsTransform"
        && record.count > 0
        && payload.len() >= record.count as usize * 48
    {
        let transform_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(128) {
            let base = item_index * transform_stride;
            if base + 48 > payload.len() {
                break;
            }
            let translation = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + component * 4..base + component * 4 + 4]).unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            let rotation = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + 16 + component * 4..base + 20 + component * 4])
                        .unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            let scale = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + 32 + component * 4..base + 36 + component * 4])
                        .unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            fields.push(layout_field(
                &format!("qs_transform[{item_index}]"),
                base,
                48,
                "struct{hkVector4 translation; hkQuaternion rotation; hkVector4 scale}",
                Some(LayoutValue::Text(format!(
                    "translation=({translation}); rotation=({rotation}); scale=({scale})"
                ))),
                "Read-only hkQsTransform row. Usually skeleton pose or mapping data; editing requires skeleton schema validation.",
                "strong inference",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_bone_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkBone" && record.count > 0 && payload.len() >= record.count as usize * 16 {
        let bone_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(256) {
            let base = item_index * bone_stride;
            if base + 16 > payload.len() {
                break;
            }
            let name_ref = le_u32(&payload[base..base + 4]).unwrap_or(0);
            let parent_or_lock = i32::from_le_bytes([
                payload[base + 8],
                payload[base + 9],
                payload[base + 10],
                payload[base + 11],
            ]);
            let flags = le_u32(&payload[base + 12..base + 16]).unwrap_or(0);
            fields.push(layout_field(
                &format!("bone[{item_index}]"),
                base,
                bone_stride,
                "uint32 name_ref; int32 parent_or_lock; uint32 flags",
                Some(LayoutValue::Text(format!(
                    "name_reference={name_ref}, parent_or_lock={parent_or_lock}, flags_or_axis={flags}"
                ))),
                "Read-only hkBone row. Skeleton rebuilding is not supported.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_int16_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkInt16" && record.count > 0 && payload.len() >= record.count as usize * 2 {
        fields.push(layout_field(
            "int16_values",
            0,
            (record.count as usize * 2).min(payload.len()),
            "int16[]",
            Some(LayoutValue::Text(format!("value_count={}", record.count))),
            "Read-only hkInt16 array. In skeleton files this often stores parent indices or compact index maps.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_scalar_array_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if let Some((field_name, data_type, byte_width, description)) = scalar_array_spec(type_name) {
        if record.count > 0 && payload.len() >= byte_width {
            fields.push(layout_field(
                field_name,
                0,
                payload.len().min(record.count as usize * byte_width),
                data_type,
                Some(LayoutValue::Text(scalar_sample(
                    payload,
                    byte_width,
                    record.count,
                    64,
                ))),
                &format!("{description} Editing is disabled until the owning Havok object field is confirmed."),
                "strong inference",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_enum_record_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if let Some(description) = enum_record_description(type_name) {
        if record.count > 0 && !payload.is_empty() {
            let count = record.count.max(1) as usize;
            let stride = if payload.len() % count == 0 {
                Some(payload.len() / count)
            } else {
                None
            };
            let byte_width = if matches!(stride, Some(1 | 2 | 4 | 8)) {
                stride.unwrap()
            } else if payload.len() >= count * 4 {
                4
            } else if payload.len() >= count * 2 {
                2
            } else {
                1
            };
            fields.push(layout_field(
                "enum_or_flags_values",
                0,
                payload.len().min(record.count as usize * byte_width),
                &format!("enum/flags[{byte_width}-byte]"),
                Some(LayoutValue::Text(scalar_sample(
                    payload,
                    byte_width,
                    record.count,
                    64,
                ))),
                &format!("{description} Names for each numeric value are not fully mapped yet, so this is read-only context."),
                "strong inference",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_int32_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "int" && record.count > 0 && payload.len() >= record.count as usize * 4 {
        let values = (0..(record.count as usize).min(512))
            .map(|index| {
                let offset = index * 4;
                i32::from_le_bytes([
                    payload[offset],
                    payload[offset + 1],
                    payload[offset + 2],
                    payload[offset + 3],
                ])
            })
            .map(|value| value.to_string())
            .collect::<Vec<_>>()
            .join(", ");
        fields.push(layout_field(
            "int32_values",
            0,
            (record.count as usize * 4).min(payload.len()),
            "int32[]",
            Some(LayoutValue::Text(format!(
                "value_count={}, values=[{}]",
                record.count, values
            ))),
            "Read-only int array. In skeleton/mapper files this commonly stores compact bone or mapping indices.",
            "strong inference",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_string_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "char" && !payload.is_empty() {
        let nul_index = payload
            .iter()
            .position(|value| *value == 0)
            .unwrap_or(payload.len());
        let text = String::from_utf8_lossy(&payload[..nul_index]).to_string();
        fields.push(layout_field(
            "ascii_or_utf8_text",
            0,
            payload.len(),
            "char[]",
            Some(LayoutValue::Text(text)),
            "Read-only string payload. String editing is not safe because it can change record length and reference layout.",
            if nul_index < payload.len() {
                "confirmed"
            } else {
                "strong inference"
            },
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_convex_face_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpConvexHull::Face"
        && record.count > 0
        && payload.len() >= record.count as usize * 4
    {
        fields.push(layout_field(
            "face_records",
            0,
            record.count as usize * 4,
            "struct{u16 index_start; u8 vertex_count; u8 meta}[]",
            Some(LayoutValue::Text(format!(
                "record_count={}, stride=4",
                record.count
            ))),
            "Convex face table. index_start points into the face-index byte array.",
            "strong inference",
            true,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_uint8_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkUint8" && record.count > 0 {
        fields.push(layout_field(
            "byte_values",
            0,
            (record.count as usize).min(payload.len()),
            "uint8[]",
            Some(LayoutValue::Text(format!("value_count={}", record.count))),
            "Byte array. In decoded convex hulls this is usually the face vertex index buffer.",
            "strong inference",
            true,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_convex_edge_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpConvexHull::Edge"
        && record.count > 0
        && payload.len() >= record.count as usize * 4
    {
        fields.push(layout_field(
            "uint16_pairs",
            0,
            record.count as usize * 4,
            "uint16[2][]",
            Some(LayoutValue::Text(format!(
                "pair_count={}, stride=4",
                record.count
            ))),
            "Convex edge/support pairs. Topology role is still inferred.",
            "strong inference",
            true,
        ));

        true
    } else {
        false
    }
}
