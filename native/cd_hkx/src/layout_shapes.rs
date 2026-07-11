use crate::*;

pub(crate) fn decode_mass_properties_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpShapeMassProperties" && payload.len() >= 64 {
        for (row_index, name, description) in [
            (
                0usize,
                "mass_properties_row0_basis_or_inertia",
                "Mass-property row 0. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                1usize,
                "mass_properties_row1_basis_or_inertia",
                "Mass-property row 1. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                2usize,
                "mass_properties_row2_basis_or_inertia",
                "Mass-property row 2. In tested payloads this often resembles a basis/inertia row or transform-like vector.",
            ),
            (
                3usize,
                "mass_properties_row3_center_mass_or_scale",
                "Mass-property row 3. In sampled shape records this is the most likely center/mass/scale-like row, but exact fields remain experimental.",
            ),
        ] {
            let offset = row_index * 16;
            let row = (0..4usize)
                .map(|component| {
                    le_f32(&payload[offset + component * 4..offset + component * 4 + 4])
                        .unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            fields.push(layout_field(
                name,
                offset,
                16,
                "float32[4]",
                Some(LayoutValue::Text(row)),
                description,
                "experimental",
                true,
            ));
        }
        fields.push(layout_field(
            "mass_property_float4_rows",
            0,
            64,
            "float32[4][4]",
            Some(LayoutValue::Text("row_count=4, stride=16".to_string())),
            "Mass-property matrix/vector payload. Exact Havok field names are not recovered yet.",
            "experimental",
            true,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_compressed_mass_properties_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkCompressedMassProperties" && payload.len() >= 16 {
        let words = (0..payload.len().min(64) / 4)
            .map(|word_index| le_u32(&payload[word_index * 4..word_index * 4 + 4]).unwrap_or(0))
            .map(|word| format!("0x{word:08X}"))
            .collect::<Vec<_>>()
            .join(" ");
        fields.push(layout_field(
            "compressed_mass_properties_sample",
            0,
            payload.len().min(96),
            "hkCompressedMassProperties/read-only",
            Some(LayoutValue::Text(format!(
                "payload_bytes={}, u32_words={words}",
                payload.len()
            ))),
            "Read-only compressed mass-property payload sample. Havok stores mass/inertia/center data in a compact form here; exact 2024.2 packing rules are not recovered, so edits are disabled.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_packed_vector3_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkPackedVector3" && record.count > 0 && payload.len() >= 4 {
        let packed_stride = (payload.len() / record.count.max(1) as usize).max(4);
        let row_limit = (record.count as usize).min(128);
        let mut samples = Vec::new();
        for item_index in 0..row_limit.min(12) {
            let base = item_index * packed_stride;
            if base + 4 > payload.len() {
                break;
            }
            let bytes = &payload[base..base + 4];
            samples.push(format!(
                "#{item_index}@0x{base:X}=({}, {}, {}, {})",
                bytes[0], bytes[1], bytes[2], bytes[3]
            ));
        }
        fields.push(layout_field(
            "packed_vector3_rows",
            0,
            payload.len().min(row_limit * packed_stride),
            "hkPackedVector3[]/read-only",
            Some(LayoutValue::Text(format!(
                "row_count={}, candidate_stride={}, samples={}",
                record.count,
                packed_stride,
                samples.join("; ")
            ))),
            "Read-only packed vector rows. Byte triplets are useful for comparing compressed mass or shape payloads, but edits are disabled until scale/offset ownership is recovered.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_shape_name_property_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "HavokShapeNameProperty" && payload.len() >= 0x24 {
        let raw_name_reference = le_u32(&payload[0x20..0x24]).unwrap_or(0);
        fields.push(layout_field(
            "shape_name_reference",
            0x20,
            4,
            "uint32/char_record_reference",
            Some(LayoutValue::Text(format!(
                "raw_value={}, candidate_char_record_index={}",
                raw_name_reference,
                if raw_name_reference > 0 {
                    (raw_name_reference - 1).to_string()
                } else {
                    "none".to_string()
                }
            ))),
            "Read-only HavokShapeNameProperty name reference. In tested Crimson Desert files this value minus one points to a char record containing the body/shape label.",
            "strong inference",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_material_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hknpMaterial" && record.count > 0 {
        let material_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(128) {
            let base = item_index * material_stride;
            if base >= payload.len() {
                break;
            }
            for offset in (0..material_stride.min(64).saturating_sub(3)).step_by(4) {
                let absolute_offset = base + offset;
                if absolute_offset + 4 > payload.len() {
                    continue;
                }
                let Some(value) = le_f32(&payload[absolute_offset..absolute_offset + 4]) else {
                    continue;
                };
                if !value.is_finite() || value.abs() < 1e-8 || value.abs() > 1_000_000.0 {
                    continue;
                }
                fields.push(layout_field(
                    &format!("{}[{item_index}]", fixed_float_slot_name(type_name, offset)),
                    absolute_offset,
                    4,
                    "float32",
                    Some(LayoutValue::F32(value)),
                    &fixed_float_slot_description(type_name, offset),
                    fixed_float_slot_confidence(type_name, offset),
                    true,
                ));
            }
            let words = (0..material_stride.min(48) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("material[{item_index}]"),
                base,
                material_stride,
                "hknpMaterial/read-only",
                Some(LayoutValue::Text(words)),
                "Read-only hknpMaterial row. Likely friction/restitution/filter/material flags; exact field names are not confirmed.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}
