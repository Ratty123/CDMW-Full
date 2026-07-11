use crate::*;

pub(crate) fn resolve_record_ref_value(raw: u64, records: &[ItemRecord]) -> Option<usize> {
    if raw == 0 {
        return None;
    }
    if let Ok(index) = usize::try_from(raw) {
        if records.iter().any(|record| record.index == index) {
            return Some(index);
        }
        if records
            .iter()
            .any(|record| record.absolute_data_offset == Some(index))
        {
            return records
                .iter()
                .find(|record| record.absolute_data_offset == Some(index))
                .map(|record| record.index);
        }
    }
    if let Ok(data_offset) = u32::try_from(raw) {
        return records
            .iter()
            .find(|record| record.data_offset == data_offset && data_offset > 0)
            .map(|record| record.index);
    }
    None
}

pub(crate) fn read_record_ref_at(
    data: &[u8],
    records: &[ItemRecord],
    absolute_offset: usize,
) -> Option<usize> {
    if absolute_offset.saturating_add(8) <= data.len() {
        if let Some(index) = le_u64(&data[absolute_offset..absolute_offset + 8])
            .and_then(|raw| resolve_record_ref_value(raw, records))
        {
            return Some(index);
        }
    }
    if absolute_offset.saturating_add(4) <= data.len() {
        if let Some(index) = le_u32(&data[absolute_offset..absolute_offset + 4])
            .and_then(|raw| resolve_record_ref_value(raw as u64, records))
        {
            return Some(index);
        }
    }
    None
}

pub(crate) fn read_u32_at(data: &[u8], absolute_offset: usize) -> Option<u32> {
    (absolute_offset.saturating_add(4) <= data.len())
        .then(|| le_u32(&data[absolute_offset..absolute_offset + 4]))
        .flatten()
}

pub(crate) fn read_u16_at(data: &[u8], absolute_offset: usize) -> Option<u16> {
    (absolute_offset.saturating_add(2) <= data.len())
        .then(|| le_u16(&data[absolute_offset..absolute_offset + 2]))
        .flatten()
}

pub(crate) fn read_u8_at(data: &[u8], absolute_offset: usize) -> Option<u8> {
    data.get(absolute_offset).copied()
}

pub(crate) fn record_span_end(
    data: &[u8],
    records: &[ItemRecord],
    record: &ItemRecord,
) -> Option<usize> {
    let start = record.absolute_data_offset?;
    records
        .iter()
        .filter_map(|candidate| candidate.absolute_data_offset)
        .filter(|offset| *offset > start)
        .min()
        .or(Some(data.len()))
}

pub(crate) fn record_item_stride(
    data: &[u8],
    records: &[ItemRecord],
    record: &ItemRecord,
) -> Option<usize> {
    if record.count == 0 {
        return None;
    }
    let start = record.absolute_data_offset?;
    let end = record_span_end(data, records, record)?;
    let byte_length = end.checked_sub(start)?;
    let stride = byte_length / record.count as usize;
    (stride > 0).then_some(stride)
}

pub(crate) fn hk_member_type_name(type_code: u8) -> &'static str {
    match type_code {
        0 => "TYPE_VOID",
        1 => "TYPE_BOOL",
        2 => "TYPE_CHAR",
        3 => "TYPE_INT8",
        4 => "TYPE_UINT8",
        5 => "TYPE_INT16",
        6 => "TYPE_UINT16",
        7 => "TYPE_INT32",
        8 => "TYPE_UINT32",
        9 => "TYPE_INT64",
        10 => "TYPE_UINT64",
        11 => "TYPE_REAL",
        12 => "TYPE_VECTOR4",
        13 => "TYPE_QUATERNION",
        14 => "TYPE_MATRIX3",
        15 => "TYPE_ROTATION",
        16 => "TYPE_QSTRANSFORM",
        17 => "TYPE_MATRIX4",
        18 => "TYPE_TRANSFORM",
        19 => "TYPE_ZERO",
        20 => "TYPE_POINTER",
        21 => "TYPE_FUNCTIONPOINTER",
        22 => "TYPE_ARRAY",
        23 => "TYPE_INPLACEARRAY",
        24 => "TYPE_ENUM",
        25 => "TYPE_STRUCT",
        26 => "TYPE_SIMPLEARRAY",
        27 => "TYPE_HOMOGENEOUSARRAY",
        28 => "TYPE_VARIANT",
        29 => "TYPE_CSTRING",
        30 => "TYPE_ULONG",
        31 => "TYPE_FLAGS",
        32 => "TYPE_HALF",
        33 => "TYPE_STRINGPTR",
        34 => "TYPE_RELARRAY",
        _ => "TYPE_UNKNOWN",
    }
}

