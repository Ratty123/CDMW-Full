use crate::*;

pub(crate) fn be_u32(bytes: &[u8]) -> Option<u32> {
    if bytes.len() < 4 {
        return None;
    }
    Some(u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

pub(crate) fn le_u32(bytes: &[u8]) -> Option<u32> {
    if bytes.len() < 4 {
        return None;
    }
    Some(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

pub(crate) fn le_u16(bytes: &[u8]) -> Option<u16> {
    if bytes.len() < 2 {
        return None;
    }
    Some(u16::from_le_bytes([bytes[0], bytes[1]]))
}

pub(crate) fn le_u64(bytes: &[u8]) -> Option<u64> {
    if bytes.len() < 8 {
        return None;
    }
    Some(u64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}

pub(crate) fn le_f32(bytes: &[u8]) -> Option<f32> {
    le_u32(bytes).map(f32::from_bits)
}

pub(crate) fn find_bytes(haystack: &[u8], needle: &[u8], start: usize) -> Option<usize> {
    if needle.is_empty() || start >= haystack.len() || needle.len() > haystack.len() {
        return None;
    }
    haystack[start..]
        .windows(needle.len())
        .position(|window| window == needle)
        .map(|position| start + position)
}

pub(crate) fn decode_length_word(raw: u32) -> (u32, u32) {
    (raw & 0x0fff_ffff, raw & 0xf000_0000)
}

pub fn find_tag_items(data: &[u8]) -> Vec<TagItem> {
    let mut items = Vec::new();
    if let Some(offset) = find_bytes(&data[..data.len().min(64)], b"TAG0", 0) {
        items.push(TagItem {
            name: "TAG0".to_string(),
            offset,
            length_word_offset: None,
            raw_length_word: None,
            declared_length: None,
            length_flags: None,
            marker_end_offset: None,
            word_end_offset: None,
        });
    }
    let mut seen = Vec::<(String, usize)>::new();
    for marker in TAG_ITEM_MARKERS {
        let marker_bytes = marker.as_bytes();
        let mut start = 0usize;
        while let Some(offset) = find_bytes(data, marker_bytes, start) {
            start = offset.saturating_add(1);
            if offset < 4 {
                continue;
            }
            let raw = match be_u32(&data[offset - 4..offset]) {
                Some(value) => value,
                None => continue,
            };
            let (declared_length, length_flags) = decode_length_word(raw);
            if declared_length == 0 {
                continue;
            }
            let marker_end = offset.saturating_add(declared_length as usize);
            let word_end = offset
                .saturating_sub(4)
                .saturating_add(declared_length as usize);
            if marker_end > data.len().saturating_add(4) && word_end > data.len() {
                continue;
            }
            if seen
                .iter()
                .any(|(name, seen_offset)| name == marker && *seen_offset == offset)
            {
                continue;
            }
            seen.push((marker.to_string(), offset));
            items.push(TagItem {
                name: marker.to_string(),
                offset,
                length_word_offset: Some(offset - 4),
                raw_length_word: Some(raw),
                declared_length: Some(declared_length),
                length_flags: Some(length_flags),
                marker_end_offset: Some(marker_end),
                word_end_offset: Some(word_end),
            });
        }
    }
    items.sort_by_key(|item| item.offset);
    items
}

pub(crate) fn tag_item_by_name<'a>(items: &'a [TagItem], name: &str) -> Option<&'a TagItem> {
    items.iter().find(|item| item.name == name)
}

pub(crate) fn next_tag_item<'a>(items: &'a [TagItem], item: &TagItem) -> Option<&'a TagItem> {
    items
        .iter()
        .filter(|candidate| candidate.offset > item.offset)
        .min_by_key(|candidate| candidate.offset)
}

pub fn extract_tst1_type_names(data: &[u8], items: &[TagItem]) -> Vec<String> {
    let Some(tst1) = tag_item_by_name(items, "TST1") else {
        return Vec::new();
    };
    let next = next_tag_item(items, tst1);
    let mut candidates = Vec::new();
    if let Some(end) = tst1.marker_end_offset {
        candidates.push(end);
    }
    if let Some(next_item) = next {
        if let Some(offset) = next_item.length_word_offset {
            candidates.push(offset);
        } else {
            candidates.push(next_item.offset);
        }
    }
    let end = candidates
        .into_iter()
        .filter(|candidate| *candidate > tst1.offset)
        .min()
        .unwrap_or(data.len())
        .min(data.len());
    let start = (tst1.offset + 4).min(end);
    data[start..end]
        .split(|byte| *byte == 0)
        .filter_map(|raw| {
            if raw.is_empty() || raw == [0xff] {
                return None;
            }
            let name = String::from_utf8_lossy(raw).trim().to_string();
            if name.is_empty() || name == "\u{fffd}" {
                None
            } else {
                Some(name)
            }
        })
        .collect()
}

pub(crate) fn read_var_uint(payload: &[u8], mut offset: usize) -> Result<(u64, usize), String> {
    if offset >= payload.len() {
        return Err("Unexpected end of Havok packed integer stream.".to_string());
    }
    let byte_1 = payload[offset];
    offset += 1;
    if byte_1 & 0b1000_0000 == 0 {
        return Ok(((byte_1 & 0b0111_1111) as u64, offset));
    }
    if byte_1 == 0b1100_0011 {
        if offset + 2 > payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        return Ok((
            ((payload[offset] as u64) << 8) | payload[offset + 1] as u64,
            offset + 2,
        ));
    }
    let marker = byte_1 >> 3;
    if (0b0001_0000..0b0001_1000).contains(&marker) {
        if offset >= payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        return Ok((
            0b0011_1111_1111_1111 & (((byte_1 as u64) << 8) | payload[offset] as u64),
            offset + 1,
        ));
    }
    if (0b0001_1000..0b0001_1100).contains(&marker) {
        if offset + 2 > payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        return Ok((
            0b0001_1111_1111_1111_1111_1111
                & (((byte_1 as u64) << 16)
                    | ((payload[offset] as u64) << 8)
                    | payload[offset + 1] as u64),
            offset + 2,
        ));
    }
    if marker == 0b0001_1100 {
        if offset + 3 > payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        let value = u32::from_le_bytes([
            byte_1,
            payload[offset],
            payload[offset + 1],
            payload[offset + 2],
        ]) & 0x07ff_ffff;
        return Ok((value as u64, offset + 3));
    }
    if marker == 0b0001_1101 {
        if offset + 4 > payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        let value = 0b0000_0111_1111_1111_1111_1111_1111_1111_1111u64
            & (((byte_1 as u64) << 32)
                | ((payload[offset] as u64) << 24)
                | ((payload[offset + 1] as u64) << 16)
                | ((payload[offset + 2] as u64) << 8)
                | payload[offset + 3] as u64);
        return Ok((value, offset + 4));
    }
    if marker == 0b0001_1110 {
        if offset + 7 > payload.len() {
            return Err("Truncated Havok packed integer.".to_string());
        }
        let mut bytes = [0u8; 8];
        bytes[0] = byte_1;
        bytes[1..8].copy_from_slice(&payload[offset..offset + 7]);
        return Ok((
            u64::from_le_bytes(bytes) & 0x07ff_ffff_ffff_ffff,
            offset + 7,
        ));
    }
    Err(format!(
        "Unrecognized Havok packed integer marker byte 0x{byte_1:02X}."
    ))
}

pub fn parse_tna1_type_infos(
    data: &[u8],
    items: &[TagItem],
    string_table_names: &[String],
) -> (Option<u32>, Vec<TypeInfo>, Vec<String>) {
    let Some(tna1) = tag_item_by_name(items, "TNA1") else {
        return (None, Vec::new(), Vec::new());
    };
    if tna1.offset + 4 >= data.len() {
        return (None, Vec::new(), Vec::new());
    }
    let payload_end = if let Some(end) = tna1.word_end_offset.filter(|end| *end <= data.len()) {
        end
    } else if let Some(end) = tna1.marker_end_offset.filter(|end| *end <= data.len()) {
        end
    } else if let Some(next) = next_tag_item(items, tna1) {
        next.length_word_offset.unwrap_or(data.len())
    } else {
        data.len()
    }
    .min(data.len());
    let start = (tna1.offset + 4).min(payload_end);
    let payload = &data[start..payload_end];
    if payload.is_empty() {
        return (None, Vec::new(), Vec::new());
    }
    let mut warnings = Vec::new();
    let (declared_count, mut cursor) = match read_var_uint(payload, 0) {
        Ok(value) => value,
        Err(error) => {
            return (
                None,
                Vec::new(),
                vec![format!("Could not decode TNA1 type count: {error}")],
            )
        }
    };
    let mut type_infos = Vec::new();
    for index in 1..declared_count {
        let parsed = (|| -> Result<TypeInfo, String> {
            let (name_index, next_cursor) = read_var_uint(payload, cursor)?;
            cursor = next_cursor;
            let (template_count, next_cursor) = read_var_uint(payload, cursor)?;
            cursor = next_cursor;
            let name = string_table_names
                .get(name_index as usize)
                .cloned()
                .unwrap_or_else(|| format!("type-string[{name_index}]"));
            let mut template_parameters = Vec::new();
            for _ in 0..template_count {
                let (template_name_index, next_cursor) = read_var_uint(payload, cursor)?;
                cursor = next_cursor;
                let (template_value, next_cursor) = read_var_uint(payload, cursor)?;
                cursor = next_cursor;
                let template_name = string_table_names
                    .get(template_name_index as usize)
                    .cloned()
                    .unwrap_or_else(|| format!("template-string[{template_name_index}]"));
                template_parameters.push((template_name, template_value as u32));
            }
            Ok(TypeInfo {
                index: index as u32,
                name,
                template_parameters,
            })
        })();
        match parsed {
            Ok(info) => type_infos.push(info),
            Err(error) => {
                warnings.push(format!("Could not fully decode TNA1 type {index}: {error}"));
                break;
            }
        }
    }
    if cursor < payload.len() && payload[cursor..].iter().any(|value| *value != 0) {
        warnings.push(format!(
            "TNA1 has {} undecoded non-zero trailing byte(s).",
            payload.len() - cursor
        ));
    }
    (Some(declared_count as u32), type_infos, warnings)
}

pub(crate) fn data_payload_offset(items: &[TagItem]) -> Option<usize> {
    tag_item_by_name(items, "DATA").map(|item| item.offset + 4)
}

pub(crate) fn data_payload_end(data: &[u8], items: &[TagItem]) -> Option<usize> {
    let item = tag_item_by_name(items, "DATA")?;
    item.word_end_offset
        .or(item.marker_end_offset)
        .filter(|end| *end <= data.len())
        .or(Some(data.len()))
}

pub fn parse_item_records(
    data: &[u8],
    items: &[TagItem],
    type_infos: &[TypeInfo],
    type_names: &[String],
) -> Vec<ItemRecord> {
    let Some(item) = tag_item_by_name(items, "ITEM") else {
        return Vec::new();
    };
    let data_payload_offset = data_payload_offset(items);
    let record_start = item.offset + 16;
    let record_end = if let Some(end) = item.word_end_offset.filter(|end| *end <= data.len()) {
        end
    } else if let Some(end) = item.marker_end_offset.filter(|end| *end <= data.len()) {
        end
    } else {
        data.len()
    };
    if record_start >= record_end {
        return Vec::new();
    }
    let mut records = Vec::new();
    for (index, chunk) in data[record_start..record_end].chunks_exact(12).enumerate() {
        let Some(raw_type_flags) = le_u32(&chunk[0..4]) else {
            continue;
        };
        let Some(data_offset) = le_u32(&chunk[4..8]) else {
            continue;
        };
        let Some(count) = le_u32(&chunk[8..12]) else {
            continue;
        };
        let type_index = raw_type_flags & 0x0fff_ffff;
        let flags = raw_type_flags & 0xf000_0000;
        let type_name = type_infos
            .iter()
            .find(|info| info.index == type_index)
            .map(TypeInfo::display_name)
            .or_else(|| type_names.get(type_index as usize).cloned())
            .unwrap_or_default();
        records.push(ItemRecord {
            index,
            raw_type_flags,
            type_index,
            flags,
            data_offset,
            absolute_data_offset: data_payload_offset.map(|base| base + data_offset as usize),
            count,
            type_name,
        });
    }
    records
}

pub fn item_record_spans(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
) -> Vec<(usize, usize, usize)> {
    let Some(data_end) = data_payload_end(data, items) else {
        return Vec::new();
    };
    let absolute_offsets = records
        .iter()
        .filter_map(|record| record.absolute_data_offset)
        .filter(|offset| *offset < data_end)
        .collect::<Vec<_>>();
    let mut spans = Vec::new();
    for record in records {
        let Some(start) = record.absolute_data_offset else {
            continue;
        };
        if start >= data_end {
            continue;
        }
        let end = absolute_offsets
            .iter()
            .copied()
            .filter(|offset| *offset > start)
            .min()
            .unwrap_or(data_end);
        if end > start {
            spans.push((record.index, start, end));
        }
    }
    spans
}
