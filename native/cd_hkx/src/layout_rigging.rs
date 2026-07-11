use crate::*;

pub(crate) fn decode_skeleton_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkSkeleton" && payload.len() >= 64 {
        for (offset, name, description) in [
            (
                0x18usize,
                "bones_reference_or_count_pair",
                "Likely skeleton bone array reference/count pair.",
            ),
            (
                0x28usize,
                "parent_indices_reference_or_count_pair",
                "Likely parent-index array reference/count pair.",
            ),
            (
                0x38usize,
                "reference_pose_reference_or_count_pair",
                "Likely reference-pose transform array reference/count pair.",
            ),
            (
                0x48usize,
                "float_slots_or_metadata_pair",
                "Possible skeleton float slots or metadata reference/count pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/reference_count",
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                &format!("{description} Structural skeleton edits are not supported."),
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_skeleton_mapper_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkaSkeletonMapper" && payload.len() >= 64 {
        for (offset, name, description) in [
            (
                0x20usize,
                "source_skeleton_or_root_reference",
                "Likely source skeleton/root reference. In paired Crimson Desert mapper records this value swaps with the target reference.",
            ),
            (
                0x28usize,
                "target_skeleton_or_root_reference",
                "Likely target skeleton/root reference. Used to browse mapper direction; structural edits are not supported.",
            ),
            (
                0x60usize,
                "mapper_data_or_mapping_reference",
                "Likely mapper-data reference or compact mapping record index. Exact reference encoding is still being recovered.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/reference_pair",
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                description,
                "experimental",
                false,
            ));
        }
        let nonzero_words = (0..payload.len().min(208).saturating_sub(3))
            .step_by(4)
            .filter_map(|offset| {
                let word = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
                (word != 0).then_some(format!("0x{offset:X}={word}"))
            })
            .collect::<Vec<_>>()
            .join(", ");
        fields.push(layout_field(
            "mapper_header_nonzero_words",
            0,
            payload.len().min(208),
            "uint32[]/skeleton-mapper-header",
            Some(LayoutValue::Text(nonzero_words)),
            "Read-only hkaSkeletonMapper header sample. Useful for comparing source/target mapper pairs and finding links to SimpleMapping rows.",
            "experimental",
            false,
        ));

        true
    } else {
        false
    }
}

pub(crate) fn decode_simple_mapping_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkaSkeletonMapperData::SimpleMapping" && record.count > 0 {
        let mapping_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(256) {
            let base = item_index * mapping_stride;
            if base >= payload.len() {
                break;
            }
            let row_end = (base + mapping_stride).min(payload.len());
            let row = &payload[base..row_end];
            let words = (0..row.len().min(64) / 4)
                .map(|word_index| le_u32(&row[word_index * 4..word_index * 4 + 4]).unwrap_or(0))
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            let finite_floats = (0..row.len().min(64).saturating_sub(3))
                .step_by(4)
                .filter_map(|offset| {
                    let value = le_f32(&row[offset..offset + 4]).unwrap_or(0.0);
                    (value.is_finite() && value.abs() >= 1e-8 && value.abs() <= 1_000_000.0)
                        .then_some(format!("0x{offset:X}={value:.6}"))
                })
                .collect::<Vec<_>>()
                .join(", ");
            fields.push(layout_field(
                &format!("simple_mapping[{item_index}]"),
                base,
                mapping_stride,
                "hkaSkeletonMapperData::SimpleMapping/read-only",
                Some(LayoutValue::Text(format!(
                    "u32_words=[{words}]; finite_float_slots=[{finite_floats}]"
                ))),
                "Read-only skeleton mapper row. These rows likely map source bones to target bones with a compact transform/weight block.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_animation_container_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if type_name == "hkaAnimationContainer" && payload.len() >= 16 {
        for offset in (0..payload.len().min(112)).step_by(8) {
            if offset + 8 > payload.len() {
                break;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                &format!("animation_container_pair_0x{offset:X}"),
                offset,
                8,
                "uint32[2]/array_or_reference_pair",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                "Read-only hkaAnimationContainer reference/count candidate. Structural edits are not supported.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_ref_variant_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if matches!(type_name, "hkRefVariant" | "hkStringPtr") && payload.len() >= 8 {
        fields.push(layout_field(
            "referenced_value",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Read-only Havok reference/string pointer payload. Relationship graph resolves matching ITEM offsets separately.",
            "experimental",
            false,
        ));
        if payload.len() >= 16 {
            let low = le_u32(&payload[8..12]).unwrap_or(0);
            let high = le_u32(&payload[12..16]).unwrap_or(0);
            fields.push(layout_field(
                "reference_metadata_pair",
                8,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                "Possible variant type/context metadata. Structural edits are not supported.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}

pub(crate) fn decode_reference_value_pairs_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) -> bool {
    let type_name = record.type_name.as_str();
    let _ = record;
    if matches!(
        type_name,
        "hkMemoryResourceContainer"
            | "hknpConstraintData"
            | "hknpRefDragProperties"
            | "hknpRefMassDistribution"
    ) && payload.len() >= 8
    {
        for offset in (0..payload.len().min(192)).step_by(8) {
            if offset + 8 > payload.len() {
                break;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                &format!("reference_or_value_pair_0x{offset:X}"),
                offset,
                8,
                "uint32[2]/reference_or_value",
                Some(LayoutValue::Text(format!(
                    "a={low}, b={high}, as_u64={}",
                    le_u64(&payload[offset..offset + 8]).unwrap_or(0)
                ))),
                &format!("Read-only {type_name} pair. These pairs are useful for identifying arrays, references, counts, flags, and tuning records; structural edits are not supported."),
                "experimental",
                false,
            ));
        }
        let finite_floats = (0..payload.len().min(192).saturating_sub(3))
            .step_by(4)
            .filter_map(|offset| {
                let value = le_f32(&payload[offset..offset + 4]).unwrap_or(0.0);
                (value.is_finite() && value.abs() >= 1e-8 && value.abs() <= 1_000_000.0)
                    .then_some(format!("0x{offset:X}={value:.6}"))
            })
            .take(16)
            .collect::<Vec<_>>()
            .join(", ");
        if !finite_floats.is_empty() {
            fields.push(layout_field(
                "finite_float_candidates",
                0,
                payload.len().min(192),
                "float32[]/candidate",
                Some(LayoutValue::Text(finite_floats)),
                "Finite float candidates inside this payload. Edits are disabled until fields are named.",
                "experimental",
                false,
            ));
        }

        true
    } else {
        false
    }
}