pub(crate) fn hkclass_name_from_record(
    data: &[u8],
    records: &[ItemRecord],
    record_index: usize,
) -> Option<String> {
    let record = item_record_by_index(records, record_index)?;
    if record.type_name == "char" || record.type_name == "hkStringPtr" {
        return record_string_value(data, records, record_index);
    }
    if record.type_name != "hkClass" {
        return Some(record.type_name.clone());
    }
    let start = record.absolute_data_offset?;
    let name_record = read_record_ref_at(data, records, start)?;
    record_string_value(data, records, name_record)
}

pub(crate) fn decode_real_hkclass_enum(
    data: &[u8],
    records: &[ItemRecord],
    enum_record_index: usize,
) -> Option<RealHkClassEnumMetadata> {
    let record = item_record_by_index(records, enum_record_index)?;
    if record.type_name != "hkClassEnum" {
        return None;
    }
    let start = record.absolute_data_offset?;
    let name_record = read_record_ref_at(data, records, start);
    let name = name_record
        .and_then(|index| record_string_value(data, records, index))
        .unwrap_or_else(|| format!("hkClassEnum_record_{enum_record_index}"));
    let items_record_index = read_record_ref_at(data, records, start.saturating_add(8));
    let item_count = read_u32_at(data, start.saturating_add(16)).unwrap_or(0);
    let flags = read_u32_at(data, start.saturating_add(32));
    Some(RealHkClassEnumMetadata {
        name,
        record_index: enum_record_index,
        item_count,
        items_record_index,
        flags,
        confidence: "strong inference".to_string(),
    })
}

pub(crate) fn decode_real_hkclass_member(
    data: &[u8],
    records: &[ItemRecord],
    member_record: &ItemRecord,
    item_index: usize,
) -> Option<RealHkClassMemberMetadata> {
    let stride = record_item_stride(data, records, member_record)?;
    let start = member_record
        .absolute_data_offset?
        .saturating_add(item_index.saturating_mul(stride));
    if start.saturating_add(32) > data.len() {
        return None;
    }
    let name_record = read_record_ref_at(data, records, start);
    let name = name_record
        .and_then(|index| record_string_value(data, records, index))
        .unwrap_or_else(|| format!("member_{item_index}"));
    let class_ref_record_index = read_record_ref_at(data, records, start.saturating_add(8));
    let enum_ref_record_index = read_record_ref_at(data, records, start.saturating_add(16));
    let type_code = read_u8_at(data, start.saturating_add(24)).unwrap_or(0);
    let subtype_code = read_u8_at(data, start.saturating_add(25)).unwrap_or(0);
    let c_array_size = read_u16_at(data, start.saturating_add(26)).unwrap_or(0);
    let flags = read_u16_at(data, start.saturating_add(28)).unwrap_or(0);
    let offset = read_u16_at(data, start.saturating_add(30)).unwrap_or(0);
    let attributes_ref_record_index = read_record_ref_at(data, records, start.saturating_add(32));
    let class_ref_name =
        class_ref_record_index.and_then(|index| hkclass_name_from_record(data, records, index));
    let enum_ref_name =
        enum_ref_record_index.and_then(|index| hkclass_name_from_record(data, records, index));
    let type_name = hk_member_type_name(type_code).to_string();
    let subtype_name = hk_member_type_name(subtype_code).to_string();
    let template_ref = if matches!(type_code, 20 | 22 | 23 | 25 | 26 | 27 | 34) {
        class_ref_name.clone().or_else(|| enum_ref_name.clone())
    } else {
        None
    };
    Some(RealHkClassMemberMetadata {
        name,
        record_index: member_record.index,
        item_index,
        type_code,
        type_name,
        subtype_code,
        subtype_name,
        c_array_size,
        flags,
        offset,
        class_ref_record_index,
        class_ref_name,
        enum_ref_record_index,
        enum_ref_name,
        attributes_ref_record_index,
        template_ref,
        confidence: "strong inference".to_string(),
    })
}

