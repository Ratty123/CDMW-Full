use crate::*;

pub(crate) fn metadata_fixup_word(
    index: usize,
    offset: usize,
    value: u32,
    match_kind: &str,
    reference_category: &str,
    target_type_name: Option<&str>,
    confidence: &str,
) -> TagfileFixupWord {
    TagfileFixupWord {
        index,
        offset,
        value,
        match_kind: match_kind.to_string(),
        reference_category: reference_category.to_string(),
        target_record_index: None,
        target_type_index: None,
        target_type_name: target_type_name.map(str::to_string),
        target_data_offset: None,
        target_absolute_offset: None,
        target_string_index: None,
        target_string: None,
        owner_record_index: None,
        owner_type_index: None,
        owner_type_name: None,
        owner_local_offset: None,
        patch_value: None,
        confidence: confidence.to_string(),
    }
}

pub(crate) fn match_fixup_word(
    index: usize,
    offset: usize,
    value: u32,
    section_name: &str,
    records: &[ItemRecord],
    type_infos: &[TypeInfo],
    type_names: &[String],
    string_table_names: &[String],
) -> TagfileFixupWord {
    if value == 0 {
        return metadata_fixup_word(
            index,
            offset,
            value,
            "null",
            "null_reference",
            None,
            "strong inference",
        );
    }
    if let Some(record) = records
        .iter()
        .find(|record| record.data_offset == value && value > 0)
    {
        return TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "data_offset".to_string(),
            reference_category: fixup_reference_category(
                &record.type_name,
                section_name,
                "data_offset",
            ),
            target_record_index: Some(record.index),
            target_type_index: Some(record.type_index),
            target_type_name: Some(record.type_name.clone()),
            target_data_offset: Some(record.data_offset),
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "experimental".to_string(),
        };
    }
    if let Some(record) = records
        .iter()
        .find(|record| record.absolute_data_offset == Some(value as usize) && value > 0)
    {
        return TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "absolute_offset".to_string(),
            reference_category: fixup_reference_category(
                &record.type_name,
                section_name,
                "absolute_offset",
            ),
            target_record_index: Some(record.index),
            target_type_index: Some(record.type_index),
            target_type_name: Some(record.type_name.clone()),
            target_data_offset: None,
            target_absolute_offset: record.absolute_data_offset,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "experimental".to_string(),
        };
    }
    let type_name = type_infos
        .iter()
        .find(|info| info.index == value)
        .map(TypeInfo::display_name)
        .or_else(|| type_names.get(value as usize).cloned());
    if let Some(type_name) = type_name {
        return TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "type_index".to_string(),
            reference_category: fixup_reference_category(&type_name, section_name, "type_index"),
            target_record_index: None,
            target_type_index: Some(value),
            target_type_name: Some(type_name),
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "experimental".to_string(),
        };
    }
    if let Some(string_value) = string_table_names.get(value as usize) {
        return TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "string_table_index".to_string(),
            reference_category: fixup_reference_category(
                string_value,
                section_name,
                "string_table_index",
            ),
            target_record_index: None,
            target_type_index: None,
            target_type_name: None,
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: Some(value as usize),
            target_string: Some(string_value.clone()),
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "experimental".to_string(),
        };
    }
    metadata_fixup_word(
        index,
        offset,
        value,
        "unresolved_word",
        "unresolved_fixup_word",
        None,
        "raw",
    )
}

