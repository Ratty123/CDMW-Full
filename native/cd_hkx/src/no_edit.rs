use crate::*;

pub fn read_no_edit_model(data: &[u8]) -> Result<HkxNoEditModel, String> {
    if data.is_empty() {
        return Err("HKX input is empty".to_string());
    }
    let summary = parse_summary(data);
    if summary.tag0_offset.is_none() {
        return Err("HKX TAG0 marker was not found".to_string());
    }
    if summary.tag_items.is_empty() {
        return Err("HKX tag table was not recovered".to_string());
    }
    let raw_segments = build_no_edit_segments(data, &summary);
    if raw_segments.is_empty() {
        return Err("HKX no-edit segment model was not recovered".to_string());
    }
    Ok(HkxNoEditModel {
        original_byte_length: data.len(),
        raw_segments,
        summary,
    })
}

pub fn write_no_edit_model(model: &HkxNoEditModel) -> Result<Vec<u8>, String> {
    if model.original_byte_length == 0 {
        return Err("native no-edit model has no original bytes".to_string());
    }
    if model.raw_segments.is_empty() {
        return Err("native no-edit model has no raw-preserved segments".to_string());
    }
    let mut expected_offset = 0usize;
    let mut output = Vec::with_capacity(model.original_byte_length);
    for segment in &model.raw_segments {
        if segment.offset != expected_offset {
            return Err(format!(
                "native no-edit segment gap before 0x{:X}: expected 0x{:X}",
                segment.offset, expected_offset
            ));
        }
        if segment.bytes.len() != segment.byte_length {
            return Err(format!(
                "native no-edit segment '{}' byte length mismatch: declared {}, actual {}",
                segment.label,
                segment.byte_length,
                segment.bytes.len()
            ));
        }
        output.extend_from_slice(&segment.bytes);
        expected_offset = expected_offset.saturating_add(segment.byte_length);
    }
    if expected_offset != model.original_byte_length {
        return Err(format!(
            "native no-edit segment coverage ended at 0x{:X}, expected file length 0x{:X}",
            expected_offset, model.original_byte_length
        ));
    }
    Ok(output)
}

pub(crate) fn build_no_edit_segments(data: &[u8], summary: &HkxSummary) -> Vec<HkxNoEditSegment> {
    if data.is_empty() {
        return Vec::new();
    }
    let mut boundaries = vec![0usize, data.len()];
    for item in &summary.tag_items {
        let start = item
            .length_word_offset
            .unwrap_or(item.offset)
            .min(data.len());
        boundaries.push(start);
        boundaries.push(item.offset.min(data.len()));
        if let Some(end) = item
            .word_end_offset
            .or(item.marker_end_offset)
            .filter(|end| *end <= data.len())
        {
            boundaries.push(end);
        }
    }
    boundaries.sort_unstable();
    boundaries.dedup();
    boundaries
        .windows(2)
        .filter_map(|window| {
            let start = window[0];
            let end = window[1];
            if start >= end || end > data.len() {
                return None;
            }
            let label = summary
                .tag_items
                .iter()
                .find_map(|item| {
                    let item_start = item
                        .length_word_offset
                        .unwrap_or(item.offset)
                        .min(data.len());
                    let item_marker = item.offset.min(data.len());
                    let item_end = item
                        .word_end_offset
                        .or(item.marker_end_offset)
                        .filter(|candidate| *candidate <= data.len())?;
                    if start == item_start && end <= item_marker {
                        return Some(format!("{}_length", item.name));
                    }
                    if start >= item_marker && end <= item_end {
                        return Some(item.name.clone());
                    }
                    None
                })
                .unwrap_or_else(|| "raw_gap".to_string());
            Some(HkxNoEditSegment {
                label,
                offset: start,
                byte_length: end - start,
                bytes: data[start..end].to_vec(),
            })
        })
        .collect()
}