pub(crate) fn decode_real_hkclass_metadata(
    data: &[u8],
    records: &[ItemRecord],
) -> RealHkClassMetadataReport {
    let mut classes = Vec::<RealHkClassMetadata>::new();
    for class_record in records
        .iter()
        .filter(|record| record.type_name == "hkClass")
    {
        let Some(start) = class_record.absolute_data_offset else {
            continue;
        };
        if start.saturating_add(80) > data.len() {
            continue;
        }
        let name_record = read_record_ref_at(data, records, start);
        let name = name_record
            .and_then(|index| record_string_value(data, records, index))
            .unwrap_or_else(|| format!("hkClass_record_{}", class_record.index));
        let parent_record_index = read_record_ref_at(data, records, start.saturating_add(8));
        let parent_name =
            parent_record_index.and_then(|index| hkclass_name_from_record(data, records, index));
        let object_size = read_u32_at(data, start.saturating_add(16));
        let enums_record_index = read_record_ref_at(data, records, start.saturating_add(24));
        let declared_enum_count = read_u32_at(data, start.saturating_add(32)).unwrap_or(0);
        let members_record_index = read_record_ref_at(data, records, start.saturating_add(40));
        let declared_member_count = read_u32_at(data, start.saturating_add(48)).unwrap_or(0);
        let defaults_record_index = read_record_ref_at(data, records, start.saturating_add(56));
        let attributes_record_index = read_record_ref_at(data, records, start.saturating_add(64));
        let flags = read_u32_at(data, start.saturating_add(72));
        let version = read_u32_at(data, start.saturating_add(76));
        let signature = read_u32_at(data, start.saturating_add(80)).filter(|value| *value != 0);
        let mut members = Vec::new();
        if let Some(member_record) =
            members_record_index.and_then(|index| item_record_by_index(records, index))
        {
            let count = if declared_member_count > 0 {
                declared_member_count.min(member_record.count)
            } else {
                member_record.count
            };
            for item_index in 0..count as usize {
                if let Some(member) =
                    decode_real_hkclass_member(data, records, member_record, item_index)
                {
                    members.push(member);
                }
            }
        }
        let mut enums = Vec::new();
        if let Some(index) = enums_record_index {
            if let Some(decoded) = decode_real_hkclass_enum(data, records, index) {
                enums.push(decoded);
            }
        }
        let mut recovered_requirements = BTreeMap::<String, bool>::new();
        recovered_requirements.insert("member_type_codes".to_string(), !members.is_empty());
        recovered_requirements.insert("member_flags".to_string(), !members.is_empty());
        recovered_requirements.insert(
            "base_classes".to_string(),
            parent_record_index.is_some() || start.saturating_add(16) <= data.len(),
        );
        recovered_requirements.insert(
            "enum_refs".to_string(),
            declared_enum_count > 0
                || members
                    .iter()
                    .any(|member| member.enum_ref_record_index.is_some()),
        );
        recovered_requirements.insert("signatures".to_string(), signature.is_some());
        recovered_requirements.insert("versions".to_string(), version.is_some());
        recovered_requirements.insert(
            "default_values".to_string(),
            start.saturating_add(64) <= data.len(),
        );
        recovered_requirements.insert(
            "template_refs".to_string(),
            members.iter().any(|member| member.template_ref.is_some()),
        );
        let unresolved_requirements = recovered_requirements
            .iter()
            .filter_map(|(key, recovered)| (!*recovered).then_some(key.clone()))
            .collect::<Vec<_>>();
        classes.push(RealHkClassMetadata {
            name,
            record_index: class_record.index,
            parent_record_index,
            parent_name,
            object_size,
            version,
            flags,
            signature,
            defaults_record_index,
            attributes_record_index,
            declared_enum_count,
            declared_member_count,
            members_record_index,
            enums_record_index,
            members,
            enums,
            recovered_requirements,
            unresolved_requirements,
            confidence: "strong inference".to_string(),
        });
    }
    let mut recovered_requirements = BTreeMap::<String, bool>::new();
    for key in [
        "member_type_codes",
        "member_flags",
        "base_classes",
        "enum_refs",
        "signatures",
        "versions",
        "default_values",
        "template_refs",
    ] {
        recovered_requirements.insert(
            key.to_string(),
            !classes.is_empty()
                && classes.iter().any(|class| {
                    class
                        .recovered_requirements
                        .get(key)
                        .copied()
                        .unwrap_or(false)
                }),
        );
    }
    let unresolved_requirements = recovered_requirements
        .iter()
        .filter_map(|(key, recovered)| (!*recovered).then_some(key.clone()))
        .collect::<Vec<_>>();
    let member_count = classes
        .iter()
        .map(|class| class.members.len())
        .sum::<usize>();
    let enum_count = classes.iter().map(|class| class.enums.len()).sum::<usize>();
    RealHkClassMetadataReport {
        format: "cd_hkx_real_hkclass_metadata_v1".to_string(),
        status: if classes.is_empty() {
            "not_found".to_string()
        } else {
            "real_hkclass_records_decoded".to_string()
        },
        imported: false,
        class_count: classes.len(),
        member_count,
        enum_count,
        recovered_requirements,
        unresolved_requirements,
        classes,
    }
}