pub(crate) fn nested_item_word_match(
    index: usize,
    offset: usize,
    value: u32,
    section_item: &TagItem,
    item: &TagItem,
    records: &[ItemRecord],
) -> Option<TagfileFixupWord> {
    let word_absolute_offset = section_item.offset.saturating_add(4).saturating_add(offset);
    if item
        .length_word_offset
        .is_some_and(|length_offset| length_offset == word_absolute_offset)
    {
        return Some(metadata_fixup_word(
            index,
            offset,
            value,
            "item_length_word",
            "item_table_metadata",
            None,
            "confirmed",
        ));
    }
    if word_absolute_offset == item.offset {
        return Some(metadata_fixup_word(
            index,
            offset,
            value,
            "item_marker",
            "item_table_metadata",
            Some("ITEM"),
            "confirmed",
        ));
    }
    if word_absolute_offset > item.offset && word_absolute_offset < item.offset.saturating_add(16) {
        return Some(metadata_fixup_word(
            index,
            offset,
            value,
            "item_header_word",
            "item_table_metadata",
            None,
            "confirmed",
        ));
    }
    let record_start = item.offset.saturating_add(16);
    let item_end = item
        .word_end_offset
        .or(item.marker_end_offset)
        .unwrap_or(record_start);
    if word_absolute_offset < record_start || word_absolute_offset.saturating_add(4) > item_end {
        return None;
    }
    let relative = word_absolute_offset - record_start;
    let record_index = relative / 12;
    let record = records.get(record_index)?;
    match relative % 12 {
        0 => Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_type_flags".to_string(),
            reference_category: "type_reference".to_string(),
            target_record_index: Some(record.index),
            target_type_index: Some(record.type_index),
            target_type_name: Some(record.type_name.clone()),
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: if value == record.raw_type_flags {
                "confirmed".to_string()
            } else {
                "experimental".to_string()
            },
        }),
        4 => Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_data_offset".to_string(),
            reference_category: "item_data_offset".to_string(),
            target_record_index: Some(record.index),
            target_type_index: Some(record.type_index),
            target_type_name: Some(record.type_name.clone()),
            target_data_offset: Some(record.data_offset),
            target_absolute_offset: record.absolute_data_offset,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: if value == record.data_offset {
                "confirmed".to_string()
            } else {
                "experimental".to_string()
            },
        }),
        8 => Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_count".to_string(),
            reference_category: "item_count".to_string(),
            target_record_index: Some(record.index),
            target_type_index: Some(record.type_index),
            target_type_name: Some(record.type_name.clone()),
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: if value == record.count {
                "confirmed".to_string()
            } else {
                "experimental".to_string()
            },
        }),
        _ => None,
    }
}

pub(crate) fn decode_ptch_patch_site(
    data: &[u8],
    patch_site_index: usize,
    ptch_word_index: usize,
    section_item: &TagItem,
    ptch_item: &TagItem,
    patch_site_offset: u32,
    records: &[ItemRecord],
) -> TagfilePtchPatchSite {
    let word_absolute_offset = ptch_item
        .offset
        .saturating_add(4)
        .saturating_add(ptch_word_index.saturating_mul(4));
    let section_payload_start = section_item.offset.saturating_add(4);
    let section_word_offset = word_absolute_offset.checked_sub(section_payload_start);
    let section_word_index = section_word_offset.map(|offset| offset / 4);
    let owner = record_containing_data_offset(records, patch_site_offset);
    let owner_local_offset = owner.map(|record| (patch_site_offset - record.data_offset) as usize);
    let patch_value = owner.and_then(|record| {
        let absolute = record.absolute_data_offset? + owner_local_offset.unwrap_or(0);
        (absolute + 8 <= data.len()).then(|| le_u64(&data[absolute..absolute + 8]).unwrap_or(0))
    });
    let target = patch_value
        .and_then(|raw| usize::try_from(raw).ok())
        .and_then(|record_index| records.get(record_index));
    let (target_status, reference_category, confidence) = if patch_value == Some(0) {
        (
            "null".to_string(),
            "null_reference".to_string(),
            "strong inference".to_string(),
        )
    } else if let Some(target) = target {
        (
            "object".to_string(),
            fixup_reference_category(&target.type_name, "INDX", "data_offset"),
            "strong inference".to_string(),
        )
    } else {
        (
            "unresolved".to_string(),
            "patch_offset_candidate".to_string(),
            "experimental".to_string(),
        )
    };
    TagfilePtchPatchSite {
        index: patch_site_index,
        ptch_word_index,
        section_word_index,
        section_word_offset,
        patch_site_offset,
        owner_record_index: owner.map(|record| record.index),
        owner_type_index: owner.map(|record| record.type_index),
        owner_type_name: owner.map(|record| record.type_name.clone()),
        owner_local_offset,
        patch_value,
        target_status,
        reference_category,
        target_record_index: target.map(|record| record.index),
        target_type_index: target.map(|record| record.type_index),
        target_type_name: target.map(|record| record.type_name.clone()),
        target_data_offset: target.map(|record| record.data_offset),
        target_absolute_offset: target.and_then(|record| record.absolute_data_offset),
        confidence,
    }
}

