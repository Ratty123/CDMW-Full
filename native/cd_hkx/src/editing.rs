use crate::*;

pub fn patch_fixed_float(
    data: &[u8],
    record_index: usize,
    item_index: usize,
    item_relative_offset: usize,
    value: f32,
) -> Result<Vec<u8>, String> {
    if !value.is_finite() {
        return Err("patched float value must be finite".to_string());
    }
    if value.abs() > 1_000_000.0 {
        return Err("patched float value is outside the conservative safe range".to_string());
    }
    let summary = parse_summary(data);
    let group = summary
        .physics_tuning_groups
        .iter()
        .find(|group| group.record_index == record_index)
        .ok_or_else(|| {
            format!("record {record_index} is not a supported fixed-float physics tuning record")
        })?;
    let slot = group
        .slots
        .iter()
        .find(|slot| slot.item_index == item_index && slot.offset == item_relative_offset)
        .ok_or_else(|| {
            format!(
                "record {record_index}, item {item_index}, offset 0x{item_relative_offset:X} is not a supported fixed-float slot"
            )
        })?;
    let record = summary
        .item_records
        .iter()
        .find(|record| record.index == record_index)
        .ok_or_else(|| format!("record {record_index} was not found"))?;
    let spans = item_record_spans(data, &summary.tag_items, &summary.item_records);
    let (_index, start, end) = spans
        .iter()
        .find(|(index, _, _)| *index == record_index)
        .copied()
        .ok_or_else(|| format!("record {record_index} payload span was not found"))?;
    if record.count == 0 {
        return Err(format!("record {record_index} has no items"));
    }
    if item_index >= record.count as usize {
        return Err(format!(
            "item index {item_index} is outside record {record_index} count {}",
            record.count
        ));
    }
    let stride = (end - start) / record.count as usize;
    if stride != group.stride {
        return Err(format!(
            "record {record_index} stride changed from decoded {} to {stride}",
            group.stride
        ));
    }
    if item_relative_offset + 4 > stride {
        return Err(format!(
            "offset 0x{item_relative_offset:X} is outside record {record_index} item stride"
        ));
    }
    let absolute = start + item_index * stride + item_relative_offset;
    if absolute + 4 > data.len() {
        return Err(format!(
            "record {record_index} item {item_index} offset 0x{item_relative_offset:X} points outside the HKX payload"
        ));
    }
    let _previous_value = slot.value;
    let mut patched = data.to_vec();
    patched[absolute..absolute + 4].copy_from_slice(&value.to_le_bytes());
    Ok(patched)
}
