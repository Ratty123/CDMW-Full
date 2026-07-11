use crate::*;

pub(crate) fn tag_item_payload<'a>(
    data: &'a [u8],
    items: &[TagItem],
    name: &str,
) -> Option<&'a [u8]> {
    let item = tag_item_by_name(items, name)?;
    let start = item.offset.saturating_add(4).min(data.len());
    let end = item
        .word_end_offset
        .or(item.marker_end_offset)
        .filter(|end| *end <= data.len())
        .unwrap_or_else(|| {
            next_tag_item(items, item)
                .and_then(|next| next.length_word_offset.or(Some(next.offset)))
                .filter(|offset| *offset <= data.len())
                .unwrap_or(data.len())
        });
    Some(&data[start..end.max(start).min(data.len())])
}

pub(crate) fn layout_field(
    name: &str,
    offset: usize,
    size: usize,
    data_type: &str,
    value: Option<LayoutValue>,
    description: &str,
    confidence: &str,
    editable: bool,
) -> LayoutField {
    LayoutField {
        name: name.to_string(),
        offset,
        size,
        data_type: data_type.to_string(),
        value,
        description: description.to_string(),
        confidence: confidence.to_string(),
        editable,
    }
}

pub(crate) fn payload_hex_prefix(payload: &[u8], limit: usize) -> String {
    let mut out = String::new();
    for (index, byte) in payload.iter().take(limit).enumerate() {
        if index > 0 {
            out.push(' ');
        }
        let _ = write!(out, "{byte:02x}");
    }
    out
}

pub(crate) fn scalar_array_type_name(type_name: &str) -> bool {
    matches!(
        type_name,
        "unsigned char" | "unsigned short" | "unsigned int" | "unsigned long long" | "long long"
    )
}

pub(crate) fn object_reference_owner_field(
    type_name: &str,
    offset: usize,
) -> Option<(&'static str, &'static str)> {
    match type_name {
        "hkArray" => (offset == 0).then_some(("data", "array_data_reference")),
        "hkRefPtr" => (offset == 0).then_some(("ptr", "object_reference")),
        "hkRefVariant" => (offset == 0).then_some(("variant", "object_reference")),
        "hkStringPtr" => (offset == 0).then_some(("string", "string_reference")),
        "hkRootLevelContainer" => {
            (offset == 0).then_some(("namedVariants", "array_data_reference"))
        }
        "hkRootLevelContainer::NamedVariant" => match offset {
            0 => Some(("name", "string_reference")),
            8 => Some(("className", "type_class_reference")),
            16 => Some(("variant", "object_reference")),
            _ => None,
        },
        "hknpPhysicsSceneData" | "hknpRagdollData" => (offset % 8 == 0 && offset < 0x80)
            .then_some(("containerArrayOrReference", "array_data_reference")),
        "hknpPhysicsSystemData" => match offset {
            0x00 => Some(("materials", "array_data_reference")),
            0x08 => Some(("motionProperties", "array_data_reference")),
            0x10 => Some(("bodyCinfos", "array_data_reference")),
            0x18 => Some(("constraintCinfos", "array_data_reference")),
            0x20 => Some(("shapeReferences", "array_data_reference")),
            _ => None,
        },
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => match offset {
            0x08 => Some(("shape", "object_reference")),
            0x10 => Some(("motionPropertiesId", "object_reference")),
            _ => None,
        },
        "hknpConstraintCinfo" => match offset {
            0x00 => Some(("bodyA", "object_reference")),
            0x08 => Some(("bodyB", "object_reference")),
            0x10 => Some(("constraintData", "object_reference")),
            _ => None,
        },
        "hknpConvexShape" => match offset {
            0x30 => Some(("vertices", "array_data_reference")),
            0x40 => Some(("planes", "array_data_reference")),
            0x48 => Some(("faces", "array_data_reference")),
            0x50 => Some(("faceIndices", "array_data_reference")),
            0x58 => Some(("edgeTableA", "array_data_reference")),
            0x60 => Some(("edgeTableB", "array_data_reference")),
            _ => None,
        },
        "hknpBoxShape" => match offset {
            0x38 => Some(("vertices", "array_data_reference")),
            0x40 => Some(("planes", "array_data_reference")),
            0x48 => Some(("faces", "array_data_reference")),
            0x50 => Some(("faceIndices", "array_data_reference")),
            0x58 => Some(("edgeTableA", "array_data_reference")),
            0x60 => Some(("edgeTableB", "array_data_reference")),
            _ => None,
        },
        "hknpCompoundShape" => match offset {
            0x20 => Some(("shapeInstances", "array_data_reference")),
            0x30 => Some(("simdTreeNodes", "array_data_reference")),
            0x40 => Some(("freeListElements", "array_data_reference")),
            0x50 => Some(("shapeProperties", "array_data_reference")),
            _ => None,
        },
        "hkSkeleton" => match offset {
            0x18 => Some(("bones", "array_data_reference")),
            0x28 => Some(("parentIndices", "array_data_reference")),
            0x38 => Some(("referencePose", "array_data_reference")),
            0x48 => Some(("floatSlots", "array_data_reference")),
            _ => None,
        },
        "hkaSkeletonMapper" => match offset {
            0x20 => Some(("sourceSkeleton", "object_reference")),
            0x28 => Some(("targetSkeleton", "object_reference")),
            0x60 => Some(("mappingData", "array_data_reference")),
            _ => None,
        },
        "hkaAnimationContainer" => (offset % 8 == 0 && offset < 0x70)
            .then_some(("animationContainerArrayOrReference", "array_data_reference")),
        "hkClass" => match offset {
            0 => Some(("name", "string_reference")),
            8 => Some(("parent", "type_class_reference")),
            24 => Some(("declaredEnums", "array_data_reference")),
            40 => Some(("declaredMembers", "array_data_reference")),
            56 => Some(("defaults", "object_reference")),
            64 => Some(("attributes", "object_reference")),
            _ => None,
        },
        "hkClassMember" => match offset {
            0 => Some(("name", "string_reference")),
            8 => Some(("class", "type_class_reference")),
            16 => Some(("enum", "type_class_reference")),
            32 => Some(("attributes", "object_reference")),
            _ => None,
        },
        "hkClassEnum" => match offset {
            0 => Some(("name", "string_reference")),
            8 => Some(("items", "array_data_reference")),
            24 => Some(("attributes", "object_reference")),
            _ => None,
        },
        _ => None,
    }
}