pub(crate) fn decode_nested_ptch_table(
    data: &[u8],
    section_item: &TagItem,
    ptch_item: &TagItem,
    records: &[ItemRecord],
) -> Option<TagfilePtchTable> {
    let ptch_end = ptch_item
        .word_end_offset
        .or(ptch_item.marker_end_offset)
        .unwrap_or(ptch_item.offset.saturating_add(4));
    let payload_offset = ptch_item.offset.saturating_add(4);
    if payload_offset.saturating_add(20) > data.len() || payload_offset > ptch_end {
        return None;
    }
    let payload_byte_length = ptch_end.saturating_sub(payload_offset);
    let word_count = payload_byte_length / 4;
    if word_count < 5 {
        return None;
    }
    let header = [
        le_u32(&data[payload_offset..payload_offset + 4]).unwrap_or(0),
        le_u32(&data[payload_offset + 4..payload_offset + 8]).unwrap_or(0),
        le_u32(&data[payload_offset + 8..payload_offset + 12]).unwrap_or(0),
        le_u32(&data[payload_offset + 12..payload_offset + 16]).unwrap_or(0),
    ];
    let patch_site_count =
        le_u32(&data[payload_offset + 16..payload_offset + 20]).unwrap_or(0) as usize;
    if header != [1, 1, 0, 2] || patch_site_count > word_count.saturating_sub(5) {
        return None;
    }
    let mut patch_sites = Vec::new();
    for patch_site_index in 0..patch_site_count {
        let ptch_word_index = 5 + patch_site_index;
        let value_offset = payload_offset.saturating_add(ptch_word_index.saturating_mul(4));
        if value_offset.saturating_add(4) > data.len() {
            break;
        }
        let patch_site_offset = le_u32(&data[value_offset..value_offset + 4]).unwrap_or(0);
        patch_sites.push(decode_ptch_patch_site(
            data,
            patch_site_index,
            ptch_word_index,
            section_item,
            ptch_item,
            patch_site_offset,
            records,
        ));
    }
    let resolved_patch_site_count = patch_sites
        .iter()
        .filter(|site| site.target_status == "object")
        .count();
    let null_patch_site_count = patch_sites
        .iter()
        .filter(|site| site.target_status == "null")
        .count();
    let unresolved_patch_site_count = patch_sites
        .iter()
        .filter(|site| site.target_status == "unresolved")
        .count();
    Some(TagfilePtchTable {
        offset: ptch_item.offset,
        payload_offset,
        payload_byte_length,
        word_count,
        header,
        patch_site_count,
        resolved_patch_site_count,
        null_patch_site_count,
        unresolved_patch_site_count,
        confidence: if unresolved_patch_site_count == 0 {
            "strong inference".to_string()
        } else {
            "experimental".to_string()
        },
        patch_sites,
    })
}

