use crate::*;

pub(crate) fn add_hknp_fallback_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if fields.is_empty() && type_name.starts_with("hknp") {
        for offset in (0..payload.len().min(256).saturating_sub(3)).step_by(4) {
            let Some(value) = le_f32(&payload[offset..offset + 4]) else {
                continue;
            };
            if value.is_finite() && value.abs() >= 1e-8 && value.abs() <= 1_000_000.0 {
                fields.push(layout_field(
                    &format!("finite_float_0x{offset:X}"),
                    offset,
                    4,
                    "float32",
                    Some(LayoutValue::F32(value)),
                    "Finite float candidate in a modern Havok Physics payload. Exported for schema recovery only.",
                    "raw",
                    false,
                ));
            }
        }
    }
}

pub(crate) fn add_word_fallback_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    if fields.is_empty() {
        for offset in (0..payload.len().min(64)).step_by(4) {
            if offset + 4 > payload.len() {
                break;
            }
            fields.push(layout_field(
                &format!("u32_0x{offset:X}"),
                offset,
                4,
                "uint32",
                le_u32(&payload[offset..offset + 4]).map(LayoutValue::U32),
                "Unverified 32-bit word sample from this preserved payload.",
                "raw",
                false,
            ));
        }
    }
}

pub(crate) fn add_raw_fallback_layout(
    payload: &[u8],
    record: &ItemRecord,
    fields: &mut Vec<LayoutField>,
) {
    let type_name = record.type_name.as_str();
    let _ = record;
    let _ = type_name;
    let stride = if record.count > 0 {
        payload.len() / record.count as usize
    } else {
        payload.len()
    };
    if fields.is_empty() && stride > 0 {
        fields.push(layout_field(
            "raw_payload",
            0,
            payload.len(),
            "bytes",
            Some(LayoutValue::Text(format!("stride={stride}"))),
            "Preserved object bytes with no recovered field layout yet.",
            "raw",
            false,
        ));
    }
}
