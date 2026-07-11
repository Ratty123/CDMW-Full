use crate::*;

pub(crate) fn detect_sdk_version(data: &[u8]) -> String {
    let marker = b"SDKV";
    let Some(offset) = find_bytes(data, marker, 0) else {
        return String::new();
    };
    let start = offset + 4;
    let end = (start + 32).min(data.len());
    data[start..end]
        .iter()
        .copied()
        .take_while(|byte| byte.is_ascii_digit())
        .map(char::from)
        .collect()
}

pub fn parse_summary(data: &[u8]) -> HkxSummary {
    let tag_items = find_tag_items(data);
    let string_table_names = extract_tst1_type_names(data, &tag_items);
    let (declared_type_name_count, type_infos, mut warnings) =
        parse_tna1_type_infos(data, &tag_items, &string_table_names);
    let type_names = if type_infos.is_empty() {
        string_table_names.clone()
    } else {
        type_infos.iter().map(TypeInfo::display_name).collect()
    };
    let declared_size = be_u32(data.get(0..4).unwrap_or_default());
    if let Some(size) = declared_size {
        if size as usize != data.len() {
            warnings.push(format!(
                "Declared size {size} does not match payload size {}.",
                data.len()
            ));
        }
    }
    let item_records = parse_item_records(data, &tag_items, &type_infos, &type_names);
    let tagfile_reference_fixups = parse_tagfile_reference_fixups(
        data,
        &tag_items,
        &item_records,
        &type_infos,
        &type_names,
        &string_table_names,
    );
    let fixup_semantics_report = build_fixup_semantics_report(&tagfile_reference_fixups);
    let object_records = parse_object_records(data, &tag_items, &item_records);
    let native_model_graph = build_native_model_graph(
        data,
        &item_records,
        &object_records,
        &tagfile_reference_fixups,
    );
    let hard_internal_evidence = build_hard_internal_evidence(&object_records);
    let real_hkclass_metadata = decode_real_hkclass_metadata(data, &item_records);
    let decoder_evidence_v2 = build_decoder_evidence_v2(
        &object_records,
        &tagfile_reference_fixups,
        &fixup_semantics_report,
        &native_model_graph,
    );
    let physics_tuning_groups = parse_physics_tuning_groups(data, &tag_items, &item_records);
    let modding_readiness = build_hkx_modding_readiness(
        &object_records,
        &native_model_graph,
        &hard_internal_evidence,
        &real_hkclass_metadata,
        &decoder_evidence_v2,
        &physics_tuning_groups,
    );
    HkxSummary {
        declared_size,
        size_matches: declared_size
            .map(|size| size as usize == data.len())
            .unwrap_or(false),
        sdk_version: detect_sdk_version(data),
        tag0_offset: find_bytes(&data[..data.len().min(64)], b"TAG0", 0),
        tag_items,
        string_table_names,
        type_infos,
        declared_type_name_count,
        type_names,
        item_records,
        object_records,
        tagfile_reference_fixups,
        fixup_semantics_report,
        native_model_graph,
        hard_internal_evidence,
        real_hkclass_metadata,
        decoder_evidence_v2,
        modding_readiness,
        physics_tuning_groups,
        warnings,
    }
}