pub(crate) fn nested_ptch_word_match(
    data: &[u8],
    index: usize,
    offset: usize,
    value: u32,
    section_item: &TagItem,
    ptch_item: &TagItem,
    records: &[ItemRecord],
    type_infos: &[TypeInfo],
    type_names: &[String],
    string_table_names: &[String],
) -> Option<TagfileFixupWord> {
    let word_absolute_offset = section_item.offset.saturating_add(4).saturating_add(offset);
    if ptch_item
        .length_word_offset
        .is_some_and(|length_offset| length_offset == word_absolute_offset)
    {
        return Some(metadata_fixup_word(
            index,
            offset,
            value,
            "ptch_length_word",
            "ptch_table_metadata",
            None,
            "confirmed",
        ));
    }
    if word_absolute_offset == ptch_item.offset {
        return Some(metadata_fixup_word(
            index,
            offset,
            value,
            "ptch_marker",
            "ptch_table_metadata",
            Some("PTCH"),
            "confirmed",
        ));
    }
    if word_absolute_offset < ptch_item.offset.saturating_add(4) {
        return None;
    }
    let ptch_end = ptch_item
        .word_end_offset
        .or(ptch_item.marker_end_offset)
        .unwrap_or(ptch_item.offset.saturating_add(4));
    if word_absolute_offset.saturating_add(4) > ptch_end {
        return None;
    }
    let ptch_payload_start = ptch_item.offset.saturating_add(4);
    let ptch_word_offset = word_absolute_offset.checked_sub(ptch_payload_start)?;
    if ptch_word_offset % 4 != 0 {
        return None;
    }
    let ptch_word_index = ptch_word_offset / 4;
    let ptch_word_count = ptch_end.saturating_sub(ptch_payload_start) / 4;
    if ptch_word_count >= 5 && ptch_payload_start + 20 <= data.len() {
        let header0 = le_u32(&data[ptch_payload_start..ptch_payload_start + 4]).unwrap_or(0);
        let header1 = le_u32(&data[ptch_payload_start + 4..ptch_payload_start + 8]).unwrap_or(0);
        let header2 = le_u32(&data[ptch_payload_start + 8..ptch_payload_start + 12]).unwrap_or(0);
        let header3 = le_u32(&data[ptch_payload_start + 12..ptch_payload_start + 16]).unwrap_or(0);
        let patch_site_count =
            le_u32(&data[ptch_payload_start + 16..ptch_payload_start + 20]).unwrap_or(0) as usize;
        if (header0, header1, header2, header3) == (1, 1, 0, 2)
            && patch_site_count <= ptch_word_count.saturating_sub(5)
        {
            if ptch_word_index < 4 {
                return Some(metadata_fixup_word(
                    index,
                    offset,
                    value,
                    "ptch_header_word",
                    "ptch_table_metadata",
                    None,
                    "confirmed",
                ));
            }
            if ptch_word_index == 4 {
                return Some(metadata_fixup_word(
                    index,
                    offset,
                    value,
                    "ptch_patch_site_count",
                    "ptch_table_metadata",
                    None,
                    "confirmed",
                ));
            }
            if ptch_word_index < 5 + patch_site_count {
                let site = decode_ptch_patch_site(
                    data,
                    ptch_word_index - 5,
                    ptch_word_index,
                    section_item,
                    ptch_item,
                    value,
                    records,
                );
                return Some(TagfileFixupWord {
                    index,
                    offset,
                    value,
                    match_kind: if site.target_status == "object" {
                        "ptch_object_patch_offset".to_string()
                    } else if site.target_status == "null" {
                        "ptch_null_patch_offset".to_string()
                    } else {
                        "ptch_patch_site_offset".to_string()
                    },
                    reference_category: site.reference_category,
                    target_record_index: site.target_record_index,
                    target_type_index: site.target_type_index,
                    target_type_name: site.target_type_name,
                    target_data_offset: site.target_data_offset,
                    target_absolute_offset: site.target_absolute_offset,
                    target_string_index: None,
                    target_string: None,
                    owner_record_index: site.owner_record_index,
                    owner_type_index: site.owner_type_index,
                    owner_type_name: site.owner_type_name,
                    owner_local_offset: site.owner_local_offset,
                    patch_value: site.patch_value,
                    confidence: site.confidence,
                });
            }
        }
    }
    let mut matched = match_fixup_word(
        index,
        offset,
        value,
        "PTCH",
        records,
        type_infos,
        type_names,
        string_table_names,
    );
    matched.match_kind = match matched.match_kind.as_str() {
        "null" => "ptch_null".to_string(),
        "data_offset" => "ptch_data_offset".to_string(),
        "absolute_offset" => "ptch_absolute_offset".to_string(),
        "type_index" => "ptch_type_index".to_string(),
        "string_table_index" => "ptch_string_table_index".to_string(),
        "unresolved_word" => "ptch_payload_word".to_string(),
        other => format!("ptch_{other}"),
    };
    if matched.reference_category == "unresolved_fixup_word" {
        matched.reference_category = "patch_offset_candidate".to_string();
        matched.confidence = "experimental".to_string();
    }
    Some(matched)
}