pub(crate) fn classify_object_reference(
    current: &ItemRecord,
    target: &ItemRecord,
    offset: usize,
) -> (String, Option<String>) {
    if let Some((field_name, category)) = object_reference_owner_field(&current.type_name, offset) {
        return (category.to_string(), Some(field_name.to_string()));
    }
    if target.type_name == "char" {
        return ("string_reference".to_string(), None);
    }
    if target.type_name.starts_with("hkArray") || scalar_array_type_name(&target.type_name) {
        return ("array_data_reference".to_string(), None);
    }
    if current.type_name.starts_with("hkArray") {
        return ("array_data_reference".to_string(), Some("data".to_string()));
    }
    if current.type_name.starts_with("hkRefPtr") || current.type_name == "hkRefVariant" {
        return ("object_reference".to_string(), None);
    }
    ("object_reference".to_string(), None)
}

pub(crate) fn possible_reference_candidates(
    payload: &[u8],
    records: &[ItemRecord],
    current: &ItemRecord,
    limit: usize,
) -> Vec<ReferenceCandidate> {
    let mut links = Vec::new();
    let mut seen = Vec::<(String, usize, usize)>::new();
    for offset in (0..payload.len().saturating_sub(3)).step_by(4) {
        let Some(value) = le_u32(&payload[offset..offset + 4]) else {
            continue;
        };
        for (kind, target) in records.iter().filter_map(|record| {
            if record.index == current.index {
                return None;
            }
            if record.data_offset == value && value > 0 {
                return Some(("data_offset", record));
            }
            if record.absolute_data_offset == Some(value as usize) && value > 0 {
                return Some(("absolute_offset", record));
            }
            None
        }) {
            let key = (kind.to_string(), offset, target.index);
            if seen.contains(&key) {
                continue;
            }
            seen.push(key);
            let (reference_category, owner_field_name) =
                classify_object_reference(current, target, offset);
            links.push(ReferenceCandidate {
                offset,
                reference_kind: kind.to_string(),
                reference_category,
                owner_field_name,
                raw_value: value,
                target_record_index: target.index,
                target_type_index: target.type_index,
                target_type_name: target.type_name.clone(),
            });
            if links.len() >= limit {
                return links;
            }
        }
    }
    links
}

pub(crate) fn increment_count(map: &mut BTreeMap<String, usize>, key: &str) {
    *map.entry(key.to_string()).or_insert(0) += 1;
}

pub(crate) fn increment_count_by(map: &mut BTreeMap<String, usize>, key: &str, count: usize) {
    if count == 0 {
        return;
    }
    *map.entry(key.to_string()).or_insert(0) += count;
}

pub(crate) fn record_containing_data_offset<'a>(
    records: &'a [ItemRecord],
    data_offset: u32,
) -> Option<&'a ItemRecord> {
    records
        .iter()
        .filter(|record| record.data_offset <= data_offset)
        .max_by_key(|record| record.data_offset)
}

pub(crate) fn fixup_reference_category(
    target_type_name: &str,
    section_name: &str,
    match_kind: &str,
) -> String {
    if match_kind == "null" {
        return "null_reference".to_string();
    }
    if match_kind == "type_index" {
        return "type_reference".to_string();
    }
    if match_kind == "string_table_index" {
        if target_type_name.starts_with("hk")
            || target_type_name.starts_with("hknp")
            || target_type_name.starts_with("hka")
            || target_type_name.starts_with("hkx")
            || target_type_name.starts_with("hkcd")
            || target_type_name.contains("::")
        {
            return "type_class_reference".to_string();
        }
        return "string_reference".to_string();
    }
    if target_type_name == "char" {
        return "string_reference".to_string();
    }
    if target_type_name.starts_with("hkArray") || scalar_array_type_name(target_type_name) {
        return "array_data_reference".to_string();
    }
    if section_name == "INDX" {
        return "object_reference".to_string();
    }
    "data_reference_candidate".to_string()
}