pub(crate) fn first_mismatch_offset(left: &[u8], right: &[u8]) -> Option<usize> {
    let shared_len = left.len().min(right.len());
    for index in 0..shared_len {
        if left[index] != right[index] {
            return Some(index);
        }
    }
    if left.len() != right.len() {
        return Some(shared_len);
    }
    None
}

pub fn roundtrip_no_edit(data: &[u8]) -> (Vec<u8>, NoEditBinaryWriterReport) {
    match read_no_edit_model(data) {
        Ok(model) => match write_no_edit_model(&model) {
            Ok(output) => {
                let byte_identical = output == data;
                let first_mismatch = if byte_identical {
                    None
                } else {
                    first_mismatch_offset(data, &output)
                };
                let report = NoEditBinaryWriterReport {
                    format: "cd_hkx_no_edit_binary_writer_v1".to_string(),
                    status: if byte_identical {
                        "byte_identical".to_string()
                    } else {
                        "mismatch".to_string()
                    },
                    native_writer_status: "available".to_string(),
                    no_edit_roundtrip_mode: "native_read_model_write_lossless_bytes".to_string(),
                    read_model_write_pipeline: "raw_preserving_model".to_string(),
                    available: true,
                    native_read_model_write_available: true,
                    parsed_model_available: true,
                    byte_identical,
                    byte_identical_no_edit_rebuild_supported: byte_identical,
                    semantic_rebuild_supported: false,
                    havok_xml_import_unblocked: false,
                    input_byte_length: data.len(),
                    output_byte_length: output.len(),
                    parsed_raw_segment_count: model.raw_segments.len(),
                    parsed_tag_item_count: model.summary.tag_items.len(),
                    parsed_item_record_count: model.summary.item_records.len(),
                    parsed_object_record_count: model.summary.object_records.len(),
                    first_mismatch_offset: first_mismatch,
                    validation_errors: Vec::new(),
                };
                (output, report)
            }
            Err(error) => (
                Vec::new(),
                NoEditBinaryWriterReport {
                    format: "cd_hkx_no_edit_binary_writer_v1".to_string(),
                    status: "write_error".to_string(),
                    native_writer_status: "available".to_string(),
                    no_edit_roundtrip_mode: "native_read_model_write_lossless_bytes".to_string(),
                    read_model_write_pipeline: "raw_preserving_model".to_string(),
                    available: true,
                    native_read_model_write_available: true,
                    parsed_model_available: true,
                    byte_identical: false,
                    byte_identical_no_edit_rebuild_supported: false,
                    semantic_rebuild_supported: false,
                    havok_xml_import_unblocked: false,
                    input_byte_length: data.len(),
                    output_byte_length: 0,
                    parsed_raw_segment_count: model.raw_segments.len(),
                    parsed_tag_item_count: 0,
                    parsed_item_record_count: 0,
                    parsed_object_record_count: 0,
                    first_mismatch_offset: Some(0),
                    validation_errors: vec![error],
                },
            ),
        },
        Err(error) => (
            Vec::new(),
            NoEditBinaryWriterReport {
                format: "cd_hkx_no_edit_binary_writer_v1".to_string(),
                status: "read_error".to_string(),
                native_writer_status: "available".to_string(),
                no_edit_roundtrip_mode: "native_read_model_write_lossless_bytes".to_string(),
                read_model_write_pipeline: "raw_preserving_model".to_string(),
                available: true,
                native_read_model_write_available: false,
                parsed_model_available: false,
                byte_identical: false,
                byte_identical_no_edit_rebuild_supported: false,
                semantic_rebuild_supported: false,
                havok_xml_import_unblocked: false,
                input_byte_length: data.len(),
                output_byte_length: 0,
                parsed_raw_segment_count: 0,
                parsed_tag_item_count: 0,
                parsed_item_record_count: 0,
                parsed_object_record_count: 0,
                first_mismatch_offset: Some(0),
                validation_errors: vec![error],
            },
        ),
    }
}

pub fn verify_no_edit_roundtrip(data: &[u8]) -> NoEditBinaryWriterReport {
    let (_output, report) = roundtrip_no_edit(data);
    report
}
