use std::collections::BTreeMap;
use std::fmt::Write;

const TAG_ITEM_MARKERS: [&str; 10] = [
    "SDKV", "DATA", "TYPE", "MTTP", "TST1", "TNA1", "TPAD", "INDX", "ITEM", "PTCH",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagItem {
    pub name: String,
    pub offset: usize,
    pub length_word_offset: Option<usize>,
    pub raw_length_word: Option<u32>,
    pub declared_length: Option<u32>,
    pub length_flags: Option<u32>,
    pub marker_end_offset: Option<usize>,
    pub word_end_offset: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeInfo {
    pub index: u32,
    pub name: String,
    pub template_parameters: Vec<(String, u32)>,
}

impl TypeInfo {
    pub fn display_name(&self) -> String {
        if self.template_parameters.is_empty() {
            return self.name.clone();
        }
        let parameters = self
            .template_parameters
            .iter()
            .map(|(name, value)| format!("{name}={value}"))
            .collect::<Vec<_>>()
            .join(", ");
        format!("{}<{}>", self.name, parameters)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemRecord {
    pub index: usize,
    pub raw_type_flags: u32,
    pub type_index: u32,
    pub flags: u32,
    pub data_offset: u32,
    pub absolute_data_offset: Option<usize>,
    pub count: u32,
    pub type_name: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum LayoutValue {
    U32(u32),
    U64(u64),
    F32(f32),
    Text(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct LayoutField {
    pub name: String,
    pub offset: usize,
    pub size: usize,
    pub data_type: String,
    pub value: Option<LayoutValue>,
    pub description: String,
    pub confidence: String,
    pub editable: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReferenceCandidate {
    pub offset: usize,
    pub reference_kind: String,
    pub reference_category: String,
    pub owner_field_name: Option<String>,
    pub raw_value: u32,
    pub target_record_index: usize,
    pub target_type_index: u32,
    pub target_type_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagfileFixupWord {
    pub index: usize,
    pub offset: usize,
    pub value: u32,
    pub match_kind: String,
    pub reference_category: String,
    pub target_record_index: Option<usize>,
    pub target_type_index: Option<u32>,
    pub target_type_name: Option<String>,
    pub target_data_offset: Option<u32>,
    pub target_absolute_offset: Option<usize>,
    pub target_string_index: Option<usize>,
    pub target_string: Option<String>,
    pub owner_record_index: Option<usize>,
    pub owner_type_index: Option<u32>,
    pub owner_type_name: Option<String>,
    pub owner_local_offset: Option<usize>,
    pub patch_value: Option<u64>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagfilePtchPatchSite {
    pub index: usize,
    pub ptch_word_index: usize,
    pub section_word_index: Option<usize>,
    pub section_word_offset: Option<usize>,
    pub patch_site_offset: u32,
    pub owner_record_index: Option<usize>,
    pub owner_type_index: Option<u32>,
    pub owner_type_name: Option<String>,
    pub owner_local_offset: Option<usize>,
    pub patch_value: Option<u64>,
    pub target_status: String,
    pub reference_category: String,
    pub target_record_index: Option<usize>,
    pub target_type_index: Option<u32>,
    pub target_type_name: Option<String>,
    pub target_data_offset: Option<u32>,
    pub target_absolute_offset: Option<usize>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagfilePtchTable {
    pub offset: usize,
    pub payload_offset: usize,
    pub payload_byte_length: usize,
    pub word_count: usize,
    pub header: [u32; 4],
    pub patch_site_count: usize,
    pub resolved_patch_site_count: usize,
    pub null_patch_site_count: usize,
    pub unresolved_patch_site_count: usize,
    pub confidence: String,
    pub patch_sites: Vec<TagfilePtchPatchSite>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagfileFixupSection {
    pub name: String,
    pub offset: usize,
    pub payload_byte_length: usize,
    pub word_count: usize,
    pub shown_word_count: usize,
    pub truncated_word_count: usize,
    pub match_kind_counts: BTreeMap<String, usize>,
    pub reference_category_counts: BTreeMap<String, usize>,
    pub record_offset_match_count: usize,
    pub null_word_count: usize,
    pub type_index_match_count: usize,
    pub string_table_index_match_count: usize,
    pub ptch_tables: Vec<TagfilePtchTable>,
    pub resolved_references: Vec<TagfileFixupWord>,
    pub words: Vec<TagfileFixupWord>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TagfileFixupSummary {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub match_kind_counts: BTreeMap<String, usize>,
    pub reference_category_counts: BTreeMap<String, usize>,
    pub section_count: usize,
    pub ptch_table_count: usize,
    pub ptch_patch_site_count: usize,
    pub ptch_resolved_patch_site_count: usize,
    pub ptch_null_patch_site_count: usize,
    pub ptch_unresolved_patch_site_count: usize,
    pub sections: Vec<TagfileFixupSection>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FixupSemanticsRemainingCase {
    pub priority_rank: usize,
    pub case_name: String,
    pub count: usize,
    pub description: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FixupSemanticsSectionSummary {
    pub name: String,
    pub payload_byte_length: usize,
    pub word_count: usize,
    pub ptch_table_count: usize,
    pub ptch_patch_site_count: usize,
    pub ptch_patch_site_resolved_count: usize,
    pub ptch_patch_site_unresolved_count: usize,
    pub match_kind_counts: BTreeMap<String, usize>,
    pub reference_category_counts: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FixupSemanticsReport {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub ptch_table_count: usize,
    pub ptch_patch_site_count: usize,
    pub ptch_object_patch_site_count: usize,
    pub ptch_null_patch_site_count: usize,
    pub ptch_unresolved_patch_site_count: usize,
    pub ptch_tuple_shape_counts: BTreeMap<String, usize>,
    pub ptch_payload_match_kind_counts: BTreeMap<String, usize>,
    pub ptch_reference_category_counts: BTreeMap<String, usize>,
    pub ptch_target_status_counts: BTreeMap<String, usize>,
    pub varuint_status_counts: BTreeMap<String, usize>,
    pub ptch_remaining_case_priorities: Vec<FixupSemanticsRemainingCase>,
    pub section_summaries: Vec<FixupSemanticsSectionSummary>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ObjectRecord {
    pub record_index: usize,
    pub type_index: u32,
    pub type_name: String,
    pub count: u32,
    pub data_offset: u32,
    pub absolute_data_offset: Option<usize>,
    pub byte_length: usize,
    pub stride: Option<f32>,
    pub status: String,
    pub fields: Vec<LayoutField>,
    pub references: Vec<ReferenceCandidate>,
    pub raw_hex_prefix: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FixedFloatSlot {
    pub item_index: usize,
    pub offset: usize,
    pub name: String,
    pub value: f32,
    pub description: String,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PhysicsTuningGroup {
    pub category: String,
    pub label: String,
    pub type_name: String,
    pub record_index: usize,
    pub count: u32,
    pub byte_length: usize,
    pub stride: usize,
    pub description: String,
    pub confidence: String,
    pub edit_rule: String,
    pub slots: Vec<FixedFloatSlot>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeGraphNode {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub record_index: Option<usize>,
    pub type_index: Option<u32>,
    pub type_name: Option<String>,
    pub data_offset: Option<u32>,
    pub count: Option<u32>,
    pub graph_order: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeGraphEdge {
    pub source: String,
    pub target: String,
    pub relation: String,
    pub source_record_index: Option<usize>,
    pub target_record_index: Option<usize>,
    pub owner_field_name: Option<String>,
    pub owner_local_offset: Option<usize>,
    pub reference_category: String,
    pub resolution_source: String,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeOwnerArray {
    pub owner_record_index: usize,
    pub owner_type_name: String,
    pub field_name: String,
    pub target_record_index: usize,
    pub target_type_name: String,
    pub array_type: String,
    pub element_type: String,
    pub numelements: Option<u32>,
    pub owner_local_offset: usize,
    pub resolution_source: String,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeNamedVariant {
    pub variant_record_index: usize,
    pub name: Option<String>,
    pub class_name: Option<String>,
    pub object_record_index: Option<usize>,
    pub object_type_name: Option<String>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeRootInfo {
    pub record_index: Option<usize>,
    pub type_name: Option<String>,
    pub method: String,
    pub confidence: String,
    pub named_variant_count: usize,
    pub named_variants: Vec<NativeNamedVariant>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeModelGraph {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub node_count: usize,
    pub edge_count: usize,
    pub fixup_backed_reference_edge_count: usize,
    pub inferred_reference_edge_count: usize,
    pub owner_array_count: usize,
    pub root: NativeRootInfo,
    pub graph_order: Vec<usize>,
    pub nodes: Vec<NativeGraphNode>,
    pub edges: Vec<NativeGraphEdge>,
    pub owner_arrays: Vec<NativeOwnerArray>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HardInternalEvidenceTarget {
    pub key: String,
    pub label: String,
    pub description: String,
    pub status: String,
    pub proof_status: String,
    pub present_in_file: bool,
    pub resolved: bool,
    pub import_blocking: bool,
    pub observed_record_count: usize,
    pub observed_byte_count: usize,
    pub observed_types: Vec<String>,
    pub observed_fields: Vec<String>,
    pub record_indices: Vec<usize>,
    pub unresolved_blockers: Vec<String>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HardInternalEvidenceReport {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub target_count: usize,
    pub observed_target_count: usize,
    pub unresolved_target_count: usize,
    pub total_observed_byte_count: usize,
    pub targets: Vec<HardInternalEvidenceTarget>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RealHkClassMemberMetadata {
    pub name: String,
    pub record_index: usize,
    pub item_index: usize,
    pub type_code: u8,
    pub type_name: String,
    pub subtype_code: u8,
    pub subtype_name: String,
    pub c_array_size: u16,
    pub flags: u16,
    pub offset: u16,
    pub class_ref_record_index: Option<usize>,
    pub class_ref_name: Option<String>,
    pub enum_ref_record_index: Option<usize>,
    pub enum_ref_name: Option<String>,
    pub attributes_ref_record_index: Option<usize>,
    pub template_ref: Option<String>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RealHkClassEnumMetadata {
    pub name: String,
    pub record_index: usize,
    pub item_count: u32,
    pub items_record_index: Option<usize>,
    pub flags: Option<u32>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RealHkClassMetadata {
    pub name: String,
    pub record_index: usize,
    pub parent_record_index: Option<usize>,
    pub parent_name: Option<String>,
    pub object_size: Option<u32>,
    pub version: Option<u32>,
    pub flags: Option<u32>,
    pub signature: Option<u32>,
    pub defaults_record_index: Option<usize>,
    pub attributes_record_index: Option<usize>,
    pub declared_enum_count: u32,
    pub declared_member_count: u32,
    pub members_record_index: Option<usize>,
    pub enums_record_index: Option<usize>,
    pub members: Vec<RealHkClassMemberMetadata>,
    pub enums: Vec<RealHkClassEnumMetadata>,
    pub recovered_requirements: BTreeMap<String, bool>,
    pub unresolved_requirements: Vec<String>,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RealHkClassMetadataReport {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub class_count: usize,
    pub member_count: usize,
    pub enum_count: usize,
    pub recovered_requirements: BTreeMap<String, bool>,
    pub unresolved_requirements: Vec<String>,
    pub classes: Vec<RealHkClassMetadata>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecoderEvidenceClassStatus {
    pub type_name: String,
    pub record_count: usize,
    pub byte_count: usize,
    pub decoded_field_count: usize,
    pub reference_count: usize,
    pub editable_field_count: usize,
    pub status: String,
    pub friendly_status: String,
    pub missing_requirements: Vec<String>,
    pub link_evidence: Vec<String>,
    pub corpus_priority_score: usize,
    pub read_only: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecoderEvidenceFixupBackedField {
    pub class_name: String,
    pub field_name: String,
    pub reference_category: String,
    pub count: usize,
    pub confidence: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecoderEvidenceV2 {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub read_only: bool,
    pub class_status_count: usize,
    pub priority_class_count: usize,
    pub total_partial_byte_count: usize,
    pub unresolved_or_packed_case_count: usize,
    pub owner_array_count: usize,
    pub reference_semantic_counts: BTreeMap<String, usize>,
    pub link_evidence_counts: BTreeMap<String, usize>,
    pub class_statuses: Vec<DecoderEvidenceClassStatus>,
    pub fixup_backed_fields: Vec<DecoderEvidenceFixupBackedField>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HkxModdingTaskGroup {
    pub key: String,
    pub label: String,
    pub readiness_label: String,
    pub patchable_slot_count: usize,
    pub context_record_count: usize,
    pub evidence: Vec<String>,
    pub risk: String,
    pub import_safe: bool,
    pub description: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HkxSemanticWriterGate {
    pub status: String,
    pub mode: String,
    pub enabled: bool,
    pub raw_preserving_no_edit_writer_required: bool,
    pub semantic_rebuild_supported: bool,
    pub fixed_size_value_edits_allowed: bool,
    pub allowed_edits: Vec<String>,
    pub blocked_edits: Vec<String>,
    pub requirements: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HkxModdingReadiness {
    pub format: String,
    pub status: String,
    pub imported: bool,
    pub read_only: bool,
    pub per_file_label: String,
    pub readiness_labels: Vec<String>,
    pub fixed_size_patch_importable: bool,
    pub havok_xml_importable: bool,
    pub new_editable_fields_enabled: bool,
    pub decoded_object_count: usize,
    pub patchable_slot_count: usize,
    pub fixup_backed_reference_edge_count: usize,
    pub owner_array_count: usize,
    pub unresolved_or_packed_case_count: usize,
    pub semantic_writer_gate: HkxSemanticWriterGate,
    pub task_groups: Vec<HkxModdingTaskGroup>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxSummary {
    pub declared_size: Option<u32>,
    pub size_matches: bool,
    pub sdk_version: String,
    pub tag0_offset: Option<usize>,
    pub tag_items: Vec<TagItem>,
    pub string_table_names: Vec<String>,
    pub type_infos: Vec<TypeInfo>,
    pub declared_type_name_count: Option<u32>,
    pub type_names: Vec<String>,
    pub item_records: Vec<ItemRecord>,
    pub object_records: Vec<ObjectRecord>,
    pub tagfile_reference_fixups: TagfileFixupSummary,
    pub fixup_semantics_report: FixupSemanticsReport,
    pub native_model_graph: NativeModelGraph,
    pub hard_internal_evidence: HardInternalEvidenceReport,
    pub real_hkclass_metadata: RealHkClassMetadataReport,
    pub decoder_evidence_v2: DecoderEvidenceV2,
    pub modding_readiness: HkxModdingReadiness,
    pub physics_tuning_groups: Vec<PhysicsTuningGroup>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxNoEditSegment {
    pub label: String,
    pub offset: usize,
    pub byte_length: usize,
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HkxNoEditModel {
    pub original_byte_length: usize,
    pub raw_segments: Vec<HkxNoEditSegment>,
    pub summary: HkxSummary,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NoEditBinaryWriterReport {
    pub format: String,
    pub status: String,
    pub native_writer_status: String,
    pub no_edit_roundtrip_mode: String,
    pub read_model_write_pipeline: String,
    pub available: bool,
    pub native_read_model_write_available: bool,
    pub parsed_model_available: bool,
    pub byte_identical: bool,
    pub byte_identical_no_edit_rebuild_supported: bool,
    pub semantic_rebuild_supported: bool,
    pub havok_xml_import_unblocked: bool,
    pub input_byte_length: usize,
    pub output_byte_length: usize,
    pub parsed_raw_segment_count: usize,
    pub parsed_tag_item_count: usize,
    pub parsed_item_record_count: usize,
    pub parsed_object_record_count: usize,
    pub first_mismatch_offset: Option<usize>,
    pub validation_errors: Vec<String>,
}

fn be_u32(bytes: &[u8]) -> Option<u32> {
    if bytes.len() < 4 {
        return None;
    }
    Some(u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn le_u32(bytes: &[u8]) -> Option<u32> {
    if bytes.len() < 4 {
        return None;
    }
    Some(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn le_u16(bytes: &[u8]) -> Option<u16> {
    if bytes.len() < 2 {
        return None;
    }
    Some(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn le_u64(bytes: &[u8]) -> Option<u64> {
    if bytes.len() < 8 {
        return None;
    }
    Some(u64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}

fn le_f32(bytes: &[u8]) -> Option<f32> {
    le_u32(bytes).map(f32::from_bits)
}

fn find_bytes(haystack: &[u8], needle: &[u8], start: usize) -> Option<usize> {
    if needle.is_empty() || start >= haystack.len() || needle.len() > haystack.len() {
        return None;
    }
    haystack[start..]
        .windows(needle.len())
        .position(|window| window == needle)
        .map(|position| start + position)
}

fn decode_length_word(raw: u32) -> (u32, u32) {
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

fn tag_item_by_name<'a>(items: &'a [TagItem], name: &str) -> Option<&'a TagItem> {
    items.iter().find(|item| item.name == name)
}

fn next_tag_item<'a>(items: &'a [TagItem], item: &TagItem) -> Option<&'a TagItem> {
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

fn read_var_uint(payload: &[u8], mut offset: usize) -> Result<(u64, usize), String> {
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

fn data_payload_offset(items: &[TagItem]) -> Option<usize> {
    tag_item_by_name(items, "DATA").map(|item| item.offset + 4)
}

fn data_payload_end(data: &[u8], items: &[TagItem]) -> Option<usize> {
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

fn tag_item_payload<'a>(data: &'a [u8], items: &[TagItem], name: &str) -> Option<&'a [u8]> {
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

fn layout_field(
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

fn payload_hex_prefix(payload: &[u8], limit: usize) -> String {
    let mut out = String::new();
    for (index, byte) in payload.iter().take(limit).enumerate() {
        if index > 0 {
            out.push(' ');
        }
        let _ = write!(out, "{byte:02x}");
    }
    out
}

fn scalar_array_type_name(type_name: &str) -> bool {
    matches!(
        type_name,
        "unsigned char" | "unsigned short" | "unsigned int" | "unsigned long long" | "long long"
    )
}

fn object_reference_owner_field(
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

fn classify_object_reference(
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

fn possible_reference_candidates(
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

fn increment_count(map: &mut BTreeMap<String, usize>, key: &str) {
    *map.entry(key.to_string()).or_insert(0) += 1;
}

fn increment_count_by(map: &mut BTreeMap<String, usize>, key: &str, count: usize) {
    if count == 0 {
        return;
    }
    *map.entry(key.to_string()).or_insert(0) += count;
}

fn record_containing_data_offset<'a>(
    records: &'a [ItemRecord],
    data_offset: u32,
) -> Option<&'a ItemRecord> {
    records
        .iter()
        .filter(|record| record.data_offset <= data_offset)
        .max_by_key(|record| record.data_offset)
}

fn fixup_reference_category(
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

fn match_fixup_word(
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
        return TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "null".to_string(),
            reference_category: "null_reference".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: None,
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "strong inference".to_string(),
        };
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
    TagfileFixupWord {
        index,
        offset,
        value,
        match_kind: "unresolved_word".to_string(),
        reference_category: "unresolved_fixup_word".to_string(),
        target_record_index: None,
        target_type_index: None,
        target_type_name: None,
        target_data_offset: None,
        target_absolute_offset: None,
        target_string_index: None,
        target_string: None,
        owner_record_index: None,
        owner_type_index: None,
        owner_type_name: None,
        owner_local_offset: None,
        patch_value: None,
        confidence: "raw".to_string(),
    }
}

fn nested_item_word_match(
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
        return Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_length_word".to_string(),
            reference_category: "item_table_metadata".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: None,
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "confirmed".to_string(),
        });
    }
    if word_absolute_offset == item.offset {
        return Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_marker".to_string(),
            reference_category: "item_table_metadata".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: Some("ITEM".to_string()),
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "confirmed".to_string(),
        });
    }
    if word_absolute_offset > item.offset && word_absolute_offset < item.offset.saturating_add(16) {
        return Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "item_header_word".to_string(),
            reference_category: "item_table_metadata".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: None,
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "confirmed".to_string(),
        });
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

fn decode_ptch_patch_site(
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

fn decode_nested_ptch_table(
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

fn nested_ptch_word_match(
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
        return Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "ptch_length_word".to_string(),
            reference_category: "ptch_table_metadata".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: None,
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "confirmed".to_string(),
        });
    }
    if word_absolute_offset == ptch_item.offset {
        return Some(TagfileFixupWord {
            index,
            offset,
            value,
            match_kind: "ptch_marker".to_string(),
            reference_category: "ptch_table_metadata".to_string(),
            target_record_index: None,
            target_type_index: None,
            target_type_name: Some("PTCH".to_string()),
            target_data_offset: None,
            target_absolute_offset: None,
            target_string_index: None,
            target_string: None,
            owner_record_index: None,
            owner_type_index: None,
            owner_type_name: None,
            owner_local_offset: None,
            patch_value: None,
            confidence: "confirmed".to_string(),
        });
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
                return Some(TagfileFixupWord {
                    index,
                    offset,
                    value,
                    match_kind: "ptch_header_word".to_string(),
                    reference_category: "ptch_table_metadata".to_string(),
                    target_record_index: None,
                    target_type_index: None,
                    target_type_name: None,
                    target_data_offset: None,
                    target_absolute_offset: None,
                    target_string_index: None,
                    target_string: None,
                    owner_record_index: None,
                    owner_type_index: None,
                    owner_type_name: None,
                    owner_local_offset: None,
                    patch_value: None,
                    confidence: "confirmed".to_string(),
                });
            }
            if ptch_word_index == 4 {
                return Some(TagfileFixupWord {
                    index,
                    offset,
                    value,
                    match_kind: "ptch_patch_site_count".to_string(),
                    reference_category: "ptch_table_metadata".to_string(),
                    target_record_index: None,
                    target_type_index: None,
                    target_type_name: None,
                    target_data_offset: None,
                    target_absolute_offset: None,
                    target_string_index: None,
                    target_string: None,
                    owner_record_index: None,
                    owner_type_index: None,
                    owner_type_name: None,
                    owner_local_offset: None,
                    patch_value: None,
                    confidence: "confirmed".to_string(),
                });
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

fn parse_tagfile_reference_fixups(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
    type_infos: &[TypeInfo],
    type_names: &[String],
    string_table_names: &[String],
) -> TagfileFixupSummary {
    let mut sections = Vec::new();
    let mut total_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut total_reference_category_counts = BTreeMap::<String, usize>::new();
    for section_name in ["INDX", "TPAD"] {
        let Some(section_item) = tag_item_by_name(items, section_name) else {
            continue;
        };
        let payload = tag_item_payload(data, items, section_name).unwrap_or(&[]);
        let section_payload_start = section_item.offset.saturating_add(4);
        let section_payload_end = section_payload_start.saturating_add(payload.len());
        let nested_item = tag_item_by_name(items, "ITEM").filter(|item| {
            item.length_word_offset.is_some_and(|offset| {
                offset >= section_payload_start && offset < section_payload_end
            }) || (item.offset >= section_payload_start && item.offset < section_payload_end)
        });
        let nested_ptch = tag_item_by_name(items, "PTCH").filter(|item| {
            item.length_word_offset.is_some_and(|offset| {
                offset >= section_payload_start && offset < section_payload_end
            }) || (item.offset >= section_payload_start && item.offset < section_payload_end)
        });
        let word_count = payload.len() / 4;
        let shown_word_count = word_count.min(256);
        let mut words = Vec::new();
        let mut match_kind_counts = BTreeMap::<String, usize>::new();
        let mut reference_category_counts = BTreeMap::<String, usize>::new();
        let ptch_tables = nested_ptch
            .and_then(|item| decode_nested_ptch_table(data, section_item, item, records))
            .map(|table| vec![table])
            .unwrap_or_default();
        for word_index in 0..shown_word_count {
            let offset = word_index * 4;
            let value = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let word = nested_item
                .and_then(|item| {
                    nested_item_word_match(word_index, offset, value, section_item, item, records)
                })
                .or_else(|| {
                    nested_ptch.and_then(|item| {
                        nested_ptch_word_match(
                            data,
                            word_index,
                            offset,
                            value,
                            section_item,
                            item,
                            records,
                            type_infos,
                            type_names,
                            string_table_names,
                        )
                    })
                })
                .unwrap_or_else(|| {
                    match_fixup_word(
                        word_index,
                        offset,
                        value,
                        section_name,
                        records,
                        type_infos,
                        type_names,
                        string_table_names,
                    )
                });
            increment_count(&mut match_kind_counts, &word.match_kind);
            increment_count(&mut total_match_kind_counts, &word.match_kind);
            increment_count(&mut reference_category_counts, &word.reference_category);
            increment_count(
                &mut total_reference_category_counts,
                &word.reference_category,
            );
            words.push(word);
        }
        let resolved_references = words
            .iter()
            .filter(|word| {
                word.match_kind != "unresolved_word"
                    && !matches!(
                        word.reference_category.as_str(),
                        "item_table_metadata"
                            | "item_count"
                            | "ptch_table_metadata"
                            | "patch_offset_candidate"
                    )
            })
            .take(128)
            .cloned()
            .collect::<Vec<_>>();
        sections.push(TagfileFixupSection {
            name: section_name.to_string(),
            offset: section_item.offset,
            payload_byte_length: payload.len(),
            word_count,
            shown_word_count,
            truncated_word_count: word_count.saturating_sub(shown_word_count),
            record_offset_match_count: match_kind_counts.get("data_offset").copied().unwrap_or(0)
                + match_kind_counts
                    .get("item_data_offset")
                    .copied()
                    .unwrap_or(0)
                + match_kind_counts
                    .get("absolute_offset")
                    .copied()
                    .unwrap_or(0),
            null_word_count: match_kind_counts.get("null").copied().unwrap_or(0),
            type_index_match_count: match_kind_counts.get("type_index").copied().unwrap_or(0)
                + match_kind_counts
                    .get("item_type_flags")
                    .copied()
                    .unwrap_or(0),
            string_table_index_match_count: match_kind_counts
                .get("string_table_index")
                .copied()
                .unwrap_or(0),
            ptch_tables,
            match_kind_counts,
            reference_category_counts,
            resolved_references,
            words,
        });
    }
    let ptch_table_count = sections
        .iter()
        .map(|section| section.ptch_tables.len())
        .sum::<usize>();
    let ptch_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.patch_site_count)
        .sum::<usize>();
    let ptch_resolved_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.resolved_patch_site_count)
        .sum::<usize>();
    let ptch_null_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.null_patch_site_count)
        .sum::<usize>();
    let ptch_unresolved_patch_site_count = sections
        .iter()
        .flat_map(|section| section.ptch_tables.iter())
        .map(|table| table.unresolved_patch_site_count)
        .sum::<usize>();
    TagfileFixupSummary {
        format: "cd_hkx_tagfile_reference_fixups_v1".to_string(),
        status: "experimental_observation".to_string(),
        imported: false,
        section_count: sections.len(),
        match_kind_counts: total_match_kind_counts,
        reference_category_counts: total_reference_category_counts,
        ptch_table_count,
        ptch_patch_site_count,
        ptch_resolved_patch_site_count,
        ptch_null_patch_site_count,
        ptch_unresolved_patch_site_count,
        sections,
    }
}

fn add_fixup_remaining_case(
    cases: &mut BTreeMap<String, (usize, String)>,
    case_name: &str,
    count: usize,
    description: &str,
) {
    if count == 0 {
        return;
    }
    let entry = cases
        .entry(case_name.to_string())
        .or_insert_with(|| (0, description.to_string()));
    entry.0 += count;
    if entry.1.is_empty() {
        entry.1 = description.to_string();
    }
}

fn build_fixup_semantics_report(fixups: &TagfileFixupSummary) -> FixupSemanticsReport {
    let mut tuple_shape_counts = BTreeMap::<String, usize>::new();
    let mut payload_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut reference_category_counts = BTreeMap::<String, usize>::new();
    let mut target_status_counts = BTreeMap::<String, usize>::new();
    let mut varuint_status_counts = BTreeMap::<String, usize>::new();
    let mut remaining_cases = BTreeMap::<String, (usize, String)>::new();
    let mut section_summaries = Vec::new();
    let known_ptch_word_kinds = [
        "ptch_length_word",
        "ptch_marker",
        "ptch_header_word",
        "ptch_patch_site_count",
        "ptch_object_patch_offset",
        "ptch_null_patch_offset",
    ];
    let expected_tuple_shapes = ["1,1,0,2"];
    for section in &fixups.sections {
        for (kind, count) in &section.match_kind_counts {
            if kind.starts_with("ptch_") {
                increment_count_by(&mut payload_match_kind_counts, kind, *count);
                if !known_ptch_word_kinds.contains(&kind.as_str()) {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("ptch_match_kind:{kind}"),
                        *count,
                        "PTCH payload word matched a non-header/non-object shape that still needs corpus proof.",
                    );
                }
            }
        }
        for (category, count) in &section.reference_category_counts {
            increment_count_by(&mut reference_category_counts, category, *count);
            if matches!(
                category.as_str(),
                "data_reference_candidate"
                    | "string_reference"
                    | "type_reference"
                    | "type_class_reference"
                    | "patch_offset_candidate"
                    | "unresolved_fixup_word"
            ) {
                add_fixup_remaining_case(
                    &mut remaining_cases,
                    &format!("reference_category:{category}"),
                    *count,
                    "Observed reference category is not yet promoted into a full Havok fixup semantic.",
                );
            }
        }
        increment_count(&mut varuint_status_counts, "native_not_decoded");
        add_fixup_remaining_case(
            &mut remaining_cases,
            "varuint_status:native_not_decoded",
            1,
            "Native PTCH/fixup parser does not yet model section varuint streams.",
        );
        let mut patch_site_count = 0usize;
        let mut resolved_site_count = 0usize;
        let mut unresolved_site_count = 0usize;
        for table in &section.ptch_tables {
            let shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            increment_count(&mut tuple_shape_counts, &shape);
            if !expected_tuple_shapes.contains(&shape.as_str()) {
                add_fixup_remaining_case(
                    &mut remaining_cases,
                    &format!("ptch_tuple_shape:{shape}"),
                    1,
                    "PTCH table header shape differs from the currently verified object/null patch tuple.",
                );
            }
            patch_site_count += table.patch_site_count;
            resolved_site_count += table.resolved_patch_site_count + table.null_patch_site_count;
            unresolved_site_count += table.unresolved_patch_site_count;
            for site in &table.patch_sites {
                let target_status = if site.target_status.is_empty() {
                    "unresolved"
                } else {
                    site.target_status.as_str()
                };
                increment_count(&mut target_status_counts, target_status);
                if !site.reference_category.is_empty() {
                    increment_count(&mut reference_category_counts, &site.reference_category);
                }
                if target_status == "unresolved" {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        "unresolved_ptch_patch_site",
                        1,
                        "PTCH patch-site offset was found but its patched slot value was not resolved to null or an ITEM record.",
                    );
                } else if !matches!(target_status, "object" | "null") {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("non_object_ptch_patch_site:{target_status}"),
                        1,
                        "PTCH patch site resolved to a target status that is not yet modeled as object/null.",
                    );
                }
                if !site.reference_category.is_empty()
                    && !matches!(
                        site.reference_category.as_str(),
                        "object_reference" | "null_reference"
                    )
                {
                    add_fixup_remaining_case(
                        &mut remaining_cases,
                        &format!("patch_site_reference_category:{}", site.reference_category),
                        1,
                        "PTCH patch site carries a non-object/null reference category that needs dedicated semantics.",
                    );
                }
            }
        }
        section_summaries.push(FixupSemanticsSectionSummary {
            name: section.name.clone(),
            payload_byte_length: section.payload_byte_length,
            word_count: section.word_count,
            ptch_table_count: section.ptch_tables.len(),
            ptch_patch_site_count: patch_site_count,
            ptch_patch_site_resolved_count: resolved_site_count,
            ptch_patch_site_unresolved_count: unresolved_site_count,
            match_kind_counts: section.match_kind_counts.clone(),
            reference_category_counts: section.reference_category_counts.clone(),
        });
    }
    let mut remaining_rows = remaining_cases
        .into_iter()
        .map(|(case_name, (count, description))| (case_name, count, description))
        .collect::<Vec<_>>();
    remaining_rows.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    let ptch_remaining_case_priorities = remaining_rows
        .into_iter()
        .enumerate()
        .map(
            |(index, (case_name, count, description))| FixupSemanticsRemainingCase {
                priority_rank: index + 1,
                case_name,
                count,
                description,
            },
        )
        .collect::<Vec<_>>();
    FixupSemanticsReport {
        format: "cd_hkx_fixup_semantics_report_v1".to_string(),
        status: "experimental_observation".to_string(),
        imported: false,
        ptch_table_count: fixups.ptch_table_count,
        ptch_patch_site_count: fixups.ptch_patch_site_count,
        ptch_object_patch_site_count: fixups.ptch_resolved_patch_site_count,
        ptch_null_patch_site_count: fixups.ptch_null_patch_site_count,
        ptch_unresolved_patch_site_count: fixups.ptch_unresolved_patch_site_count,
        ptch_tuple_shape_counts: tuple_shape_counts,
        ptch_payload_match_kind_counts: payload_match_kind_counts,
        ptch_reference_category_counts: reference_category_counts,
        ptch_target_status_counts: target_status_counts,
        varuint_status_counts,
        ptch_remaining_case_priorities,
        section_summaries,
    }
}

fn scalar_array_spec(type_name: &str) -> Option<(&'static str, &'static str, usize, &'static str)> {
    match type_name {
        "unsigned char" => Some((
            "uint8_values",
            "uint8[]",
            1,
            "Read-only unsigned-byte array. These records commonly back compact flags, shape-key bytes, or mesh/physics index data.",
        )),
        "unsigned short" => Some((
            "uint16_values",
            "uint16[]",
            2,
            "Read-only unsigned-short array. These records commonly store compact indices, flags, or mesh/physics lookup values.",
        )),
        "unsigned int" => Some((
            "uint32_values",
            "uint32[]",
            4,
            "Read-only unsigned-int array. These records commonly store references, flags, counts, shape keys, or table words.",
        )),
        "unsigned long long" => Some((
            "uint64_values",
            "uint64[]",
            8,
            "Read-only unsigned 64-bit array. These records commonly store large identifiers, masks, or packed references.",
        )),
        "long long" => Some((
            "int64_values",
            "int64[]",
            8,
            "Read-only signed 64-bit array. These records are exported for comparison and reference recovery.",
        )),
        _ => None,
    }
}

fn enum_record_description(type_name: &str) -> Option<&'static str> {
    match type_name {
        "hknpShapeType::Enum" => Some("Shape kind enum values used by hknp shapes."),
        "hknpCollisionDispatchType::Enum" => {
            Some("Collision dispatch enum values used by hknp broad/narrow phase routing.")
        }
        "hknpShape::FlagsEnum" => Some("Shape flag bitfields used by hknp shape records."),
        "hkcdSimdTreeNamespace::Node::FlagsEnum" => Some("Spatial tree node flag bitfields."),
        _ => None,
    }
}

fn scalar_sample(payload: &[u8], byte_width: usize, count: u32, limit: usize) -> String {
    let decoded_count = (payload.len() / byte_width).min(count as usize);
    let values = (0..decoded_count.min(limit))
        .map(|index| {
            let offset = index * byte_width;
            match byte_width {
                1 => payload[offset].to_string(),
                2 => le_u16(&payload[offset..offset + 2])
                    .unwrap_or(0)
                    .to_string(),
                4 => le_u32(&payload[offset..offset + 4])
                    .unwrap_or(0)
                    .to_string(),
                8 => le_u64(&payload[offset..offset + 8])
                    .unwrap_or(0)
                    .to_string(),
                _ => "0".to_string(),
            }
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!("value_count={count}, decoded_count={decoded_count}, values=[{values}]")
}

fn decode_layout_fields(payload: &[u8], record: &ItemRecord) -> Vec<LayoutField> {
    let type_name = record.type_name.as_str();
    let stride = if record.count > 0 {
        payload.len() / record.count as usize
    } else {
        payload.len()
    };
    let mut fields = Vec::new();
    if type_name.starts_with("hkArray") && payload.len() >= 16 {
        fields.push(layout_field(
            "data_reference_or_offset",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely Havok array data reference or offset. Exact 2024.2 reference encoding is still unconfirmed.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "size",
            8,
            4,
            "uint32",
            le_u32(&payload[8..12]).map(LayoutValue::U32),
            "Likely current array element count.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "capacity_and_flags",
            12,
            4,
            "uint32",
            le_u32(&payload[12..16]).map(LayoutValue::U32),
            "Likely Havok array capacity and flags word. Rebuilding this safely is not supported yet.",
            "experimental",
            false,
        ));
    } else if type_name.starts_with("hkRefPtr") && payload.len() >= 8 {
        fields.push(layout_field(
            "referenced_object",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely Havok reference pointer payload.",
            "experimental",
            false,
        ));
    } else if type_name == "hkFloat3"
        && record.count > 0
        && payload.len() >= record.count as usize * 12
    {
        fields.push(layout_field(
            "float3_rows",
            0,
            record.count as usize * 12,
            "float32[3][]",
            Some(LayoutValue::Text(format!(
                "row_count={}, stride=12",
                record.count
            ))),
            "Local-space vector rows. For decoded convex shapes these are usually vertices.",
            "strong inference",
            true,
        ));
    } else if type_name == "hkVector4"
        && record.count > 0
        && payload.len() >= record.count as usize * 16
    {
        fields.push(layout_field(
            "float4_rows",
            0,
            record.count as usize * 16,
            "float32[4][]",
            Some(LayoutValue::Text(format!(
                "row_count={}, stride=16",
                record.count
            ))),
            "Four-float vector rows. For decoded convex shapes these are usually plane equations.",
            "strong inference",
            true,
        ));
    } else if type_name == "hkQsTransform"
        && record.count > 0
        && payload.len() >= record.count as usize * 48
    {
        let transform_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(128) {
            let base = item_index * transform_stride;
            if base + 48 > payload.len() {
                break;
            }
            let translation = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + component * 4..base + component * 4 + 4]).unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            let rotation = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + 16 + component * 4..base + 20 + component * 4])
                        .unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            let scale = (0..4usize)
                .map(|component| {
                    le_f32(&payload[base + 32 + component * 4..base + 36 + component * 4])
                        .unwrap_or(0.0)
                })
                .map(|value| format!("{value:.6}"))
                .collect::<Vec<_>>()
                .join(", ");
            fields.push(layout_field(
                &format!("qs_transform[{item_index}]"),
                base,
                48,
                "struct{hkVector4 translation; hkQuaternion rotation; hkVector4 scale}",
                Some(LayoutValue::Text(format!(
                    "translation=({translation}); rotation=({rotation}); scale=({scale})"
                ))),
                "Read-only hkQsTransform row. Usually skeleton pose or mapping data; editing requires skeleton schema validation.",
                "strong inference",
                false,
            ));
        }
    } else if type_name == "hkBone"
        && record.count > 0
        && payload.len() >= record.count as usize * 16
    {
        let bone_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(256) {
            let base = item_index * bone_stride;
            if base + 16 > payload.len() {
                break;
            }
            let name_ref = le_u32(&payload[base..base + 4]).unwrap_or(0);
            let parent_or_lock = i32::from_le_bytes([
                payload[base + 8],
                payload[base + 9],
                payload[base + 10],
                payload[base + 11],
            ]);
            let flags = le_u32(&payload[base + 12..base + 16]).unwrap_or(0);
            fields.push(layout_field(
                &format!("bone[{item_index}]"),
                base,
                bone_stride,
                "uint32 name_ref; int32 parent_or_lock; uint32 flags",
                Some(LayoutValue::Text(format!(
                    "name_reference={name_ref}, parent_or_lock={parent_or_lock}, flags_or_axis={flags}"
                ))),
                "Read-only hkBone row. Skeleton rebuilding is not supported.",
                "experimental",
                false,
            ));
        }
    } else if type_name == "hkInt16"
        && record.count > 0
        && payload.len() >= record.count as usize * 2
    {
        fields.push(layout_field(
            "int16_values",
            0,
            (record.count as usize * 2).min(payload.len()),
            "int16[]",
            Some(LayoutValue::Text(format!("value_count={}", record.count))),
            "Read-only hkInt16 array. In skeleton files this often stores parent indices or compact index maps.",
            "experimental",
            false,
        ));
    } else if let Some((field_name, data_type, byte_width, description)) =
        scalar_array_spec(type_name)
    {
        if record.count > 0 && payload.len() >= byte_width {
            fields.push(layout_field(
                field_name,
                0,
                payload.len().min(record.count as usize * byte_width),
                data_type,
                Some(LayoutValue::Text(scalar_sample(
                    payload,
                    byte_width,
                    record.count,
                    64,
                ))),
                &format!("{description} Editing is disabled until the owning Havok object field is confirmed."),
                "strong inference",
                false,
            ));
        }
    } else if let Some(description) = enum_record_description(type_name) {
        if record.count > 0 && !payload.is_empty() {
            let count = record.count.max(1) as usize;
            let stride = if payload.len() % count == 0 {
                Some(payload.len() / count)
            } else {
                None
            };
            let byte_width = if matches!(stride, Some(1 | 2 | 4 | 8)) {
                stride.unwrap()
            } else if payload.len() >= count * 4 {
                4
            } else if payload.len() >= count * 2 {
                2
            } else {
                1
            };
            fields.push(layout_field(
                "enum_or_flags_values",
                0,
                payload.len().min(record.count as usize * byte_width),
                &format!("enum/flags[{byte_width}-byte]"),
                Some(LayoutValue::Text(scalar_sample(
                    payload,
                    byte_width,
                    record.count,
                    64,
                ))),
                &format!("{description} Names for each numeric value are not fully mapped yet, so this is read-only context."),
                "strong inference",
                false,
            ));
        }
    } else if type_name == "int" && record.count > 0 && payload.len() >= record.count as usize * 4 {
        let values = (0..(record.count as usize).min(512))
            .map(|index| {
                let offset = index * 4;
                i32::from_le_bytes([
                    payload[offset],
                    payload[offset + 1],
                    payload[offset + 2],
                    payload[offset + 3],
                ])
            })
            .map(|value| value.to_string())
            .collect::<Vec<_>>()
            .join(", ");
        fields.push(layout_field(
            "int32_values",
            0,
            (record.count as usize * 4).min(payload.len()),
            "int32[]",
            Some(LayoutValue::Text(format!(
                "value_count={}, values=[{}]",
                record.count, values
            ))),
            "Read-only int array. In skeleton/mapper files this commonly stores compact bone or mapping indices.",
            "strong inference",
            false,
        ));
    } else if type_name == "char" && !payload.is_empty() {
        let nul_index = payload
            .iter()
            .position(|value| *value == 0)
            .unwrap_or(payload.len());
        let text = String::from_utf8_lossy(&payload[..nul_index]).to_string();
        fields.push(layout_field(
            "ascii_or_utf8_text",
            0,
            payload.len(),
            "char[]",
            Some(LayoutValue::Text(text)),
            "Read-only string payload. String editing is not safe because it can change record length and reference layout.",
            if nul_index < payload.len() {
                "confirmed"
            } else {
                "strong inference"
            },
            false,
        ));
    } else if type_name == "hknpConvexHull::Face"
        && record.count > 0
        && payload.len() >= record.count as usize * 4
    {
        fields.push(layout_field(
            "face_records",
            0,
            record.count as usize * 4,
            "struct{u16 index_start; u8 vertex_count; u8 meta}[]",
            Some(LayoutValue::Text(format!(
                "record_count={}, stride=4",
                record.count
            ))),
            "Convex face table. index_start points into the face-index byte array.",
            "strong inference",
            true,
        ));
    } else if type_name == "hkUint8" && record.count > 0 {
        fields.push(layout_field(
            "byte_values",
            0,
            (record.count as usize).min(payload.len()),
            "uint8[]",
            Some(LayoutValue::Text(format!("value_count={}", record.count))),
            "Byte array. In decoded convex hulls this is usually the face vertex index buffer.",
            "strong inference",
            true,
        ));
    } else if type_name == "hknpConvexHull::Edge"
        && record.count > 0
        && payload.len() >= record.count as usize * 4
    {
        fields.push(layout_field(
            "uint16_pairs",
            0,
            record.count as usize * 4,
            "uint16[2][]",
            Some(LayoutValue::Text(format!(
                "pair_count={}, stride=4",
                record.count
            ))),
            "Convex edge/support pairs. Topology role is still inferred.",
            "strong inference",
            true,
        ));
    } else if type_name == "hknpShapeMassProperties" && payload.len() >= 64 {
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
    } else if type_name == "hkCompressedMassProperties" && payload.len() >= 16 {
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
    } else if type_name == "hkPackedVector3" && record.count > 0 && payload.len() >= 4 {
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
    } else if type_name == "HavokShapeNameProperty" && payload.len() >= 0x24 {
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
    } else if type_name == "hknpMaterial" && record.count > 0 {
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
    } else if type_name == "hkSkeleton" && payload.len() >= 64 {
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
    } else if type_name == "hkaSkeletonMapper" && payload.len() >= 64 {
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
    } else if type_name == "hkaSkeletonMapperData::SimpleMapping" && record.count > 0 {
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
    } else if type_name == "hkaAnimationContainer" && payload.len() >= 16 {
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
    } else if matches!(type_name, "hkRefVariant" | "hkStringPtr") && payload.len() >= 8 {
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
    } else if matches!(
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
    } else if type_name == "hknpShapeProperties::Entry" && record.count > 0 && payload.len() >= 16 {
        let entry_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * entry_stride;
            if base + 16 > payload.len() {
                break;
            }
            let key = le_u32(&payload[base..base + 4]).unwrap_or(0);
            let value = le_u32(&payload[base + 4..base + 8]).unwrap_or(0);
            let flags = le_u32(&payload[base + 8..base + 12]).unwrap_or(0);
            let user = le_u32(&payload[base + 12..base + 16]).unwrap_or(0);
            fields.push(layout_field(
                &format!("property_entry[{item_index}]"),
                base,
                entry_stride.min(16),
                "uint32[4]",
                Some(LayoutValue::Text(format!(
                    "key_or_id={key}, value_or_reference={value}, flags_or_type={flags}, user_data={user}"
                ))),
                "Likely hknp shape-property entry row. Exact key/value/flags names are not confirmed.",
                "experimental",
                false,
            ));
        }
    } else if type_name.starts_with("hkFreeListArrayElement") && record.count > 0 {
        let element_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * element_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..element_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("free_list_element[{item_index}]"),
                base,
                element_stride,
                "uint32[]/free-list-element",
                Some(LayoutValue::Text(words)),
                "Free-list element backing compound/shape-instance storage. List rebuilding is not supported.",
                "experimental",
                false,
            ));
        }
    } else if type_name == "hknpCompoundShape" && payload.len() >= 32 {
        for (offset, name, description) in [
            (
                0x00usize,
                "base_or_vtable_words",
                "Initial object/base words for hknpCompoundShape.",
            ),
            (
                0x20usize,
                "shape_instances_or_storage_pair",
                "Possible child shape instance storage offset/count or reference pair.",
            ),
            (
                0x30usize,
                "simd_tree_or_bounds_pair",
                "Possible tree/bounds reference or count pair.",
            ),
            (
                0x40usize,
                "free_list_or_child_metadata_pair",
                "Possible free-list/child metadata pair.",
            ),
            (
                0x50usize,
                "shape_property_or_flags_pair",
                "Possible property/flags pair.",
            ),
            (
                0x60usize,
                "compound_runtime_pair",
                "Possible runtime/cache pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let first = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let second = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!("{first}, {second}"))),
                description,
                "experimental",
                false,
            ));
        }
    } else if type_name == "hknpShapeInstance" && record.count > 0 {
        let instance_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(64) {
            let base = item_index * instance_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..instance_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("shape_instance[{item_index}]"),
                base,
                instance_stride,
                "uint32[]/shape-instance",
                Some(LayoutValue::Text(words)),
                "Child shape-instance row. Likely links child shape data, transform/filter metadata, and shape keys.",
                "experimental",
                false,
            ));
        }
    } else if type_name == "hkcdSimdTreeNamespace::Node" && record.count > 0 {
        let node_stride = payload.len() / record.count.max(1) as usize;
        for item_index in 0..(record.count as usize).min(128) {
            let base = item_index * node_stride;
            if base >= payload.len() {
                break;
            }
            let words = (0..node_stride.min(32) / 4)
                .map(|word_index| {
                    le_u32(&payload[base + word_index * 4..base + word_index * 4 + 4]).unwrap_or(0)
                })
                .map(|word| format!("0x{word:08X}"))
                .collect::<Vec<_>>()
                .join(" ");
            fields.push(layout_field(
                &format!("simd_tree_node[{item_index}]"),
                base,
                node_stride,
                "uint32[]/float32[]/tree-node",
                Some(LayoutValue::Text(words)),
                "Spatial acceleration tree node used by compound/mesh shapes. Bounds/child encoding is not fully named yet.",
                "experimental",
                false,
            ));
        }
    } else if type_name == "hkRootLevelContainer" && payload.len() >= 16 {
        fields.push(layout_field(
            "named_variants_data_reference",
            0,
            8,
            "uint64/reference",
            le_u64(&payload[0..8]).map(LayoutValue::U64),
            "Likely array/reference to hkRootLevelContainer::NamedVariant records.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "named_variants_size",
            8,
            4,
            "uint32",
            le_u32(&payload[8..12]).map(LayoutValue::U32),
            "Likely number of root named variants.",
            "experimental",
            false,
        ));
        fields.push(layout_field(
            "named_variants_capacity_and_flags",
            12,
            4,
            "uint32",
            le_u32(&payload[12..16]).map(LayoutValue::U32),
            "Likely Havok array capacity/flags for root variants. Structural edits are not supported.",
            "experimental",
            false,
        ));
    } else if type_name == "hkRootLevelContainer::NamedVariant" && payload.len() >= 24 {
        for (offset, name, description) in [
            (
                0usize,
                "name_reference",
                "Likely reference to variant name string.",
            ),
            (
                8usize,
                "class_name_reference",
                "Likely reference to Havok class/type name string.",
            ),
            (
                16usize,
                "object_reference",
                "Likely reference to the root object for this named variant.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint64/reference",
                le_u64(&payload[offset..offset + 8]).map(LayoutValue::U64),
                description,
                "experimental",
                false,
            ));
        }
    } else if type_name == "hknpPhysicsSystemData" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "materials_array_or_reference_pair",
                "Likely reference/count pair for hknpMaterial rows.",
            ),
            (
                0x08usize,
                "motion_properties_array_or_reference_pair",
                "Likely reference/count pair for hknpSharedMotionProperties rows.",
            ),
            (
                0x10usize,
                "body_cinfo_array_or_reference_pair",
                "Likely reference/count pair for ExtendedBodyCinfo body rows.",
            ),
            (
                0x18usize,
                "constraint_cinfo_array_or_reference_pair",
                "Likely reference/count pair for hknpConstraintCinfo rows.",
            ),
            (
                0x20usize,
                "shape_reference_array_or_pair",
                "Likely reference/count pair for shape references.",
            ),
            (
                0x28usize,
                "system_metadata_or_flags_pair",
                "Likely physics-system metadata, flags, or runtime pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/reference_count",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Structural array/reference edits are not supported."),
                "experimental",
                false,
            ));
        }
    } else if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "body_base_flags_or_type_pair",
                "Likely body type, flags, or base metadata pair.",
            ),
            (
                0x08usize,
                "shape_reference_or_key_pair",
                "Likely shape reference/index plus shape-key or flags.",
            ),
            (
                0x10usize,
                "motion_properties_reference_pair",
                "Likely reference/index to hknpSharedMotionProperties.",
            ),
            (
                0x18usize,
                "material_or_collision_filter_pair",
                "Likely material/filter/collision-layer metadata.",
            ),
            (
                0x20usize,
                "body_name_user_data_or_bone_pair",
                "Likely body name, user data, bone, or attachment index metadata.",
            ),
            (
                0x28usize,
                "body_transform_header_pair",
                "Likely header before transform/orientation float block.",
            ),
            (
                0x50usize,
                "body_runtime_or_quality_pair",
                "Likely runtime quality/motion/activation metadata.",
            ),
            (
                0x60usize,
                "body_mass_or_inertia_header_pair",
                "Likely header near mass/inertia-related fields.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/body-cinfo",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Kept read-only until exact body schema is confirmed."),
                "experimental",
                false,
            ));
        }
    } else if type_name == "hknpConstraintCinfo" && payload.len() >= 8 {
        for (offset, name, description) in [
            (
                0x00usize,
                "body_a_reference_or_index_pair",
                "Likely first constrained body reference/index pair.",
            ),
            (
                0x08usize,
                "body_b_reference_or_index_pair",
                "Likely second constrained body reference/index pair.",
            ),
            (
                0x10usize,
                "constraint_data_reference_pair",
                "Likely reference/index to hknpConstraintData or concrete constraint data.",
            ),
            (
                0x18usize,
                "constraint_priority_flags_pair",
                "Likely priority, collision, enable, or runtime flags.",
            ),
            (
                0x20usize,
                "constraint_user_data_or_metadata_pair",
                "Likely user data or constraint metadata pair.",
            ),
        ] {
            if offset + 8 > payload.len() {
                continue;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]/constraint-cinfo",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                &format!("{description} Constraint reference edits are not supported."),
                "experimental",
                false,
            ));
        }
    } else if matches!(type_name, "hknpPhysicsSceneData" | "hknpRagdollData") {
        for offset in (0..payload.len().min(128)).step_by(8) {
            if offset + 8 > payload.len() {
                break;
            }
            let low = le_u32(&payload[offset..offset + 4]).unwrap_or(0);
            let high = le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0);
            if low == 0 && high == 0 {
                continue;
            }
            let description = match type_name {
                "hknpConstraintCinfo" => {
                    "Possible body/constraint reference or flags pair. Structural reference edits are not supported."
                }
                "hknpPhysicsSceneData" => {
                    "Possible physics-system/body/constraint array reference or count pair."
                }
                "hknpRagdollData" => {
                    "Possible ragdoll body/constraint/skeleton array reference or count pair."
                }
                _ => "Unverified pair of 32-bit words.",
            };
            fields.push(layout_field(
                &format!("u32_pair_0x{offset:X}"),
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!("{low}, {high}"))),
                description,
                "experimental",
                false,
            ));
        }
    }
    if matches!(
        type_name,
        "hknpSharedMotionProperties"
            | "hknpPhysicsSystemData::ExtendedBodyCinfo"
            | "hknpRagdollConstraintData"
            | "hknpLimitedHingeConstraintData"
            | "hknpPositionConstraintMotor"
    ) && record.count > 0
    {
        let item_stride = if record.count > 0 {
            payload.len() / record.count as usize
        } else {
            payload.len()
        };
        for item_index in 0..(record.count as usize).min(64) {
            let item_base = item_index * item_stride;
            if item_base >= payload.len() {
                break;
            }
            for offset in (0..item_stride.min(512).saturating_sub(3)).step_by(4) {
                let absolute_offset = item_base + offset;
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
        }
    }
    if matches!(type_name, "hknpSphereShape" | "hknpCapsuleShape") && payload.len() >= 0x6C {
        let radius = le_f32(&payload[0x68..0x6C]);
        fields.push(layout_field(
            "radius",
            0x68,
            4,
            "float32",
            radius.map(LayoutValue::F32),
            if type_name == "hknpSphereShape" {
                "Observed sphere radius slot. Fixed-size edits are supported when the value remains finite and positive."
            } else {
                "Observed capsule radius slot. Fixed-size edits are supported when the value remains finite and positive."
            },
            "strong inference",
            true,
        ));
    }
    if type_name == "hknpMeshShape" && payload.len() >= 16 {
        fields.push(layout_field(
            "mesh_shape_header_words",
            0,
            payload.len().min(64),
            "uint32[]",
            Some(LayoutValue::Text(format!(
                "word_sample_count={}",
                payload.len().min(64) / 4
            ))),
            "Read-only hknpMeshShape object header sample. Mesh-shape section/primitive schema is still being recovered.",
            "experimental",
            false,
        ));
    }
    if type_name == "hknpMeshShape::GeometrySection" && payload.len() >= 32 {
        for (offset, name, description) in [
            (
                0usize,
                "aabb_tree_relative_offset",
                "Candidate byte offset from the geometry-section area to hknpAabb8TreeNode data.",
            ),
            (
                4usize,
                "aabb_tree_node_count",
                "Candidate count of quantized AABB tree nodes referenced by this section.",
            ),
            (
                8usize,
                "primitive_relative_offset",
                "Candidate byte offset to packed primitive/index tuples for this section.",
            ),
            (
                12usize,
                "primitive_count",
                "Candidate primitive tuple count for this section.",
            ),
            (
                16usize,
                "mesh_byte_buffer_relative_offset",
                "Candidate byte offset to a mesh byte/index buffer used by this section.",
            ),
            (
                20usize,
                "mesh_byte_buffer_size",
                "Candidate byte length for the first mesh byte/index buffer.",
            ),
            (
                24usize,
                "secondary_buffer_relative_offset",
                "Candidate byte offset to a secondary mesh buffer or range table.",
            ),
            (
                28usize,
                "secondary_buffer_count_or_size",
                "Candidate count or byte length for the secondary mesh buffer.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                4,
                "uint32",
                le_u32(&payload[offset..offset + 4]).map(LayoutValue::U32),
                description,
                "strong inference",
                false,
            ));
        }
        if payload.len() >= 56 {
            for (offset, name) in [
                (44usize, "quantization_or_scale_x"),
                (48usize, "quantization_or_scale_y"),
                (52usize, "quantization_or_scale_z"),
            ] {
                fields.push(layout_field(
                    name,
                    offset,
                    4,
                    "float32",
                    le_f32(&payload[offset..offset + 4]).map(LayoutValue::F32),
                    "Candidate float scale/quantization field for mesh bounds or AABB decoding.",
                    "experimental",
                    false,
                ));
            }
        }
    }
    if type_name == "hknpMeshShape::GeometrySection::Primitive" && !payload.is_empty() {
        let tuple_count = (payload.len() / 4).min(record.count as usize).min(128);
        let mut min_index: Option<u8> = None;
        let mut max_index: Option<u8> = None;
        let mut quad_count = 0usize;
        let mut triangle_count = 0usize;
        for tuple_index in 0..tuple_count {
            let base = tuple_index * 4;
            let tuple = &payload[base..base + 4];
            let active = tuple
                .iter()
                .copied()
                .filter(|value| *value != 0xFF)
                .collect::<Vec<_>>();
            if active.len() == 3 {
                triangle_count += 1;
            } else if active.len() == 4 {
                quad_count += 1;
            }
            for value in active {
                min_index = Some(min_index.map_or(value, |current| current.min(value)));
                max_index = Some(max_index.map_or(value, |current| current.max(value)));
            }
            if tuple_index < 32 {
                fields.push(layout_field(
                    &format!("primitive_tuple[{tuple_index}]"),
                    base,
                    4,
                    "uint8[4]",
                    Some(LayoutValue::Text(format!(
                        "{}, {}, {}, {}",
                        tuple[0], tuple[1], tuple[2], tuple[3]
                    ))),
                    "Read-only four-byte primitive tuple candidate. Values behave like compact vertex/primitive indices in sampled Crimson Desert mesh HKX files.",
                    "experimental",
                    false,
                ));
            }
        }
        fields.push(layout_field(
            "primitive_tuple_summary",
            0,
            tuple_count * 4,
            "summary",
            Some(LayoutValue::Text(format!(
                "tuples={tuple_count}; index_range={}..{}; quads={quad_count}; triangles={triangle_count}",
                min_index.map(|value| value.to_string()).unwrap_or_else(|| "?".to_string()),
                max_index.map(|value| value.to_string()).unwrap_or_else(|| "?".to_string())
            ))),
            "Read-only topology candidate summary. Primitive edits remain blocked until shape tags and AABB/tree rebuild rules are recovered.",
            "experimental",
            false,
        ));
    }
    if type_name == "hknpAabb8TreeNode" && payload.len() >= 32 {
        let tuple_count = (payload.len() / 32).min(record.count as usize).min(64);
        fields.push(layout_field(
            "aabb8_candidate_node_summary",
            0,
            tuple_count * 32,
            "summary",
            Some(LayoutValue::Text(format!(
                "candidate_stride=32; decoded_nodes={tuple_count}; declared_count={}",
                record.count
            ))),
            "Read-only hknpAabb8TreeNode candidate segmentation. Bytes appear to contain quantized bounds and child/primitive links.",
            "experimental",
            false,
        ));
    }
    if type_name == "hknpConvexShape" && payload.len() >= 0x68 {
        for (offset, name, description) in [
            (
                0x30,
                "vertices_offset_count",
                "Observed pair; count often matches decoded vertex count.",
            ),
            (
                0x40,
                "planes_offset_count",
                "Observed pair; count often matches decoded hull plane count.",
            ),
            (
                0x48,
                "faces_offset_count",
                "Observed pair; count often matches decoded face count.",
            ),
            (
                0x50,
                "face_indices_offset_count",
                "Observed pair; count often matches face-index byte count.",
            ),
            (
                0x58,
                "edge_table_a_offset_count",
                "Observed pair; likely convex edge/support metadata.",
            ),
            (
                0x60,
                "edge_table_b_offset_count",
                "Observed pair; likely convex edge/support metadata.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                "uint32[2]",
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                description,
                "strong inference",
                false,
            ));
        }
    }
    if type_name == "hknpBoxShape" && payload.len() >= 0x6C {
        for (offset, name, description) in [
            (
                0x30,
                "shape_property_or_material_index",
                "Observed hknpBoxShape word. In Crimson Desert samples this often looks like a small property/material index.",
            ),
            (
                0x38,
                "box_vertices_offset_count",
                "Likely offset/count pair for the eight box corner vertices or equivalent local box point table.",
            ),
            (
                0x40,
                "box_planes_offset_count",
                "Likely offset/count pair for the six box plane equations.",
            ),
            (
                0x48,
                "box_faces_offset_count",
                "Likely offset/count pair for the six box face records.",
            ),
            (
                0x50,
                "box_face_indices_offset_count",
                "Likely offset/count pair for the fixed box face-index byte buffer.",
            ),
            (
                0x58,
                "box_edge_table_a_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
            (
                0x60,
                "box_edge_table_b_offset_count",
                "Likely offset/count pair for box edge/support metadata.",
            ),
        ] {
            fields.push(layout_field(
                name,
                offset,
                8,
                if offset == 0x30 { "uint32[2]/index" } else { "uint32[2]" },
                Some(LayoutValue::Text(format!(
                    "{}, {}",
                    le_u32(&payload[offset..offset + 4]).unwrap_or(0),
                    le_u32(&payload[offset + 4..offset + 8]).unwrap_or(0)
                ))),
                description,
                if offset >= 0x38 { "strong inference" } else { "experimental" },
                false,
            ));
        }
        for (offset, name, description) in [
            (
                0x68,
                "convex_radius_or_collision_margin",
                "Likely box convex radius/collision margin. Kept read-only until the exact hknpBoxShape field role is confirmed.",
            ),
            (
                0x6C,
                "aabb_or_radius_factor",
                "Likely AABB expansion/radius factor for the box shape. Kept read-only until confirmed across more samples.",
            ),
        ] {
            if offset + 4 <= payload.len() {
                fields.push(layout_field(
                    name,
                    offset,
                    4,
                    "float32",
                    le_f32(&payload[offset..offset + 4]).map(LayoutValue::F32),
                    description,
                    "strong inference",
                    false,
                ));
            }
        }
        if payload.len() >= 0xC0 {
            for row_index in 0..4usize {
                let row_offset = 0x80 + row_index * 16;
                let row = (0..4usize)
                    .map(|component| {
                        le_f32(&payload[row_offset + component * 4..row_offset + component * 4 + 4])
                            .unwrap_or(0.0)
                    })
                    .map(|value| format!("{value:.6}"))
                    .collect::<Vec<_>>()
                    .join(", ");
                fields.push(layout_field(
                    &format!("box_local_frame_or_extent_row[{row_index}]"),
                    row_offset,
                    16,
                    "float32[4]",
                    Some(LayoutValue::Text(row)),
                    "Likely local box frame, center, extent, or packed transform row. Included for comparison between samples; not safe for GUI editing yet.",
                    "experimental",
                    false,
                ));
            }
            fields.push(layout_field(
                "box_local_frame_or_extents",
                0x80,
                0x40,
                "float32[4][4]",
                Some(LayoutValue::Text("4 rows".to_string())),
                "Four-row hknpBoxShape float block observed in real Crimson Desert samples. This is likely where local orientation/center/extents live, but exact field names need more sample correlation before edits are enabled.",
                "experimental",
                false,
            ));
        }
    }
    if type_name == "hknpBoxShape" && payload.len() >= 32 {
        let words = (0..payload.len().min(64) / 4)
            .map(|word_index| le_u32(&payload[word_index * 4..word_index * 4 + 4]).unwrap_or(0))
            .map(|word| format!("0x{word:08X}"))
            .collect::<Vec<_>>()
            .join(" ");
        fields.push(layout_field(
            "box_shape_payload_sample",
            0,
            payload.len().min(128),
            "float32[]/uint32[]",
            Some(LayoutValue::Text(words)),
            "Read-only hknpBoxShape payload sample. Box half-extents/orientation fields are not fully named yet.",
            "experimental",
            false,
        ));
    }
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
    fields
}

pub fn parse_object_records(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
) -> Vec<ObjectRecord> {
    let spans = item_record_spans(data, items, records);
    let mut objects = Vec::new();
    for record in records {
        let Some((_index, start, end)) = spans
            .iter()
            .find(|(index, _, _)| *index == record.index)
            .copied()
        else {
            continue;
        };
        let payload = &data[start..end];
        let fields = decode_layout_fields(payload, record);
        let references = possible_reference_candidates(payload, records, record, 64);
        let editable = fields.iter().any(|field| field.editable);
        let status = if editable {
            "editable"
        } else if fields.iter().any(|field| field.confidence != "raw") || !references.is_empty() {
            "partially_decoded"
        } else {
            "raw_preserved"
        };
        objects.push(ObjectRecord {
            record_index: record.index,
            type_index: record.type_index,
            type_name: record.type_name.clone(),
            count: record.count,
            data_offset: record.data_offset,
            absolute_data_offset: record.absolute_data_offset,
            byte_length: end - start,
            stride: if record.count > 0 {
                Some((end - start) as f32 / record.count as f32)
            } else {
                None
            },
            status: status.to_string(),
            fields,
            references,
            raw_hex_prefix: payload_hex_prefix(payload, 64),
        });
    }
    objects
}

fn fixed_float_group_category(type_name: &str) -> Option<&'static str> {
    match type_name {
        "hknpPositionConstraintMotor" => Some("motor_force_response"),
        "hknpSharedMotionProperties" => Some("motion_damping_solver"),
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => Some("body_transform_mass"),
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            Some("joint_limits_strength")
        }
        _ => None,
    }
}

fn fixed_float_group_description(type_name: &str) -> &'static str {
    match type_name {
        "hknpPositionConstraintMotor" => {
            "Editable fixed-size motor float slots. Likely affects constraint force limits, recovery strength, and damping."
        }
        "hknpSharedMotionProperties" => {
            "Editable fixed-size shared motion-property float slots. Likely affects damping, solver response, and velocity thresholds."
        }
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            "Editable fixed-size body construction float slots. Likely includes transform, mass/inertia, and solver-related values."
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            "Editable fixed-size constraint float slots. Likely includes strength/tau, joint frames, limits, friction, and damping-like values."
        }
        _ => "Editable fixed-size physics float slots.",
    }
}

fn fixed_float_slot_name(type_name: &str, offset: usize) -> String {
    fn vector_component_slot_name(prefix: &str, start_offset: usize, offset: usize) -> String {
        let components = ["x", "y", "z", "w"];
        let relative = offset.saturating_sub(start_offset);
        let row_index = relative / 16;
        let component_index = (relative % 16) / 4;
        let component = components.get(component_index).copied().unwrap_or("n");
        format!("{prefix}_row{row_index}_{component}")
    }
    match type_name {
        "hknpPositionConstraintMotor" => match offset {
            0x20 => "min_force".to_string(),
            0x24 => "max_force".to_string(),
            0x28 => "stiffness_or_strength".to_string(),
            0x2C => "damping_or_tau".to_string(),
            0x30 => "recovery_or_proportional_response".to_string(),
            0x34 => "scale_or_enable_factor".to_string(),
            _ => format!("motor_float_0x{offset:X}"),
        },
        "hknpSharedMotionProperties" => match offset {
            0x04 => "motion_scale".to_string(),
            0x10 => "damping_or_solver_a".to_string(),
            0x14 => "damping_or_solver_b".to_string(),
            0x18 => "gravity_or_response_factor".to_string(),
            0x28 => "velocity_or_damping_limit_x".to_string(),
            0x2C => "velocity_or_damping_limit_y".to_string(),
            0x30 => "velocity_or_damping_limit_z".to_string(),
            0x34 => "velocity_or_damping_limit_w".to_string(),
            0x38 => "solver_tolerance_a".to_string(),
            0x3C => "solver_tolerance_b".to_string(),
            0x40 => "threshold".to_string(),
            0x44 => "solver_or_damping_a".to_string(),
            0x48 => "solver_or_damping_b".to_string(),
            _ => format!("motion_float_0x{offset:X}"),
        },
        "hknpMaterial" => match offset {
            0x00 => "material_friction_or_filter_a".to_string(),
            0x04 => "material_friction_or_restitution".to_string(),
            0x08 => "material_restitution_or_surface_response".to_string(),
            0x0C => "material_filter_or_flags".to_string(),
            0x10 => "material_user_data_or_property_a".to_string(),
            0x14 => "material_user_data_or_property_b".to_string(),
            0x18 => "material_surface_response_a".to_string(),
            0x1C => "material_surface_response_b".to_string(),
            0x20 => "material_surface_response_c".to_string(),
            0x30 => "material_property_scalar".to_string(),
            _ => format!("material_float_0x{offset:X}"),
        },
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            if (0x30..=0x4C).contains(&offset) {
                return vector_component_slot_name("body_transform_or_orientation", 0x30, offset);
            }
            match offset {
                0x70 => "mass_or_inertia_value".to_string(),
                0x88 => "solver_mass_or_inertia_tuning_a".to_string(),
                0x8C => "solver_mass_or_inertia_tuning_b".to_string(),
                0x98 => "body_scale_or_activation_factor".to_string(),
                _ => format!("body_float_0x{offset:X}"),
            }
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            if offset == 0x18 {
                return "constraint_strength_or_tau".to_string();
            }
            if (0x40..0x80).contains(&offset) {
                return vector_component_slot_name("joint_frame_a", 0x40, offset);
            }
            if (0x80..0xA0).contains(&offset) {
                return vector_component_slot_name("joint_frame_b", 0x80, offset);
            }
            if (0xA0..0xC0).contains(&offset) {
                return vector_component_slot_name("angular_limit_or_axis", 0xA0, offset);
            }
            if (0xC0..=0x160).contains(&offset) {
                return vector_component_slot_name(
                    "constraint_friction_motor_or_damping",
                    0xC0,
                    offset,
                );
            }
            format!("constraint_float_0x{offset:X}")
        }
        _ => format!("float_0x{offset:X}"),
    }
}

fn fixed_float_slot_description(type_name: &str, offset: usize) -> String {
    match type_name {
        "hknpPositionConstraintMotor" => match offset {
            0x20 => "Likely minimum motor force limit.".to_string(),
            0x24 => "Likely maximum motor force limit.".to_string(),
            0x28 => "Likely motor stiffness/strength value.".to_string(),
            0x2C => "Likely damping or tau response value.".to_string(),
            0x30 => "Likely recovery/proportional response value.".to_string(),
            0x34 => "Likely scale or enable factor.".to_string(),
            _ => "Unverified hknpPositionConstraintMotor float slot.".to_string(),
        },
        "hknpSharedMotionProperties" => {
            "Likely shared motion damping, solver, gravity, or velocity threshold value."
                .to_string()
        }
        "hknpMaterial" => match offset {
            0x00 | 0x04 | 0x08 | 0x18 | 0x1C | 0x20 => {
                "Likely material friction, restitution, or surface response scalar. Read-only until fixed-edit proof confirms the exact member role.".to_string()
            }
            0x0C | 0x10 | 0x14 | 0x30 => {
                "Likely material filter, flag, or property scalar. Read-only until member semantics are confirmed.".to_string()
            }
            _ => "Unverified hknpMaterial scalar slot.".to_string(),
        },
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => {
            if (0x30..=0x4C).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x30);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!(
                    "Likely body transform/orientation vector block row {row}, component {component}. This may be a local body frame, position, or quaternion-like value."
                )
            } else {
                "Likely body mass, inertia, solver, activation, or scale value.".to_string()
            }
        }
        "hknpRagdollConstraintData" | "hknpLimitedHingeConstraintData" => {
            if offset == 0x18 {
                "Likely constraint tau/strength-like value, often around 100.".to_string()
            } else if (0x40..0x80).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x40);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely joint frame A vector row {row}, component {component}.")
            } else if (0x80..0xA0).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0x80);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely joint frame B vector row {row}, component {component}.")
            } else if (0xA0..0xC0).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0xA0);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!(
                    "Likely angular limit or limit-axis vector row {row}, component {component}."
                )
            } else if (0xC0..=0x160).contains(&offset) {
                let components = ["x", "y", "z", "w"];
                let relative = offset.saturating_sub(0xC0);
                let row = relative / 16;
                let component = components.get((relative % 16) / 4).copied().unwrap_or("n");
                format!("Likely constraint friction, motor, or damping vector row {row}, component {component}.")
            } else {
                format!("Unverified {type_name} float slot.")
            }
        }
        _ => format!("Unverified {type_name} float slot."),
    }
}

fn fixed_float_slot_confidence(type_name: &str, offset: usize) -> &'static str {
    if type_name == "hknpPositionConstraintMotor" && matches!(offset, 0x20 | 0x24) {
        "strong inference"
    } else if type_name == "hknpMaterial"
        && matches!(offset, 0x00 | 0x04 | 0x08 | 0x18 | 0x1C | 0x20)
    {
        "experimental"
    } else {
        "experimental"
    }
}

pub fn parse_physics_tuning_groups(
    data: &[u8],
    items: &[TagItem],
    records: &[ItemRecord],
) -> Vec<PhysicsTuningGroup> {
    let spans = item_record_spans(data, items, records);
    let mut groups = Vec::new();
    for record in records {
        let Some(category) = fixed_float_group_category(&record.type_name) else {
            continue;
        };
        if record.count == 0 {
            continue;
        }
        let Some((_index, start, end)) = spans
            .iter()
            .find(|(index, _, _)| *index == record.index)
            .copied()
        else {
            continue;
        };
        let byte_length = end.saturating_sub(start);
        let stride = byte_length / record.count as usize;
        if stride == 0 {
            continue;
        }
        let payload = &data[start..end];
        let mut slots = Vec::new();
        for item_index in 0..record.count as usize {
            let base = item_index * stride;
            for offset in (0..stride.min(512).saturating_sub(3)).step_by(4) {
                let absolute = base + offset;
                if absolute + 4 > payload.len() {
                    continue;
                }
                let Some(value) = le_f32(&payload[absolute..absolute + 4]) else {
                    continue;
                };
                if !value.is_finite() || value.abs() < 1e-8 || value.abs() > 1_000_000.0 {
                    continue;
                }
                slots.push(FixedFloatSlot {
                    item_index,
                    offset,
                    name: fixed_float_slot_name(&record.type_name, offset),
                    value,
                    description: fixed_float_slot_description(&record.type_name, offset),
                    confidence: fixed_float_slot_confidence(&record.type_name, offset).to_string(),
                });
            }
        }
        if slots.is_empty() {
            continue;
        }
        groups.push(PhysicsTuningGroup {
            category: category.to_string(),
            label: format!("{} record {}", record.type_name, record.index),
            type_name: record.type_name.clone(),
            record_index: record.index,
            count: record.count,
            byte_length,
            stride,
            description: fixed_float_group_description(&record.type_name).to_string(),
            confidence: "experimental".to_string(),
            edit_rule: "edit_value_only_keep_record_item_and_offset".to_string(),
            slots,
        });
    }
    groups
}

fn item_record_by_index(records: &[ItemRecord], record_index: usize) -> Option<&ItemRecord> {
    records.iter().find(|record| record.index == record_index)
}

fn record_string_value(data: &[u8], records: &[ItemRecord], record_index: usize) -> Option<String> {
    let record = item_record_by_index(records, record_index)?;
    if record.type_name != "char" && record.type_name != "hkStringPtr" {
        return None;
    }
    let start = record.absolute_data_offset?;
    if start >= data.len() {
        return None;
    }
    let max_len = if record.type_name == "char" && record.count > 0 {
        record.count as usize
    } else {
        records
            .iter()
            .filter_map(|candidate| candidate.absolute_data_offset)
            .filter(|offset| *offset > start)
            .min()
            .unwrap_or(data.len())
            .saturating_sub(start)
    };
    let end = start.saturating_add(max_len).min(data.len());
    let raw = &data[start..end];
    let nul_end = raw.iter().position(|byte| *byte == 0).unwrap_or(raw.len());
    if nul_end == 0 {
        return None;
    }
    let text = String::from_utf8_lossy(&raw[..nul_end]).trim().to_string();
    (!text.is_empty()).then_some(text)
}

fn owner_array_element_type(owner_type: &str, field_name: &str, target_type: &str) -> String {
    match (owner_type, field_name) {
        ("hkRootLevelContainer", "namedVariants") => {
            "hkRootLevelContainer::NamedVariant".to_string()
        }
        ("hknpPhysicsSystemData", "materials") => "hknpMaterial".to_string(),
        ("hknpPhysicsSystemData", "motionProperties") => "hknpSharedMotionProperties".to_string(),
        ("hknpPhysicsSystemData", "bodyCinfos") => {
            "hknpPhysicsSystemData::ExtendedBodyCinfo".to_string()
        }
        ("hknpPhysicsSystemData", "constraintCinfos") => "hknpConstraintCinfo".to_string(),
        ("hknpPhysicsSystemData", "shapeReferences") => "hkRefPtr<hknpShape>".to_string(),
        ("hknpPhysicsSceneData", _) => "hknpPhysicsSystemData".to_string(),
        ("hknpRagdollData", _) => "hknpConstraintCinfo".to_string(),
        ("hknpConvexShape", "vertices") | ("hknpBoxShape", "vertices") => "hkFloat3".to_string(),
        ("hknpConvexShape", "planes") | ("hknpBoxShape", "planes") => "hkVector4".to_string(),
        ("hknpConvexShape", "faces") | ("hknpBoxShape", "faces") => {
            "hknpConvexHull::Face".to_string()
        }
        ("hknpConvexShape", "faceIndices") | ("hknpBoxShape", "faceIndices") => {
            "hkUint8".to_string()
        }
        ("hknpCompoundShape", "shapeInstances") => "hknpShapeInstance".to_string(),
        ("hknpCompoundShape", "simdTreeNodes") => "hkcdSimdTreeNamespace::Node".to_string(),
        ("hknpCompoundShape", "shapeProperties") => "hknpShapeProperties::Entry".to_string(),
        ("hkSkeleton", "bones") => "hkBone".to_string(),
        ("hkSkeleton", "parentIndices") => "hkInt16".to_string(),
        ("hkSkeleton", "referencePose") => "hkQsTransform".to_string(),
        ("hkaSkeletonMapper", "mappingData") => "hkaSkeletonMapperData::SimpleMapping".to_string(),
        _ if !target_type.is_empty() => target_type.to_string(),
        _ => "void".to_string(),
    }
}

fn owner_array_type(owner_type: &str, field_name: &str, target_type: &str) -> String {
    let element_type = owner_array_element_type(owner_type, field_name, target_type);
    format!("hkArray<{element_type}>")
}

fn read_owner_array_count(
    data: &[u8],
    owner: &ItemRecord,
    owner_local_offset: usize,
    target: &ItemRecord,
) -> Option<u32> {
    let absolute = owner
        .absolute_data_offset?
        .saturating_add(owner_local_offset);
    if absolute.saturating_add(12) <= data.len() {
        if let Some(size) = le_u32(&data[absolute + 8..absolute + 12]) {
            if size <= 1_000_000 {
                return Some(size);
            }
        }
    }
    (target.count > 0).then_some(target.count)
}

fn graph_class_priority(type_name: &str) -> u8 {
    match type_name {
        "hkRootLevelContainer" => 0,
        "hkRootLevelContainer::NamedVariant" => 1,
        "hknpPhysicsSceneData" => 2,
        "hknpPhysicsSystemData" | "hknpRagdollData" => 3,
        "hknpPhysicsSystemData::ExtendedBodyCinfo" => 4,
        "hknpConstraintCinfo" => 5,
        name if name.contains("ConstraintData") => 6,
        name if name.contains("Shape") => 7,
        "hknpMaterial" | "hknpSharedMotionProperties" => 8,
        "hkSkeleton" | "hkaAnimationContainer" | "hkaSkeletonMapper" => 9,
        _ => 32,
    }
}

fn build_graph_order(
    records: &[ItemRecord],
    edges: &[NativeGraphEdge],
    root_record_index: Option<usize>,
) -> Vec<usize> {
    let mut ordered = Vec::<usize>::new();
    let mut queue = Vec::<usize>::new();
    if let Some(root) = root_record_index {
        queue.push(root);
    }
    while let Some(record_index) = queue.pop() {
        if ordered.contains(&record_index) {
            continue;
        }
        ordered.push(record_index);
        let mut children = edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(record_index))
            .filter_map(|edge| edge.target_record_index)
            .filter(|target| !ordered.contains(target) && !queue.contains(target))
            .collect::<Vec<_>>();
        children.sort_unstable();
        for child in children.into_iter().rev() {
            queue.push(child);
        }
    }
    let mut remaining = records
        .iter()
        .filter(|record| !ordered.contains(&record.index))
        .collect::<Vec<_>>();
    remaining.sort_by_key(|record| {
        (
            graph_class_priority(&record.type_name),
            record.data_offset,
            record.index,
        )
    });
    ordered.extend(remaining.into_iter().map(|record| record.index));
    ordered
}

fn native_root_info(
    data: &[u8],
    records: &[ItemRecord],
    edges: &[NativeGraphEdge],
) -> NativeRootInfo {
    let named_variant_records = records
        .iter()
        .filter(|record| record.type_name == "hkRootLevelContainer::NamedVariant")
        .map(|record| record.index)
        .collect::<Vec<_>>();
    let mut named_variants = Vec::new();
    for variant_record_index in named_variant_records {
        let mut name = None;
        let mut class_name = None;
        let mut object_record_index = None;
        for edge in edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(variant_record_index))
        {
            match edge.owner_field_name.as_deref() {
                Some("name") => {
                    name = edge
                        .target_record_index
                        .and_then(|target| record_string_value(data, records, target));
                }
                Some("className") => {
                    class_name = edge
                        .target_record_index
                        .and_then(|target| record_string_value(data, records, target));
                }
                Some("variant") => {
                    object_record_index = edge.target_record_index;
                }
                _ => {}
            }
        }
        let object_type_name = object_record_index
            .and_then(|index| item_record_by_index(records, index))
            .map(|record| record.type_name.clone());
        named_variants.push(NativeNamedVariant {
            variant_record_index,
            name,
            class_name,
            object_record_index,
            object_type_name,
            confidence: if object_record_index.is_some() {
                "strong inference".to_string()
            } else {
                "experimental".to_string()
            },
        });
    }
    if let Some(root) = records
        .iter()
        .find(|record| record.type_name == "hkRootLevelContainer")
    {
        return NativeRootInfo {
            record_index: Some(root.index),
            type_name: Some(root.type_name.clone()),
            method: "native_hkRootLevelContainer".to_string(),
            confidence: "strong inference".to_string(),
            named_variant_count: named_variants.len(),
            named_variants,
        };
    }
    if let Some(variant_target) = named_variants
        .iter()
        .find_map(|variant| variant.object_record_index)
    {
        let root_record = item_record_by_index(records, variant_target);
        return NativeRootInfo {
            record_index: Some(variant_target),
            type_name: root_record.map(|record| record.type_name.clone()),
            method: "native_named_variant_target".to_string(),
            confidence: "strong inference".to_string(),
            named_variant_count: named_variants.len(),
            named_variants,
        };
    }
    let preferred = [
        "hknpPhysicsSceneData",
        "hknpPhysicsSystemData",
        "hknpRagdollData",
        "hkaAnimationContainer",
        "hkSkeleton",
    ];
    for class_name in preferred {
        if let Some(record) = records.iter().find(|record| record.type_name == class_name) {
            return NativeRootInfo {
                record_index: Some(record.index),
                type_name: Some(record.type_name.clone()),
                method: "native_preferred_root_class".to_string(),
                confidence: "strong inference".to_string(),
                named_variant_count: named_variants.len(),
                named_variants,
            };
        }
    }
    let first = records.first();
    NativeRootInfo {
        record_index: first.map(|record| record.index),
        type_name: first.map(|record| record.type_name.clone()),
        method: if first.is_some() {
            "native_first_record_fallback".to_string()
        } else {
            "not_recovered".to_string()
        },
        confidence: if first.is_some() {
            "experimental".to_string()
        } else {
            "none".to_string()
        },
        named_variant_count: named_variants.len(),
        named_variants,
    }
}

fn add_native_graph_edge(
    edges: &mut Vec<NativeGraphEdge>,
    seen: &mut Vec<(usize, Option<usize>, Option<usize>, String)>,
    edge: NativeGraphEdge,
) {
    let key = (
        edge.source_record_index.unwrap_or(usize::MAX),
        edge.target_record_index,
        edge.owner_local_offset,
        edge.resolution_source.clone(),
    );
    if seen.contains(&key) {
        return;
    }
    seen.push(key);
    edges.push(edge);
}

fn build_native_model_graph(
    data: &[u8],
    records: &[ItemRecord],
    objects: &[ObjectRecord],
    fixups: &TagfileFixupSummary,
) -> NativeModelGraph {
    if records.is_empty() {
        return NativeModelGraph {
            format: "cd_hkx_native_model_graph_v1".to_string(),
            status: "not_recovered".to_string(),
            imported: false,
            node_count: 0,
            edge_count: 0,
            fixup_backed_reference_edge_count: 0,
            inferred_reference_edge_count: 0,
            owner_array_count: 0,
            root: NativeRootInfo {
                record_index: None,
                type_name: None,
                method: "not_recovered".to_string(),
                confidence: "none".to_string(),
                named_variant_count: 0,
                named_variants: Vec::new(),
            },
            graph_order: Vec::new(),
            nodes: Vec::new(),
            edges: Vec::new(),
            owner_arrays: Vec::new(),
        };
    }

    let mut edges = Vec::<NativeGraphEdge>::new();
    let mut seen_edges = Vec::<(usize, Option<usize>, Option<usize>, String)>::new();
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            for site in &table.patch_sites {
                let Some(owner_record_index) = site.owner_record_index else {
                    continue;
                };
                let Some(owner) = item_record_by_index(records, owner_record_index) else {
                    continue;
                };
                let local_offset = site.owner_local_offset.unwrap_or(0);
                let (field_name, field_category) =
                    object_reference_owner_field(&owner.type_name, local_offset)
                        .map(|(name, category)| (Some(name.to_string()), category.to_string()))
                        .unwrap_or((None, site.reference_category.clone()));
                let target = site
                    .target_record_index
                    .and_then(|index| item_record_by_index(records, index));
                let relation = field_name
                    .clone()
                    .unwrap_or_else(|| "fixup_reference".to_string());
                add_native_graph_edge(
                    &mut edges,
                    &mut seen_edges,
                    NativeGraphEdge {
                        source: format!("record:{owner_record_index}"),
                        target: site
                            .target_record_index
                            .map(|index| format!("record:{index}"))
                            .unwrap_or_else(|| "null".to_string()),
                        relation,
                        source_record_index: Some(owner_record_index),
                        target_record_index: site.target_record_index,
                        owner_field_name: field_name,
                        owner_local_offset: site.owner_local_offset,
                        reference_category: if site.target_status == "null" {
                            "null_reference".to_string()
                        } else {
                            field_category
                        },
                        resolution_source: "ptch".to_string(),
                        confidence: if target.is_some() || site.target_status == "null" {
                            "strong inference".to_string()
                        } else {
                            "experimental".to_string()
                        },
                    },
                );
            }
        }
    }
    let ptch_owner_offsets = edges
        .iter()
        .filter(|edge| edge.resolution_source == "ptch")
        .filter_map(|edge| Some((edge.source_record_index?, edge.owner_local_offset?)))
        .collect::<Vec<_>>();
    for object in objects {
        let Some(owner) = item_record_by_index(records, object.record_index) else {
            continue;
        };
        for reference in &object.references {
            if ptch_owner_offsets.contains(&(object.record_index, reference.offset)) {
                continue;
            }
            add_native_graph_edge(
                &mut edges,
                &mut seen_edges,
                NativeGraphEdge {
                    source: format!("record:{}", object.record_index),
                    target: format!("record:{}", reference.target_record_index),
                    relation: reference
                        .owner_field_name
                        .clone()
                        .unwrap_or_else(|| reference.reference_kind.clone()),
                    source_record_index: Some(object.record_index),
                    target_record_index: Some(reference.target_record_index),
                    owner_field_name: reference.owner_field_name.clone(),
                    owner_local_offset: Some(reference.offset),
                    reference_category: reference.reference_category.clone(),
                    resolution_source: "inferred_offset".to_string(),
                    confidence: if owner.type_name.is_empty() {
                        "experimental".to_string()
                    } else {
                        "strong inference".to_string()
                    },
                },
            );
        }
    }

    let mut owner_arrays = Vec::<NativeOwnerArray>::new();
    let mut seen_arrays = Vec::<(usize, usize, usize)>::new();
    for edge in &edges {
        if edge.reference_category != "array_data_reference" {
            continue;
        }
        let (Some(owner_record_index), Some(target_record_index), Some(owner_local_offset)) = (
            edge.source_record_index,
            edge.target_record_index,
            edge.owner_local_offset,
        ) else {
            continue;
        };
        let key = (owner_record_index, target_record_index, owner_local_offset);
        if seen_arrays.contains(&key) {
            continue;
        }
        let Some(owner) = item_record_by_index(records, owner_record_index) else {
            continue;
        };
        let Some(target) = item_record_by_index(records, target_record_index) else {
            continue;
        };
        let field_name = edge
            .owner_field_name
            .clone()
            .unwrap_or_else(|| "data".to_string());
        let element_type =
            owner_array_element_type(&owner.type_name, &field_name, &target.type_name);
        seen_arrays.push(key);
        owner_arrays.push(NativeOwnerArray {
            owner_record_index,
            owner_type_name: owner.type_name.clone(),
            field_name: field_name.clone(),
            target_record_index,
            target_type_name: target.type_name.clone(),
            array_type: owner_array_type(&owner.type_name, &field_name, &target.type_name),
            element_type,
            numelements: read_owner_array_count(data, owner, owner_local_offset, target),
            owner_local_offset,
            resolution_source: edge.resolution_source.clone(),
            confidence: edge.confidence.clone(),
        });
    }

    let root = native_root_info(data, records, &edges);
    let graph_order = build_graph_order(records, &edges, root.record_index);
    let order_by_record = graph_order
        .iter()
        .enumerate()
        .map(|(order, record_index)| (*record_index, order))
        .collect::<BTreeMap<_, _>>();
    let nodes = records
        .iter()
        .map(|record| NativeGraphNode {
            id: format!("record:{}", record.index),
            kind: "item_record".to_string(),
            label: format!("{}: {}", record.index, record.type_name),
            record_index: Some(record.index),
            type_index: Some(record.type_index),
            type_name: Some(record.type_name.clone()),
            data_offset: Some(record.data_offset),
            count: Some(record.count),
            graph_order: order_by_record
                .get(&record.index)
                .copied()
                .unwrap_or(record.index),
        })
        .collect::<Vec<_>>();
    let fixup_backed_reference_edge_count = edges
        .iter()
        .filter(|edge| edge.resolution_source == "ptch" && edge.target_record_index.is_some())
        .count();
    let inferred_reference_edge_count = edges
        .iter()
        .filter(|edge| edge.resolution_source == "inferred_offset")
        .count();
    let status = if !edges.is_empty() {
        "native_model_graph_partial"
    } else {
        "native_object_nodes_only"
    };
    NativeModelGraph {
        format: "cd_hkx_native_model_graph_v1".to_string(),
        status: status.to_string(),
        imported: false,
        node_count: nodes.len(),
        edge_count: edges.len(),
        fixup_backed_reference_edge_count,
        inferred_reference_edge_count,
        owner_array_count: owner_arrays.len(),
        root,
        graph_order,
        nodes,
        edges,
        owner_arrays,
    }
}

fn push_unique_limited(values: &mut Vec<String>, value: &str, limit: usize) {
    if values.len() >= limit || value.is_empty() || values.iter().any(|item| item == value) {
        return;
    }
    values.push(value.to_string());
}

fn push_unique_usize_limited(values: &mut Vec<usize>, value: usize, limit: usize) {
    if values.len() >= limit || values.contains(&value) {
        return;
    }
    values.push(value);
}

fn hard_internal_target_specs() -> Vec<(&'static str, &'static str, &'static str)> {
    vec![
        (
            "hknp_mesh_primitive_bit_layout",
            "hknpMeshShape primitive bit layout",
            "Packed primitive tuple bytes, triangle/quad detection, winding, shape-key bits, and section/material ownership.",
        ),
        (
            "hknp_mesh_aabb_tree",
            "hknpMeshShape AABB tree node encoding",
            "Quantized AABB tree nodes, child/leaf flags, primitive ranges, and section-local node ownership.",
        ),
        (
            "hknp_mesh_shape_tags",
            "hknpMeshShape shape tag ranges/tables",
            "Shape tag table/range ownership, per-primitive tag lookup, and material/filter linkage.",
        ),
        (
            "compound_child_transforms",
            "compound child transforms",
            "Compound shape child instances, local transforms, child shape references, tree nodes, and property ownership.",
        ),
        (
            "compressed_mass_properties",
            "compressed mass properties",
            "hknpShapeMassProperties, hkCompressedMassProperties, hkPackedVector3 scale/offset, inertia, center, and mass factors.",
        ),
        (
            "material_property_entries",
            "material/property/free-list entries",
            "hknpMaterial fields, hknpShapeProperties::Entry, hkFreeListArrayElement rows, ids, flags, and game material mapping.",
        ),
        (
            "skeleton_animation_containers",
            "skeleton/animation containers",
            "hkSkeleton, bones, parent indices, reference pose, hkaAnimationContainer, skeleton mappers, clips, and binding references.",
        ),
    ]
}

fn hard_internal_target_blockers(key: &str) -> Vec<String> {
    match key {
        "hknp_mesh_primitive_bit_layout" => vec![
            "primitive tuple bit roles are still inferred from byte patterns".to_string(),
            "shape keys/material ownership are not proven".to_string(),
            "only same-index-set winding/order edits are safe".to_string(),
        ],
        "hknp_mesh_aabb_tree" => vec![
            "quantized bounds scale/offset ownership is not proven".to_string(),
            "child/leaf flags and primitive-range linkage need corpus proof".to_string(),
            "AABB nodes cannot be rebuilt safely yet".to_string(),
        ],
        "hknp_mesh_shape_tags" => vec![
            "shape tag ranges and table ownership are not proven".to_string(),
            "per-primitive tag resolution needs mesh-heavy corpus samples".to_string(),
            "tag/material/filter linkage is read-only".to_string(),
        ],
        "compound_child_transforms" => vec![
            "shape-instance transform layout is still experimental".to_string(),
            "child shape refs need fixup-backed ownership across samples".to_string(),
            "compound tree/property rebuild rules are unknown".to_string(),
        ],
        "compressed_mass_properties" => vec![
            "compressed vector scale/offset ownership is unknown".to_string(),
            "mass/inertia/center fields are not mapped to real Havok names".to_string(),
            "compressed mass payload rebuild is blocked".to_string(),
        ],
        "material_property_entries" => vec![
            "material friction/restitution/filter fields are not confirmed".to_string(),
            "free-list entry semantics and allocation state are unknown".to_string(),
            "game material id/name linkage needs descriptor/corpus correlation".to_string(),
        ],
        "skeleton_animation_containers" => vec![
            "animation clip/container arrays are not fully owner-typed".to_string(),
            "mapper row transform/index semantics need paired skeleton corpus proof".to_string(),
            "skeleton/animation reference ownership is read-only".to_string(),
        ],
        _ => Vec::new(),
    }
}

fn hard_internal_target_keys_for_type(type_name: &str) -> Vec<&'static str> {
    let mut keys = Vec::new();
    match type_name {
        "hknpMeshShape" | "hknpMeshShape::GeometrySection" => {
            keys.push("hknp_mesh_primitive_bit_layout");
            keys.push("hknp_mesh_aabb_tree");
            keys.push("hknp_mesh_shape_tags");
        }
        "hknpMeshShape::GeometrySection::Primitive" => {
            keys.push("hknp_mesh_primitive_bit_layout");
        }
        "hknpAabb8TreeNode" | "hkcdSimdTreeNamespace::Node" => {
            keys.push("hknp_mesh_aabb_tree");
        }
        "hknpMeshShape::ShapeTagTableEntry" => {
            keys.push("hknp_mesh_shape_tags");
        }
        "hknpCompoundShape" | "hknpShapeInstance" => {
            keys.push("compound_child_transforms");
        }
        "hknpShapeMassProperties" | "hkCompressedMassProperties" | "hkPackedVector3" => {
            keys.push("compressed_mass_properties");
        }
        "hknpMaterial" | "hknpShapeProperties::Entry" => {
            keys.push("material_property_entries");
        }
        "hkSkeleton"
        | "hkBone"
        | "hkInt16"
        | "hkQsTransform"
        | "hkaSkeletonMapper"
        | "hkaSkeletonMapperData::SimpleMapping"
        | "hkaAnimationContainer" => {
            keys.push("skeleton_animation_containers");
        }
        _ => {}
    }
    if type_name.starts_with("hkFreeListArrayElement") {
        keys.push("material_property_entries");
    }
    keys
}

fn build_hard_internal_evidence(objects: &[ObjectRecord]) -> HardInternalEvidenceReport {
    let specs = hard_internal_target_specs();
    let mut targets = specs
        .iter()
        .map(|(key, label, description)| HardInternalEvidenceTarget {
            key: (*key).to_string(),
            label: (*label).to_string(),
            description: (*description).to_string(),
            status: "open_needs_corpus_sample".to_string(),
            proof_status: "needs_corpus_sample".to_string(),
            present_in_file: false,
            resolved: false,
            import_blocking: true,
            observed_record_count: 0,
            observed_byte_count: 0,
            observed_types: Vec::new(),
            observed_fields: Vec::new(),
            record_indices: Vec::new(),
            unresolved_blockers: hard_internal_target_blockers(key),
            confidence: "none".to_string(),
        })
        .collect::<Vec<_>>();

    for object in objects {
        let keys = hard_internal_target_keys_for_type(&object.type_name);
        if keys.is_empty() {
            continue;
        }
        for key in keys {
            let Some(target) = targets.iter_mut().find(|target| target.key == key) else {
                continue;
            };
            target.present_in_file = true;
            target.observed_record_count += 1;
            target.observed_byte_count += object.byte_length;
            push_unique_limited(&mut target.observed_types, &object.type_name, 24);
            push_unique_usize_limited(&mut target.record_indices, object.record_index, 48);
            for field in &object.fields {
                if field.confidence == "raw" {
                    continue;
                }
                push_unique_limited(&mut target.observed_fields, &field.name, 64);
                if matches!(field.confidence.as_str(), "confirmed" | "strong inference") {
                    target.confidence = "strong inference".to_string();
                } else if target.confidence == "none" {
                    target.confidence = "experimental".to_string();
                }
            }
            if target.confidence == "none" {
                target.confidence = "experimental".to_string();
            }
        }
    }

    for target in &mut targets {
        if target.present_in_file {
            target.status = "open_observed_unproven".to_string();
            target.proof_status = "needs_corpus_proof".to_string();
        }
    }

    let observed_target_count = targets
        .iter()
        .filter(|target| target.present_in_file)
        .count();
    let unresolved_target_count = targets.iter().filter(|target| !target.resolved).count();
    let total_observed_byte_count = targets
        .iter()
        .map(|target| target.observed_byte_count)
        .sum::<usize>();
    HardInternalEvidenceReport {
        format: "cd_hkx_hard_internal_evidence_v1".to_string(),
        status: if observed_target_count > 0 {
            "hard_internals_observed_unproven".to_string()
        } else {
            "hard_internals_need_corpus".to_string()
        },
        imported: false,
        target_count: targets.len(),
        observed_target_count,
        unresolved_target_count,
        total_observed_byte_count,
        targets,
    }
}

fn decoder_reference_semantic_from_parts(
    reference_category: &str,
    match_kind: &str,
    target_status: &str,
) -> &'static str {
    let category = reference_category.to_ascii_lowercase();
    let kind = match_kind.to_ascii_lowercase();
    let status = target_status.to_ascii_lowercase();
    if kind.contains("varuint")
        || kind.contains("packed")
        || category.contains("varuint")
        || category.contains("packed")
    {
        return "packed_or_varuint";
    }
    if status == "null" || kind == "null" || category == "null_reference" {
        return "null";
    }
    if status == "object" || category == "object_reference" {
        return "object";
    }
    if category == "array_data_reference"
        || category == "data_reference"
        || category == "data_reference_candidate"
    {
        return "data_candidate";
    }
    if category == "string_reference" {
        return "string_candidate";
    }
    if category == "type_reference" || category == "type_class_reference" {
        return "type_class";
    }
    if status == "unresolved"
        || category == "unresolved_fixup_word"
        || category == "unresolved"
        || kind == "unresolved_word"
    {
        return "unresolved";
    }
    "unresolved"
}

fn decoder_link_evidence_for_edge(edge: &NativeGraphEdge) -> &'static str {
    if edge.resolution_source == "ptch" {
        return "fixup_backed";
    }
    if edge.reference_category == "array_data_reference" {
        return "declared_owner_array";
    }
    if edge.resolution_source == "typed_layout" {
        return "typed_layout";
    }
    if edge.resolution_source == "inferred_offset" {
        return "inferred";
    }
    "raw_observation"
}

fn decoder_missing_requirements_for_type(type_name: &str, status: &str) -> Vec<String> {
    if type_name.starts_with("hkArray") {
        return vec![
            "owner-field array mapping".to_string(),
            "element template/class metadata".to_string(),
            "fixup-backed data pointer semantics".to_string(),
            "rebuild-safe count/capacity rules".to_string(),
        ];
    }
    if type_name.starts_with("hkRefPtr") || type_name.starts_with("hkRelPtr") {
        return vec![
            "PTCH/fixup-backed target classification".to_string(),
            "null/data/string/type reference distinction".to_string(),
            "target class member metadata".to_string(),
        ];
    }
    let hard_keys = hard_internal_target_keys_for_type(type_name);
    let mut requirements = Vec::<String>::new();
    for key in hard_keys {
        for blocker in hard_internal_target_blockers(key) {
            push_unique_limited(&mut requirements, &blocker, 12);
        }
    }
    if requirements.is_empty() && type_name.starts_with("hknp") {
        requirements.push("real hkClass member metadata".to_string());
        requirements.push("member flags/offsets/defaults".to_string());
        requirements.push("owner/reference semantics".to_string());
    }
    if requirements.is_empty() && (type_name.starts_with("hk") || type_name.starts_with("hka")) {
        requirements.push("real hkClass member metadata".to_string());
        requirements.push("template/owner array context".to_string());
    }
    if requirements.is_empty() && (status == "raw_preserved" || status == "raw") {
        requirements.push("typed payload decoder".to_string());
    }
    requirements
}

fn decoder_friendly_status_for_type(type_name: &str, status: &str) -> String {
    match type_name {
        "hknpMeshShape" | "hknpMeshShape::GeometrySection" => {
            "Readable, missing AABB/tree and primitive ownership semantics".to_string()
        }
        "hknpMeshShape::GeometrySection::Primitive" => {
            "Readable, missing primitive bit layout semantics".to_string()
        }
        "hknpMeshShape::ShapeTagTableEntry" => {
            "Readable, missing shape tag range semantics".to_string()
        }
        "hknpTriangleShape" => {
            "Readable, missing triangle material/shape-tag semantics".to_string()
        }
        "hknpCompoundShape" | "hknpShapeInstance" => {
            "Readable, missing compound child transform ownership".to_string()
        }
        "hknpMaterial" | "hknpShapeProperties::Entry" => {
            "Readable, missing material/property table semantics".to_string()
        }
        "hknpShapeMassProperties" | "hkCompressedMassProperties" | "hkPackedVector3" => {
            "Readable, missing compressed mass rules".to_string()
        }
        "hkSkeleton"
        | "hkBone"
        | "hkQsTransform"
        | "hkaSkeletonMapper"
        | "hkaSkeletonMapperData::SimpleMapping"
        | "hkaAnimationContainer" => {
            "Readable, missing skeleton/animation owner semantics".to_string()
        }
        _ if type_name.starts_with("hkArray") => {
            "Readable, missing owner array element type".to_string()
        }
        _ if type_name.starts_with("hkRefPtr") || type_name.starts_with("hkRelPtr") => {
            "Readable, missing reference target semantics".to_string()
        }
        _ if status == "raw_preserved" || status == "raw" => {
            "Raw preserved, decoder needed".to_string()
        }
        _ if status == "editable" => {
            "Fixed-size patch slots recovered; official hkClass names still partial".to_string()
        }
        _ => "Readable, not fully mapped".to_string(),
    }
}

fn build_decoder_evidence_v2(
    objects: &[ObjectRecord],
    fixups: &TagfileFixupSummary,
    fixup_semantics: &FixupSemanticsReport,
    graph: &NativeModelGraph,
) -> DecoderEvidenceV2 {
    let mut reference_semantic_counts = BTreeMap::<String, usize>::new();
    let mut detailed_reference_observations = 0usize;
    for section in &fixups.sections {
        for word in &section.words {
            if word.reference_category.is_empty() {
                continue;
            }
            detailed_reference_observations += 1;
            increment_count(
                &mut reference_semantic_counts,
                decoder_reference_semantic_from_parts(
                    &word.reference_category,
                    &word.match_kind,
                    "",
                ),
            );
        }
        for table in &section.ptch_tables {
            for site in &table.patch_sites {
                detailed_reference_observations += 1;
                increment_count(
                    &mut reference_semantic_counts,
                    decoder_reference_semantic_from_parts(
                        &site.reference_category,
                        "",
                        &site.target_status,
                    ),
                );
            }
        }
    }
    if detailed_reference_observations == 0 {
        for (category, count) in &fixups.reference_category_counts {
            increment_count_by(
                &mut reference_semantic_counts,
                decoder_reference_semantic_from_parts(category, "", ""),
                *count,
            );
        }
    }
    for case in &fixup_semantics.ptch_remaining_case_priorities {
        if case.case_name.contains("varuint") || case.case_name.contains("packed") {
            increment_count_by(
                &mut reference_semantic_counts,
                "packed_or_varuint",
                case.count,
            );
        } else if case.case_name.contains("unresolved") {
            increment_count_by(&mut reference_semantic_counts, "unresolved", case.count);
        }
    }

    let mut link_evidence_counts = BTreeMap::<String, usize>::new();
    let mut class_link_evidence = BTreeMap::<String, Vec<String>>::new();
    let mut record_type = BTreeMap::<usize, String>::new();
    for object in objects {
        record_type.insert(object.record_index, object.type_name.clone());
    }
    let mut fixup_field_counts = BTreeMap::<(String, String, String), (usize, String)>::new();
    for edge in &graph.edges {
        let evidence = decoder_link_evidence_for_edge(edge);
        increment_count(&mut link_evidence_counts, evidence);
        for record_index in [edge.source_record_index, edge.target_record_index]
            .iter()
            .flatten()
        {
            if let Some(type_name) = record_type.get(record_index) {
                class_link_evidence.entry(type_name.clone()).or_default();
                let values = class_link_evidence.get_mut(type_name).unwrap();
                push_unique_limited(values, evidence, 8);
            }
        }
        if edge.resolution_source == "ptch" {
            if let Some(source_record_index) = edge.source_record_index {
                if let Some(class_name) = record_type.get(&source_record_index) {
                    let field_name = edge
                        .owner_field_name
                        .clone()
                        .unwrap_or_else(|| edge.relation.clone());
                    let key = (
                        class_name.clone(),
                        field_name,
                        edge.reference_category.clone(),
                    );
                    let entry = fixup_field_counts
                        .entry(key)
                        .or_insert_with(|| (0, edge.confidence.clone()));
                    entry.0 += 1;
                    if entry.1 == "experimental" && edge.confidence != "experimental" {
                        entry.1 = edge.confidence.clone();
                    }
                }
            }
        }
    }
    if !graph.owner_arrays.is_empty() {
        increment_count_by(
            &mut link_evidence_counts,
            "declared_owner_array",
            graph.owner_arrays.len(),
        );
        for array in &graph.owner_arrays {
            let values = class_link_evidence
                .entry(array.owner_type_name.clone())
                .or_default();
            push_unique_limited(values, "declared_owner_array", 8);
        }
    }

    let mut class_rows = BTreeMap::<String, DecoderEvidenceClassStatus>::new();
    for object in objects {
        let row = class_rows
            .entry(object.type_name.clone())
            .or_insert_with(|| DecoderEvidenceClassStatus {
                type_name: object.type_name.clone(),
                record_count: 0,
                byte_count: 0,
                decoded_field_count: 0,
                reference_count: 0,
                editable_field_count: 0,
                status: object.status.clone(),
                friendly_status: String::new(),
                missing_requirements: Vec::new(),
                link_evidence: Vec::new(),
                corpus_priority_score: 0,
                read_only: true,
            });
        row.record_count += 1;
        row.byte_count += object.byte_length;
        row.decoded_field_count += object
            .fields
            .iter()
            .filter(|field| field.confidence != "raw")
            .count();
        row.editable_field_count += object.fields.iter().filter(|field| field.editable).count();
        row.reference_count += object.references.len();
        if row.status != "raw_preserved" && object.status == "raw_preserved" {
            row.status = object.status.clone();
        } else if row.status == "editable" && object.status != "editable" {
            row.status = object.status.clone();
        }
    }
    let mut class_statuses = class_rows.into_values().collect::<Vec<_>>();
    let mut total_partial_byte_count = 0usize;
    for row in &mut class_statuses {
        row.missing_requirements =
            decoder_missing_requirements_for_type(&row.type_name, &row.status);
        row.friendly_status = decoder_friendly_status_for_type(&row.type_name, &row.status);
        row.link_evidence = class_link_evidence
            .remove(&row.type_name)
            .unwrap_or_default();
        let partial_weight = if matches!(
            row.status.as_str(),
            "partially_decoded" | "raw_preserved" | "raw"
        ) {
            row.byte_count
        } else {
            row.byte_count / 4
        };
        total_partial_byte_count += partial_weight;
        row.corpus_priority_score = partial_weight
            + row.reference_count.saturating_mul(64)
            + row.missing_requirements.len().saturating_mul(256)
            + row.record_count.saturating_mul(128);
    }
    class_statuses.sort_by(|left, right| {
        right
            .corpus_priority_score
            .cmp(&left.corpus_priority_score)
            .then_with(|| left.type_name.cmp(&right.type_name))
    });

    let mut fixup_backed_fields = fixup_field_counts
        .into_iter()
        .map(
            |((class_name, field_name, reference_category), (count, confidence))| {
                DecoderEvidenceFixupBackedField {
                    class_name,
                    field_name,
                    reference_category,
                    count,
                    confidence,
                }
            },
        )
        .collect::<Vec<_>>();
    fixup_backed_fields.sort_by(|left, right| {
        right
            .count
            .cmp(&left.count)
            .then_with(|| left.class_name.cmp(&right.class_name))
            .then_with(|| left.field_name.cmp(&right.field_name))
    });

    let unresolved_or_packed_case_count = reference_semantic_counts
        .get("unresolved")
        .copied()
        .unwrap_or(0)
        + reference_semantic_counts
            .get("packed_or_varuint")
            .copied()
            .unwrap_or(0);
    let priority_class_count = class_statuses
        .iter()
        .filter(|row| !row.missing_requirements.is_empty())
        .count();
    DecoderEvidenceV2 {
        format: "cd_hkx_decoder_evidence_v2".to_string(),
        status: if objects.is_empty() {
            "no_object_records".to_string()
        } else {
            "read_only_native_evidence".to_string()
        },
        imported: false,
        read_only: true,
        class_status_count: class_statuses.len(),
        priority_class_count,
        total_partial_byte_count,
        unresolved_or_packed_case_count,
        owner_array_count: graph.owner_array_count,
        reference_semantic_counts,
        link_evidence_counts,
        class_statuses,
        fixup_backed_fields,
    }
}

fn object_type_contains(objects: &[ObjectRecord], needles: &[&str]) -> usize {
    objects
        .iter()
        .filter(|object| {
            needles
                .iter()
                .any(|needle| object.type_name.contains(needle))
        })
        .count()
}

fn editable_field_count_for_types(objects: &[ObjectRecord], needles: &[&str]) -> usize {
    objects
        .iter()
        .filter(|object| {
            needles
                .iter()
                .any(|needle| object.type_name.contains(needle))
        })
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum()
}

fn tuning_slot_count_for_categories(groups: &[PhysicsTuningGroup], categories: &[&str]) -> usize {
    groups
        .iter()
        .filter(|group| {
            categories
                .iter()
                .any(|category| group.category == *category)
        })
        .map(|group| group.slots.len())
        .sum()
}

fn tuning_group_count_for_categories(groups: &[PhysicsTuningGroup], categories: &[&str]) -> usize {
    groups
        .iter()
        .filter(|group| {
            categories
                .iter()
                .any(|category| group.category == *category)
        })
        .count()
}

fn modding_task_group(
    key: &str,
    label: &str,
    patchable_slot_count: usize,
    context_record_count: usize,
    evidence: Vec<String>,
    risk: &str,
    description: &str,
) -> HkxModdingTaskGroup {
    let readiness_label = if patchable_slot_count > 0 {
        "Patchable tuning"
    } else if context_record_count > 0 {
        "Read-only decoded"
    } else {
        "No recovered rows"
    };
    HkxModdingTaskGroup {
        key: key.to_string(),
        label: label.to_string(),
        readiness_label: readiness_label.to_string(),
        patchable_slot_count,
        context_record_count,
        evidence,
        risk: risk.to_string(),
        import_safe: patchable_slot_count > 0,
        description: description.to_string(),
    }
}

fn build_hkx_modding_readiness(
    objects: &[ObjectRecord],
    graph: &NativeModelGraph,
    hard_internal_evidence: &HardInternalEvidenceReport,
    real_hkclass_metadata: &RealHkClassMetadataReport,
    decoder_evidence: &DecoderEvidenceV2,
    physics_tuning_groups: &[PhysicsTuningGroup],
) -> HkxModdingReadiness {
    let decoded_object_count = objects
        .iter()
        .filter(|object| object.status != "raw_preserved" && object.status != "raw")
        .count();
    let native_editable_field_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let tuning_slot_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let patchable_slot_count = native_editable_field_count + tuning_slot_count;

    let mut readiness_labels = Vec::<String>::new();
    if patchable_slot_count > 0 {
        readiness_labels.push("Patchable tuning".to_string());
    }
    if decoded_object_count > 0 || !decoder_evidence.class_statuses.is_empty() {
        readiness_labels.push("Read-only decoded".to_string());
    }
    if decoder_evidence.priority_class_count > 0
        || hard_internal_evidence.unresolved_target_count > 0
        || !real_hkclass_metadata.unresolved_requirements.is_empty()
        || graph.edge_count > graph.fixup_backed_reference_edge_count
    {
        readiness_labels.push("Needs semantic rebuild".to_string());
    }
    if objects.is_empty() && physics_tuning_groups.is_empty() {
        readiness_labels.push("Unsupported structure".to_string());
    }
    if readiness_labels.is_empty() {
        readiness_labels.push("Read-only decoded".to_string());
    }

    let per_file_label = if patchable_slot_count > 0 {
        "Patchable tuning"
    } else if decoded_object_count > 0 {
        "Read-only decoded"
    } else if objects.is_empty() {
        "Unsupported structure"
    } else {
        "Needs semantic rebuild"
    }
    .to_string();
    let status = if patchable_slot_count > 0 {
        "fixed_size_patchable"
    } else if decoded_object_count > 0 {
        "read_only_decoded"
    } else {
        "unsupported_structure"
    };

    let task_groups = vec![
        modding_task_group(
            "collision_size",
            "Collision size",
            editable_field_count_for_types(
                objects,
                &[
                    "hknpConvexShape",
                    "hknpBoxShape",
                    "hknpSphereShape",
                    "hknpCapsuleShape",
                    "hknpTriangleShape",
                ],
            ),
            object_type_contains(
                objects,
                &[
                    "hknpConvexShape",
                    "hknpBoxShape",
                    "hknpSphereShape",
                    "hknpCapsuleShape",
                    "hknpTriangleShape",
                    "hknpMeshShape",
                    "hknpCompoundShape",
                    "hknpShapeInstance",
                ],
            ),
            vec!["typed_layout".to_string(), "raw_observation".to_string()],
            "Low when patchable",
            "Collision shape radius, extents, endpoints, and decoded geometry context.",
        ),
        modding_task_group(
            "body_transform",
            "Body transform",
            tuning_slot_count_for_categories(physics_tuning_groups, &["body_transform_mass"])
                + editable_field_count_for_types(objects, &["ExtendedBodyCinfo"]),
            tuning_group_count_for_categories(physics_tuning_groups, &["body_transform_mass"])
                + object_type_contains(objects, &["ExtendedBodyCinfo"]),
            vec!["typed_layout".to_string(), "native_tuning_slots".to_string()],
            "High",
            "Body frames, transform-like rows, mass/inertia-like rows, and solver body setup.",
        ),
        modding_task_group(
            "damping_motion",
            "Damping / motion",
            tuning_slot_count_for_categories(physics_tuning_groups, &["motion_damping_solver"]),
            tuning_group_count_for_categories(physics_tuning_groups, &["motion_damping_solver"])
                + object_type_contains(objects, &["hknpSharedMotionProperties"]),
            vec!["native_tuning_slots".to_string(), "typed_layout".to_string()],
            "Medium",
            "Shared motion-property rows that can affect damping, response, and motion thresholds.",
        ),
        modding_task_group(
            "joint_limits_strength",
            "Joint limits / strength",
            tuning_slot_count_for_categories(
                physics_tuning_groups,
                &["joint_limits_strength", "motor_force_response"],
            ),
            tuning_group_count_for_categories(
                physics_tuning_groups,
                &["joint_limits_strength", "motor_force_response"],
            ) + object_type_contains(
                objects,
                &[
                    "hknpConstraint",
                    "hknpRagdollConstraintData",
                    "hknpLimitedHingeConstraintData",
                    "hknpPositionConstraintMotor",
                ],
            ),
            vec![
                "native_tuning_slots".to_string(),
                "fixup_backed".to_string(),
                "owner_array".to_string(),
            ],
            "Medium to High",
            "Constraint frames, limits, motor force/response rows, strength, and damping-like values.",
        ),
        modding_task_group(
            "materials",
            "Materials",
            editable_field_count_for_types(objects, &["hknpMaterial", "hknpShapeProperties::Entry"]),
            object_type_contains(
                objects,
                &["hknpMaterial", "hknpShapeProperties::Entry", "hkFreeListArrayElement"],
            ),
            vec!["typed_layout".to_string(), "declared_owner_array".to_string()],
            "Context only",
            "Physics material and shape-property tables. Currently useful for browsing/linking, not broad editing.",
        ),
        modding_task_group(
            "skeleton_animation",
            "Skeleton / animation",
            editable_field_count_for_types(objects, &["hkSkeleton", "hkaAnimationContainer"]),
            object_type_contains(
                objects,
                &[
                    "hkSkeleton",
                    "hkBone",
                    "hkQsTransform",
                    "hkaAnimationContainer",
                    "hkaSkeletonMapper",
                ],
            ),
            vec!["typed_layout".to_string(), "raw_observation".to_string()],
            "Read-only",
            "Skeleton bones, transforms, animation containers, and mapper rows for browsing and relationship evidence.",
        ),
    ];

    HkxModdingReadiness {
        format: "cd_hkx_modding_readiness_v1".to_string(),
        status: status.to_string(),
        imported: false,
        read_only: true,
        per_file_label,
        readiness_labels,
        fixed_size_patch_importable: patchable_slot_count > 0,
        havok_xml_importable: false,
        new_editable_fields_enabled: false,
        decoded_object_count,
        patchable_slot_count,
        fixup_backed_reference_edge_count: graph.fixup_backed_reference_edge_count,
        owner_array_count: graph.owner_array_count,
        unresolved_or_packed_case_count: decoder_evidence.unresolved_or_packed_case_count,
        semantic_writer_gate: HkxSemanticWriterGate {
            status: "disabled_pending_semantic_rebuild".to_string(),
            mode: "fixed_size_patch_only".to_string(),
            enabled: false,
            raw_preserving_no_edit_writer_required: true,
            semantic_rebuild_supported: false,
            fixed_size_value_edits_allowed: true,
            allowed_edits: vec!["existing fixed-size CDMW patch rows".to_string()],
            blocked_edits: vec![
                "Havok XML import".to_string(),
                "array count edits".to_string(),
                "reference edits".to_string(),
                "string edits".to_string(),
                "mesh topology edits".to_string(),
                "semantic object graph rebuild".to_string(),
            ],
            requirements: vec![
                "byte-identical no-edit rebuild across representative corpus".to_string(),
                "fixup-backed object/data/string/type reference semantics".to_string(),
                "owner-array element typing".to_string(),
                "root/container/named-variant semantics".to_string(),
                "fixed-edit byte identity tests".to_string(),
            ],
        },
        task_groups,
    }
}

fn resolve_record_ref_value(raw: u64, records: &[ItemRecord]) -> Option<usize> {
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

fn read_record_ref_at(
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

fn read_u32_at(data: &[u8], absolute_offset: usize) -> Option<u32> {
    (absolute_offset.saturating_add(4) <= data.len())
        .then(|| le_u32(&data[absolute_offset..absolute_offset + 4]))
        .flatten()
}

fn read_u16_at(data: &[u8], absolute_offset: usize) -> Option<u16> {
    (absolute_offset.saturating_add(2) <= data.len())
        .then(|| le_u16(&data[absolute_offset..absolute_offset + 2]))
        .flatten()
}

fn read_u8_at(data: &[u8], absolute_offset: usize) -> Option<u8> {
    data.get(absolute_offset).copied()
}

fn record_span_end(data: &[u8], records: &[ItemRecord], record: &ItemRecord) -> Option<usize> {
    let start = record.absolute_data_offset?;
    records
        .iter()
        .filter_map(|candidate| candidate.absolute_data_offset)
        .filter(|offset| *offset > start)
        .min()
        .or(Some(data.len()))
}

fn record_item_stride(data: &[u8], records: &[ItemRecord], record: &ItemRecord) -> Option<usize> {
    if record.count == 0 {
        return None;
    }
    let start = record.absolute_data_offset?;
    let end = record_span_end(data, records, record)?;
    let byte_length = end.checked_sub(start)?;
    let stride = byte_length / record.count as usize;
    (stride > 0).then_some(stride)
}

fn hk_member_type_name(type_code: u8) -> &'static str {
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

fn hkclass_name_from_record(
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

fn decode_real_hkclass_enum(
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

fn decode_real_hkclass_member(
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

fn decode_real_hkclass_metadata(data: &[u8], records: &[ItemRecord]) -> RealHkClassMetadataReport {
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

fn detect_sdk_version(data: &[u8]) -> String {
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

fn build_no_edit_segments(data: &[u8], summary: &HkxSummary) -> Vec<HkxNoEditSegment> {
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

fn first_mismatch_offset(left: &[u8], right: &[u8]) -> Option<usize> {
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

fn json_escape(value: &str) -> String {
    let mut output = String::with_capacity(value.len() + 8);
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            c if c.is_control() => {
                let _ = write!(output, "\\u{:04x}", c as u32);
            }
            c => output.push(c),
        }
    }
    output
}

fn json_optional_u32(value: Option<u32>) -> String {
    value
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

fn json_optional_usize(value: Option<usize>) -> String {
    value
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

fn json_optional_f32(value: Option<f32>) -> String {
    value
        .filter(|item| item.is_finite())
        .map(|item| item.to_string())
        .unwrap_or_else(|| "null".to_string())
}

fn json_optional_string(value: Option<&str>) -> String {
    value
        .map(|item| format!("\"{}\"", json_escape(item)))
        .unwrap_or_else(|| "null".to_string())
}

fn json_bool(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

fn push_no_edit_binary_writer_report_json(out: &mut String, report: &NoEditBinaryWriterReport) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"native_writer_status\":\"{}\",\"no_edit_roundtrip_mode\":\"{}\",\"read_model_write_pipeline\":\"{}\",\"available\":{},\"native_read_model_write_available\":{},\"parsed_model_available\":{},\"byte_identical\":{},\"byte_identical_no_edit_rebuild_supported\":{},\"semantic_rebuild_supported\":{},\"havok_xml_import_unblocked\":{},\"input_byte_length\":{},\"output_byte_length\":{},\"parsed_raw_segment_count\":{},\"parsed_tag_item_count\":{},\"parsed_item_record_count\":{},\"parsed_object_record_count\":{},\"first_mismatch_offset\":{},\"validation_errors\":[",
        json_escape(&report.format),
        json_escape(&report.status),
        json_escape(&report.native_writer_status),
        json_escape(&report.no_edit_roundtrip_mode),
        json_escape(&report.read_model_write_pipeline),
        json_bool(report.available),
        json_bool(report.native_read_model_write_available),
        json_bool(report.parsed_model_available),
        json_bool(report.byte_identical),
        json_bool(report.byte_identical_no_edit_rebuild_supported),
        json_bool(report.semantic_rebuild_supported),
        json_bool(report.havok_xml_import_unblocked),
        report.input_byte_length,
        report.output_byte_length,
        report.parsed_raw_segment_count,
        report.parsed_tag_item_count,
        report.parsed_item_record_count,
        report.parsed_object_record_count,
        json_optional_usize(report.first_mismatch_offset)
    );
    for (index, error) in report.validation_errors.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(error));
    }
    out.push_str("]}");
}

pub fn no_edit_binary_writer_report_to_json(report: &NoEditBinaryWriterReport) -> String {
    let mut out = String::new();
    push_no_edit_binary_writer_report_json(&mut out, report);
    out
}

fn json_layout_value(value: &Option<LayoutValue>) -> String {
    match value {
        Some(LayoutValue::U32(item)) => item.to_string(),
        Some(LayoutValue::U64(item)) => item.to_string(),
        Some(LayoutValue::F32(item)) if item.is_finite() => item.to_string(),
        Some(LayoutValue::Text(item)) => format!("\"{}\"", json_escape(item)),
        _ => "null".to_string(),
    }
}

fn push_json_count_map(out: &mut String, map: &BTreeMap<String, usize>) {
    out.push('{');
    for (index, (key, value)) in map.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), value);
    }
    out.push('}');
}

fn push_fixup_word_json(out: &mut String, word: &TagfileFixupWord) {
    let _ = write!(
        out,
        "{{\"index\":{},\"offset\":{},\"hex_offset\":\"0x{:X}\",\"value\":{},\"value_hex\":\"0x{:X}\",\"match_kind\":\"{}\",\"reference_category\":\"{}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_data_offset\":{},\"target_absolute_offset\":{},\"target_string_index\":{},\"target_string\":{},\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patch_value\":{},\"confidence\":\"{}\"}}",
        word.index,
        word.offset,
        word.offset,
        word.value,
        word.value,
        json_escape(&word.match_kind),
        json_escape(&word.reference_category),
        json_optional_usize(word.target_record_index),
        json_optional_u32(word.target_type_index),
        json_optional_string(word.target_type_name.as_deref()),
        json_optional_u32(word.target_data_offset),
        json_optional_usize(word.target_absolute_offset),
        json_optional_usize(word.target_string_index),
        json_optional_string(word.target_string.as_deref()),
        json_optional_usize(word.owner_record_index),
        json_optional_u32(word.owner_type_index),
        json_optional_string(word.owner_type_name.as_deref()),
        json_optional_usize(word.owner_local_offset),
        word.patch_value
            .map(|item| item.to_string())
            .unwrap_or_else(|| "null".to_string()),
        json_escape(&word.confidence)
    );
}

fn push_ptch_patch_site_json(out: &mut String, site: &TagfilePtchPatchSite) {
    let _ = write!(
        out,
        "{{\"index\":{},\"ptch_word_index\":{},\"section_word_index\":{},\"section_word_offset\":{},\"patch_site_offset\":{},\"patch_site_hex_offset\":\"0x{:X}\",\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patch_value\":{},\"target_status\":\"{}\",\"reference_category\":\"{}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_data_offset\":{},\"target_absolute_offset\":{},\"confidence\":\"{}\"}}",
        site.index,
        site.ptch_word_index,
        json_optional_usize(site.section_word_index),
        json_optional_usize(site.section_word_offset),
        site.patch_site_offset,
        site.patch_site_offset,
        json_optional_usize(site.owner_record_index),
        json_optional_u32(site.owner_type_index),
        json_optional_string(site.owner_type_name.as_deref()),
        json_optional_usize(site.owner_local_offset),
        site.patch_value
            .map(|item| item.to_string())
            .unwrap_or_else(|| "null".to_string()),
        json_escape(&site.target_status),
        json_escape(&site.reference_category),
        json_optional_usize(site.target_record_index),
        json_optional_u32(site.target_type_index),
        json_optional_string(site.target_type_name.as_deref()),
        json_optional_u32(site.target_data_offset),
        json_optional_usize(site.target_absolute_offset),
        json_escape(&site.confidence)
    );
}

fn push_ptch_table_json(out: &mut String, table: &TagfilePtchTable) {
    let _ = write!(
        out,
        "{{\"offset\":{},\"hex_offset\":\"0x{:X}\",\"payload_offset\":{},\"payload_hex_offset\":\"0x{:X}\",\"payload_byte_length\":{},\"word_count\":{},\"header\":[{},{},{},{}],\"patch_site_count\":{},\"resolved_patch_site_count\":{},\"null_patch_site_count\":{},\"unresolved_patch_site_count\":{},\"confidence\":\"{}\",\"patch_sites\":[",
        table.offset,
        table.offset,
        table.payload_offset,
        table.payload_offset,
        table.payload_byte_length,
        table.word_count,
        table.header[0],
        table.header[1],
        table.header[2],
        table.header[3],
        table.patch_site_count,
        table.resolved_patch_site_count,
        table.null_patch_site_count,
        table.unresolved_patch_site_count,
        json_escape(&table.confidence)
    );
    for (index, site) in table.patch_sites.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        push_ptch_patch_site_json(out, site);
    }
    out.push_str("]}");
}

fn push_fixup_semantics_report_json(out: &mut String, report: &FixupSemanticsReport) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_object_patch_site_count\":{},\"ptch_null_patch_site_count\":{},\"ptch_unresolved_patch_site_count\":{},\"ptch_tuple_shape_counts\":",
        json_escape(&report.format),
        json_escape(&report.status),
        if report.imported { "true" } else { "false" },
        report.ptch_table_count,
        report.ptch_patch_site_count,
        report.ptch_object_patch_site_count,
        report.ptch_null_patch_site_count,
        report.ptch_unresolved_patch_site_count,
    );
    push_json_count_map(out, &report.ptch_tuple_shape_counts);
    out.push_str(",\"ptch_payload_match_kind_counts\":");
    push_json_count_map(out, &report.ptch_payload_match_kind_counts);
    out.push_str(",\"ptch_reference_category_counts\":");
    push_json_count_map(out, &report.ptch_reference_category_counts);
    out.push_str(",\"ptch_target_status_counts\":");
    push_json_count_map(out, &report.ptch_target_status_counts);
    out.push_str(",\"varuint_status_counts\":");
    push_json_count_map(out, &report.varuint_status_counts);
    out.push_str(",\"ptch_remaining_case_priorities\":[");
    for (index, case_row) in report.ptch_remaining_case_priorities.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"priority_rank\":{},\"case\":\"{}\",\"count\":{},\"description\":\"{}\"}}",
            case_row.priority_rank,
            json_escape(&case_row.case_name),
            case_row.count,
            json_escape(&case_row.description)
        );
    }
    out.push_str("],\"section_summaries\":[");
    for (index, section) in report.section_summaries.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"payload_byte_length\":{},\"word_count\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_patch_site_resolved_count\":{},\"ptch_patch_site_unresolved_count\":{},\"match_kind_counts\":",
            json_escape(&section.name),
            section.payload_byte_length,
            section.word_count,
            section.ptch_table_count,
            section.ptch_patch_site_count,
            section.ptch_patch_site_resolved_count,
            section.ptch_patch_site_unresolved_count
        );
        push_json_count_map(out, &section.match_kind_counts);
        out.push_str(",\"reference_category_counts\":");
        push_json_count_map(out, &section.reference_category_counts);
        out.push('}');
    }
    out.push_str("]}");
}

fn push_native_model_graph_json(out: &mut String, graph: &NativeModelGraph) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"node_count\":{},\"edge_count\":{},\"fixup_backed_reference_edge_count\":{},\"inferred_reference_edge_count\":{},\"owner_array_count\":{}",
        json_escape(&graph.format),
        json_escape(&graph.status),
        json_bool(graph.imported),
        graph.node_count,
        graph.edge_count,
        graph.fixup_backed_reference_edge_count,
        graph.inferred_reference_edge_count,
        graph.owner_array_count
    );
    out.push_str(",\"root\":");
    let root = &graph.root;
    let _ = write!(
        out,
        "{{\"record_index\":{},\"type_name\":{},\"method\":\"{}\",\"confidence\":\"{}\",\"named_variant_count\":{},\"named_variants\":[",
        json_optional_usize(root.record_index),
        json_optional_string(root.type_name.as_deref()),
        json_escape(&root.method),
        json_escape(&root.confidence),
        root.named_variant_count
    );
    for (index, variant) in root.named_variants.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"variant_record_index\":{},\"name\":{},\"class_name\":{},\"object_record_index\":{},\"object_type_name\":{},\"confidence\":\"{}\"}}",
            variant.variant_record_index,
            json_optional_string(variant.name.as_deref()),
            json_optional_string(variant.class_name.as_deref()),
            json_optional_usize(variant.object_record_index),
            json_optional_string(variant.object_type_name.as_deref()),
            json_escape(&variant.confidence)
        );
    }
    out.push_str("]}");
    out.push_str(",\"graph_order\":[");
    for (index, record_index) in graph.graph_order.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "{record_index}");
    }
    out.push_str("],\"nodes\":[");
    for (index, node) in graph.nodes.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"id\":\"{}\",\"kind\":\"{}\",\"label\":\"{}\",\"record_index\":{},\"type_index\":{},\"type_name\":{},\"data_offset\":{},\"count\":{},\"graph_order\":{}}}",
            json_escape(&node.id),
            json_escape(&node.kind),
            json_escape(&node.label),
            json_optional_usize(node.record_index),
            json_optional_u32(node.type_index),
            json_optional_string(node.type_name.as_deref()),
            json_optional_u32(node.data_offset),
            json_optional_u32(node.count),
            node.graph_order
        );
    }
    out.push_str("],\"edges\":[");
    for (index, edge) in graph.edges.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"source\":\"{}\",\"target\":\"{}\",\"relation\":\"{}\",\"source_record_index\":{},\"target_record_index\":{},\"owner_field_name\":{},\"owner_local_offset\":{},\"reference_category\":\"{}\",\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
            json_escape(&edge.source),
            json_escape(&edge.target),
            json_escape(&edge.relation),
            json_optional_usize(edge.source_record_index),
            json_optional_usize(edge.target_record_index),
            json_optional_string(edge.owner_field_name.as_deref()),
            json_optional_usize(edge.owner_local_offset),
            json_escape(&edge.reference_category),
            json_escape(&edge.resolution_source),
            json_escape(&edge.confidence)
        );
    }
    out.push_str("],\"owner_arrays\":[");
    for (index, array) in graph.owner_arrays.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"owner_record_index\":{},\"owner_type_name\":\"{}\",\"field_name\":\"{}\",\"target_record_index\":{},\"target_type_name\":\"{}\",\"array_type\":\"{}\",\"element_type\":\"{}\",\"numelements\":{},\"owner_local_offset\":{},\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
            array.owner_record_index,
            json_escape(&array.owner_type_name),
            json_escape(&array.field_name),
            array.target_record_index,
            json_escape(&array.target_type_name),
            json_escape(&array.array_type),
            json_escape(&array.element_type),
            json_optional_u32(array.numelements),
            array.owner_local_offset,
            json_escape(&array.resolution_source),
            json_escape(&array.confidence)
        );
    }
    out.push_str("]}");
}

fn push_hard_internal_evidence_json(out: &mut String, report: &HardInternalEvidenceReport) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"target_count\":{},\"observed_target_count\":{},\"unresolved_target_count\":{},\"total_observed_byte_count\":{},\"targets\":[",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        report.target_count,
        report.observed_target_count,
        report.unresolved_target_count,
        report.total_observed_byte_count
    );
    for (target_index, target) in report.targets.iter().enumerate() {
        if target_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"description\":\"{}\",\"status\":\"{}\",\"proof_status\":\"{}\",\"present_in_file\":{},\"resolved\":{},\"import_blocking\":{},\"observed_record_count\":{},\"observed_byte_count\":{},\"confidence\":\"{}\",\"observed_types\":[",
            json_escape(&target.key),
            json_escape(&target.label),
            json_escape(&target.description),
            json_escape(&target.status),
            json_escape(&target.proof_status),
            json_bool(target.present_in_file),
            json_bool(target.resolved),
            json_bool(target.import_blocking),
            target.observed_record_count,
            target.observed_byte_count,
            json_escape(&target.confidence)
        );
        for (index, type_name) in target.observed_types.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(type_name));
        }
        out.push_str("],\"observed_fields\":[");
        for (index, field_name) in target.observed_fields.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(field_name));
        }
        out.push_str("],\"record_indices\":[");
        for (index, record_index) in target.record_indices.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "{record_index}");
        }
        out.push_str("],\"unresolved_blockers\":[");
        for (index, blocker) in target.unresolved_blockers.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(blocker));
        }
        out.push_str("]}");
    }
    out.push_str("]}");
}

fn push_real_hkclass_metadata_json(out: &mut String, report: &RealHkClassMetadataReport) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"class_count\":{},\"member_count\":{},\"enum_count\":{},\"recovered_requirements\":",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        report.class_count,
        report.member_count,
        report.enum_count
    );
    out.push('{');
    for (index, (key, value)) in report.recovered_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
    }
    out.push_str("},\"unresolved_requirements\":[");
    for (index, key) in report.unresolved_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(key));
    }
    out.push_str("],\"classes\":[");
    for (class_index, class_info) in report.classes.iter().enumerate() {
        if class_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"record_index\":{},\"parent_record_index\":{},\"parent_name\":{},\"object_size\":{},\"version\":{},\"flags\":{},\"signature\":{},\"signature_hex\":{},\"defaults_record_index\":{},\"attributes_record_index\":{},\"declared_enum_count\":{},\"declared_member_count\":{},\"members_record_index\":{},\"enums_record_index\":{},\"confidence\":\"{}\",\"recovered_requirements\":",
            json_escape(&class_info.name),
            class_info.record_index,
            json_optional_usize(class_info.parent_record_index),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_u32(class_info.object_size),
            json_optional_u32(class_info.version),
            json_optional_u32(class_info.flags),
            json_optional_u32(class_info.signature),
            class_info
                .signature
                .map(|value| format!("\"0x{value:08X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_usize(class_info.defaults_record_index),
            json_optional_usize(class_info.attributes_record_index),
            class_info.declared_enum_count,
            class_info.declared_member_count,
            json_optional_usize(class_info.members_record_index),
            json_optional_usize(class_info.enums_record_index),
            json_escape(&class_info.confidence)
        );
        out.push('{');
        for (index, (key, value)) in class_info.recovered_requirements.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
        }
        out.push_str("},\"unresolved_requirements\":[");
        for (index, key) in class_info.unresolved_requirements.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(key));
        }
        out.push_str("],\"members\":[");
        for (member_index, member) in class_info.members.iter().enumerate() {
            if member_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_index\":{},\"type_code\":{},\"type_name\":\"{}\",\"subtype_code\":{},\"subtype_name\":\"{}\",\"c_array_size\":{},\"flags\":{},\"flags_hex\":\"0x{:X}\",\"offset\":{},\"offset_hex\":\"0x{:X}\",\"class_ref_record_index\":{},\"class_ref_name\":{},\"enum_ref_record_index\":{},\"enum_ref_name\":{},\"attributes_ref_record_index\":{},\"template_ref\":{},\"confidence\":\"{}\"}}",
                json_escape(&member.name),
                member.record_index,
                member.item_index,
                member.type_code,
                json_escape(&member.type_name),
                member.subtype_code,
                json_escape(&member.subtype_name),
                member.c_array_size,
                member.flags,
                member.flags,
                member.offset,
                member.offset,
                json_optional_usize(member.class_ref_record_index),
                json_optional_string(member.class_ref_name.as_deref()),
                json_optional_usize(member.enum_ref_record_index),
                json_optional_string(member.enum_ref_name.as_deref()),
                json_optional_usize(member.attributes_ref_record_index),
                json_optional_string(member.template_ref.as_deref()),
                json_escape(&member.confidence)
            );
        }
        out.push_str("],\"enums\":[");
        for (enum_index, enum_info) in class_info.enums.iter().enumerate() {
            if enum_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_count\":{},\"items_record_index\":{},\"flags\":{},\"confidence\":\"{}\"}}",
                json_escape(&enum_info.name),
                enum_info.record_index,
                enum_info.item_count,
                json_optional_usize(enum_info.items_record_index),
                json_optional_u32(enum_info.flags),
                json_escape(&enum_info.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("]}");
}

fn hkclass_member_array_status(member: &RealHkClassMemberMetadata) -> &'static str {
    if member.type_name.contains("Array")
        || member
            .template_ref
            .as_deref()
            .unwrap_or("")
            .contains("Array")
    {
        "array"
    } else if member.c_array_size > 0 {
        "fixed_c_array"
    } else {
        "not_array"
    }
}

fn hkclass_member_reference_status(member: &RealHkClassMemberMetadata) -> &'static str {
    if member.class_ref_record_index.is_some()
        || member.class_ref_name.is_some()
        || member.type_name.contains("Ref")
        || member.type_name.contains("Pointer")
        || member.template_ref.as_deref().unwrap_or("").contains("Ref")
    {
        "reference"
    } else {
        "not_reference"
    }
}

fn push_real_hkclass_metadata_v2_json(out: &mut String, report: &RealHkClassMetadataReport) {
    let status = if report.class_count > 0 {
        "real_metadata_available_read_only"
    } else {
        "real_metadata_not_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_real_hkclass_metadata_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"class_count\":{},\"member_count\":{},\"enum_count\":{},\"synthetic_fallback_required\":{}",
        status,
        json_escape(&report.format),
        json_bool(report.imported),
        report.class_count,
        report.member_count,
        report.enum_count,
        json_bool(report.class_count == 0)
    );
    out.push_str(",\"recovered_requirements\":");
    out.push('{');
    for (index, (key, value)) in report.recovered_requirements.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\":{}", json_escape(key), json_bool(*value));
    }
    out.push_str("},\"unresolved_requirements\":");
    push_json_string_array(out, &report.unresolved_requirements);
    out.push_str(",\"classes\":[");
    for (class_index, class_info) in report.classes.iter().enumerate() {
        if class_index > 0 {
            out.push(',');
        }
        let metadata_source =
            if class_info.members.is_empty() && class_info.declared_member_count > 0 {
                "real_class_header_members_unresolved"
            } else {
                "real_hkclass_metadata"
            };
        let template_parameter_count = class_info
            .members
            .iter()
            .filter(|member| member.template_ref.is_some())
            .count();
        let _ = write!(
            out,
            "{{\"class_name\":\"{}\",\"name\":\"{}\",\"record_index\":{},\"parent_record_index\":{},\"parent_name\":{},\"base_class\":{},\"object_size\":{},\"version\":{},\"flags\":{},\"flags_hex\":{},\"signature\":{},\"signature_hex\":{},\"defaults_record_index\":{},\"attributes_record_index\":{},\"declared_enum_count\":{},\"declared_member_count\":{},\"member_count\":{},\"enum_count\":{},\"template_parameter_count\":{},\"metadata_source\":\"{}\",\"confidence\":\"{}\"",
            json_escape(&class_info.name),
            json_escape(&class_info.name),
            class_info.record_index,
            json_optional_usize(class_info.parent_record_index),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_string(class_info.parent_name.as_deref()),
            json_optional_u32(class_info.object_size),
            json_optional_u32(class_info.version),
            json_optional_u32(class_info.flags),
            class_info
                .flags
                .map(|value| format!("\"0x{value:X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_u32(class_info.signature),
            class_info
                .signature
                .map(|value| format!("\"0x{value:08X}\""))
                .unwrap_or_else(|| "null".to_string()),
            json_optional_usize(class_info.defaults_record_index),
            json_optional_usize(class_info.attributes_record_index),
            class_info.declared_enum_count,
            class_info.declared_member_count,
            class_info.members.len(),
            class_info.enums.len(),
            template_parameter_count,
            metadata_source,
            json_escape(&class_info.confidence)
        );
        out.push_str(",\"unresolved_requirements\":");
        push_json_string_array(out, &class_info.unresolved_requirements);
        out.push_str(",\"members\":[");
        for (member_index, member) in class_info.members.iter().enumerate() {
            if member_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"member_name\":\"{}\",\"record_index\":{},\"item_index\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"byte_size\":{},\"havok_member_type_code\":{},\"member_type_code\":{},\"member_type_name\":\"{}\",\"subtype_code\":{},\"subtype_name\":\"{}\",\"subtype_template_target\":{},\"flags\":{},\"flags_hex\":\"0x{:X}\",\"c_array_size\":{},\"array_status\":\"{}\",\"reference_status\":\"{}\",\"class_ref_record_index\":{},\"class_ref_name\":{},\"enum_ref_record_index\":{},\"enum_ref_name\":{},\"attributes_ref_record_index\":{},\"template_ref\":{},\"confidence\":\"{}\",\"editable\":false,\"edit_policy\":\"read_only_metadata\"}}",
                json_escape(&member.name),
                json_escape(&member.name),
                member.record_index,
                member.item_index,
                member.offset,
                member.offset,
                member.c_array_size,
                member.type_code,
                member.type_code,
                json_escape(&member.type_name),
                member.subtype_code,
                json_escape(&member.subtype_name),
                json_optional_string(member.template_ref.as_deref()),
                member.flags,
                member.flags,
                member.c_array_size,
                hkclass_member_array_status(member),
                hkclass_member_reference_status(member),
                json_optional_usize(member.class_ref_record_index),
                json_optional_string(member.class_ref_name.as_deref()),
                json_optional_usize(member.enum_ref_record_index),
                json_optional_string(member.enum_ref_name.as_deref()),
                json_optional_usize(member.attributes_ref_record_index),
                json_optional_string(member.template_ref.as_deref()),
                json_escape(&member.confidence)
            );
        }
        out.push_str("],\"enums\":[");
        for (enum_index, enum_info) in class_info.enums.iter().enumerate() {
            if enum_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"record_index\":{},\"item_count\":{},\"items_record_index\":{},\"flags\":{},\"flags_hex\":{},\"confidence\":\"{}\"}}",
                json_escape(&enum_info.name),
                enum_info.record_index,
                enum_info.item_count,
                json_optional_usize(enum_info.items_record_index),
                json_optional_u32(enum_info.flags),
                enum_info
                    .flags
                    .map(|value| format!("\"0x{value:X}\""))
                    .unwrap_or_else(|| "null".to_string()),
                json_escape(&enum_info.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("],\"fallback_policy\":{\"synthetic_types_label\":\"recovered/synthetic\",\"havok_xml_importable\":false}}");
}

fn normalize_fixup_semantic_bucket(
    reference_category: &str,
    target_status: &str,
    match_kind: &str,
) -> &'static str {
    let category = reference_category.to_ascii_lowercase();
    let status = target_status.to_ascii_lowercase();
    let kind = match_kind.to_ascii_lowercase();
    if status.contains("null") || category.contains("null") {
        return "null_ref";
    }
    if category.contains("string") || kind.contains("string") {
        return "string_ref";
    }
    if category.contains("type")
        || category.contains("class")
        || kind.contains("type")
        || kind.contains("class")
    {
        return "type_class_ref";
    }
    if category.contains("section") || kind.contains("section") {
        return "section_local_ref";
    }
    if category.contains("data") || kind.contains("data") {
        return "data_ref";
    }
    if category.contains("packed")
        || category.contains("varuint")
        || kind.contains("packed")
        || kind.contains("varuint")
    {
        return "packed_or_varuint";
    }
    if status.contains("resolved") || category.contains("object") || kind.contains("object") {
        return "object_ref";
    }
    "unresolved"
}

fn push_fixup_semantics_v2_json(
    out: &mut String,
    fixups: &TagfileFixupSummary,
    report: &FixupSemanticsReport,
) {
    let mut bucket_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut tuple_shape_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut patch_site_total = 0usize;
    let mut patch_site_resolved = 0usize;
    let mut patch_site_unresolved = 0usize;
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            let tuple_shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            *tuple_shape_counts.entry(tuple_shape).or_insert(0) += table.patch_sites.len();
            for site in &table.patch_sites {
                patch_site_total += 1;
                if site.target_record_index.is_some() || site.target_status == "null" {
                    patch_site_resolved += 1;
                } else {
                    patch_site_unresolved += 1;
                }
                let bucket = normalize_fixup_semantic_bucket(
                    &site.reference_category,
                    &site.target_status,
                    "",
                );
                *bucket_counts.entry(bucket.to_string()).or_insert(0) += 1;
            }
        }
        for word in &section.resolved_references {
            let bucket = normalize_fixup_semantic_bucket(
                &word.reference_category,
                if word.target_record_index.is_some() {
                    "resolved"
                } else {
                    "unresolved"
                },
                &word.match_kind,
            );
            *bucket_counts.entry(bucket.to_string()).or_insert(0) += 1;
        }
    }
    for bucket in [
        "object_ref",
        "null_ref",
        "data_ref",
        "string_ref",
        "type_class_ref",
        "section_local_ref",
        "packed_or_varuint",
        "unresolved",
    ] {
        bucket_counts.entry(bucket.to_string()).or_insert(0);
    }
    let status = if patch_site_total > 0 {
        "ptch_patch_sites_normalized_read_only"
    } else if !report.ptch_reference_category_counts.is_empty() {
        "fixup_observations_normalized_read_only"
    } else {
        "no_fixup_semantics_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_fixup_semantics_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"patch_site_count\":{},\"resolved_patch_site_count\":{},\"unresolved_patch_site_count\":{}",
        status,
        json_escape(&report.format),
        json_bool(report.imported),
        patch_site_total,
        patch_site_resolved,
        patch_site_unresolved
    );
    out.push_str(",\"semantic_bucket_taxonomy\":[");
    for (index, (bucket, meaning, edit_policy)) in [
        (
            "object_ref",
            "Fixup points to another ITEM/object record.",
            "read_only_reference; edit blocked until semantic writer proof",
        ),
        (
            "null_ref",
            "Fixup represents a null reference slot.",
            "read_only_reference; null ref edits blocked",
        ),
        (
            "data_ref",
            "Fixup likely points to data/array storage rather than an object.",
            "corpus_proof_required",
        ),
        (
            "string_ref",
            "Fixup likely points to string storage/table data.",
            "corpus_proof_required",
        ),
        (
            "type_class_ref",
            "Fixup likely points to class/type metadata.",
            "corpus_proof_required",
        ),
        (
            "section_local_ref",
            "Fixup appears to use section-local indexing/addressing.",
            "corpus_proof_required",
        ),
        (
            "packed_or_varuint",
            "Fixup appears to use packed or variable-width index encoding.",
            "corpus_proof_required",
        ),
        (
            "unresolved",
            "Fixup could not be assigned a target or semantic bucket.",
            "decoder_work_required",
        ),
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"bucket\":\"{}\",\"meaning\":\"{}\",\"edit_policy\":\"{}\"}}",
            bucket,
            json_escape(meaning),
            edit_policy
        );
    }
    out.push(']');
    out.push_str(",\"semantic_bucket_counts\":");
    push_json_count_map(out, &bucket_counts);
    out.push_str(",\"tuple_shape_counts\":");
    push_json_count_map(out, &tuple_shape_counts);
    out.push_str(",\"source_tuple_shape_counts\":");
    push_json_count_map(out, &report.ptch_tuple_shape_counts);
    out.push_str(",\"source_payload_match_kind_counts\":");
    push_json_count_map(out, &report.ptch_payload_match_kind_counts);
    out.push_str(",\"source_reference_category_counts\":");
    push_json_count_map(out, &report.ptch_reference_category_counts);
    out.push_str(",\"patch_sites\":[");
    let mut emitted = 0usize;
    for section in &fixups.sections {
        for table in &section.ptch_tables {
            let tuple_shape = format!(
                "{},{},{},{}",
                table.header[0], table.header[1], table.header[2], table.header[3]
            );
            for site in &table.patch_sites {
                if emitted > 0 {
                    out.push(',');
                }
                emitted += 1;
                let bucket = normalize_fixup_semantic_bucket(
                    &site.reference_category,
                    &site.target_status,
                    "",
                );
                let _ = write!(
                    out,
                    "{{\"index\":{},\"section\":\"{}\",\"ptch_section_offset\":{},\"ptch_section_hex_offset\":\"0x{:X}\",\"tuple_shape\":\"{}\",\"owner_record_index\":{},\"owner_type_index\":{},\"owner_type_name\":{},\"owner_local_offset\":{},\"patched_slot_value\":{},\"patch_value\":{},\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":{},\"target_status\":\"{}\",\"semantic_bucket\":\"{}\",\"reference_category\":\"{}\",\"confidence\":\"{}\"}}",
                    site.index,
                    json_escape(&section.name),
                    table.offset,
                    table.offset,
                    tuple_shape,
                    json_optional_usize(site.owner_record_index),
                    json_optional_u32(site.owner_type_index),
                    json_optional_string(site.owner_type_name.as_deref()),
                    json_optional_usize(site.owner_local_offset),
                    site.patch_value
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "null".to_string()),
                    site.patch_value
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "null".to_string()),
                    json_optional_usize(site.target_record_index),
                    json_optional_u32(site.target_type_index),
                    json_optional_string(site.target_type_name.as_deref()),
                    json_escape(&site.target_status),
                    bucket,
                    json_escape(&site.reference_category),
                    json_escape(&site.confidence)
                );
            }
        }
    }
    out.push_str("],\"remaining_cases\":[");
    for (index, case_row) in report.ptch_remaining_case_priorities.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let bucket = normalize_fixup_semantic_bucket("", "unresolved", &case_row.case_name);
        let _ = write!(
            out,
            "{{\"priority_rank\":{},\"case\":\"{}\",\"semantic_bucket\":\"{}\",\"count\":{},\"description\":\"{}\"}}",
            case_row.priority_rank,
            json_escape(&case_row.case_name),
            bucket,
            case_row.count,
            json_escape(&case_row.description)
        );
    }
    out.push_str("],\"corpus_evidence_counters\":{");
    let mut emitted_counter = 0usize;
    for (name, value) in [
        ("patch_site_count", patch_site_total),
        ("resolved_patch_site_count", patch_site_resolved),
        ("unresolved_patch_site_count", patch_site_unresolved),
        (
            "unusual_tuple_shape_count",
            tuple_shape_counts
                .iter()
                .filter(|(shape, _)| shape.as_str() != "1,1,0,2")
                .count(),
        ),
        (
            "remaining_case_count",
            report.ptch_remaining_case_priorities.len(),
        ),
        (
            "data_ref_count",
            *bucket_counts.get("data_ref").unwrap_or(&0usize),
        ),
        (
            "string_ref_count",
            *bucket_counts.get("string_ref").unwrap_or(&0usize),
        ),
        (
            "type_class_ref_count",
            *bucket_counts.get("type_class_ref").unwrap_or(&0usize),
        ),
        (
            "section_local_ref_count",
            *bucket_counts.get("section_local_ref").unwrap_or(&0usize),
        ),
        (
            "packed_or_varuint_count",
            *bucket_counts.get("packed_or_varuint").unwrap_or(&0usize),
        ),
    ] {
        if emitted_counter > 0 {
            out.push(',');
        }
        emitted_counter += 1;
        let _ = write!(out, "\"{}\":{}", name, value);
    }
    out.push_str("},\"corpus_proof_targets\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"]}");
}

fn semantic_field_kind(field: &LayoutField) -> &'static str {
    let name = field.name.to_ascii_lowercase();
    let data_type = field.data_type.to_ascii_lowercase();
    if name.contains("string") || data_type.contains("string") {
        "string"
    } else if name.contains("ref") || data_type.contains("ref") {
        "ref"
    } else if name.contains("array")
        || data_type.contains("array")
        || field.description.contains("row")
    {
        "array"
    } else if data_type.contains("float3")
        || data_type.contains("float4")
        || data_type.contains("vector")
    {
        "vector"
    } else if data_type.contains("enum") {
        "enum"
    } else if data_type.contains("struct") {
        "struct"
    } else if data_type.contains("raw") || field.value.is_none() {
        "raw_span"
    } else {
        "scalar"
    }
}

fn push_semantic_model_v1_json(
    out: &mut String,
    objects: &[ObjectRecord],
    graph: &NativeModelGraph,
    metadata: &RealHkClassMetadataReport,
) {
    let mut real_class_names = BTreeMap::new();
    for class_info in &metadata.classes {
        real_class_names.insert(class_info.name.clone(), true);
    }
    let field_count: usize = objects.iter().map(|object| object.fields.len()).sum();
    let raw_fallback_count = objects
        .iter()
        .filter(|object| object.fields.is_empty() || object.status == "raw_preserved")
        .count();
    let status = if objects.is_empty() {
        "no_semantic_objects_recovered"
    } else {
        "read_only_semantic_model_from_native_records"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_semantic_model_v1\",\"status\":\"{}\",\"imported\":false,\"read_only\":true,\"object_count\":{},\"field_count\":{},\"raw_fallback_count\":{},\"graph_order_count\":{},\"root_record_index\":{},\"root_type_name\":{}",
        status,
        objects.len(),
        field_count,
        raw_fallback_count,
        graph.graph_order.len(),
        json_optional_usize(graph.root.record_index),
        json_optional_string(graph.root.type_name.as_deref())
    );
    out.push_str(",\"source_priority\":[\"real_hkclass_metadata_v2\",\"typed_layout_decoder\",\"raw_preserved_payload\"]");
    out.push_str(",\"field_kind_taxonomy\":[\"scalar\",\"vector\",\"array\",\"ref\",\"string\",\"enum\",\"struct\",\"raw_span\"]");
    out.push_str(",\"graph_order\":[");
    for (index, record_index) in graph.graph_order.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "{record_index}");
    }
    out.push_str("],\"objects\":[");
    for (object_index, object) in objects.iter().take(512).enumerate() {
        if object_index > 0 {
            out.push(',');
        }
        let class_metadata_source = if real_class_names.contains_key(&object.type_name) {
            "real_hkclass_metadata_v2"
        } else if !object.fields.is_empty() {
            "typed_layout_decoder"
        } else {
            "raw_preserved_payload"
        };
        let raw_span_count = object
            .fields
            .iter()
            .filter(|field| semantic_field_kind(field) == "raw_span")
            .count();
        let byte_range_end = object
            .absolute_data_offset
            .map(|offset| offset.saturating_add(object.byte_length));
        let _ = write!(
            out,
            "{{\"record_index\":{},\"type_index\":{},\"type_name\":\"{}\",\"count\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"byte_length\":{},\"byte_range_start\":{},\"byte_range_end\":{},\"status\":\"{}\",\"class_metadata_source\":\"{}\",\"semantic_source\":\"{}\",\"field_count\":{},\"reference_count\":{},\"raw_span_count\":{}",
            object.record_index,
            object.type_index,
            json_escape(&object.type_name),
            object.count,
            object.data_offset,
            json_optional_usize(object.absolute_data_offset),
            object.byte_length,
            json_optional_usize(object.absolute_data_offset),
            json_optional_usize(byte_range_end),
            json_escape(&object.status),
            class_metadata_source,
            class_metadata_source,
            object.fields.len(),
            object.references.len(),
            raw_span_count
        );
        out.push_str(",\"fields\":[");
        for (field_index, field) in object.fields.iter().enumerate() {
            if field_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"kind\":\"{}\",\"offset\":{},\"offset_hex\":\"0x{:X}\",\"size\":{},\"byte_range_start\":{},\"byte_range_end\":{},\"data_type\":\"{}\",\"value\":{},\"confidence\":\"{}\",\"editable_candidate\":{},\"write_enabled\":false,\"write_gate_status\":\"{}\",\"description\":\"{}\"}}",
                json_escape(&field.name),
                semantic_field_kind(field),
                field.offset,
                field.offset,
                field.size,
                json_optional_usize(object.absolute_data_offset.map(|base| base + field.offset)),
                json_optional_usize(
                    object
                        .absolute_data_offset
                        .map(|base| base + field.offset + field.size)
                ),
                json_escape(&field.data_type),
                json_layout_value(&field.value),
                json_escape(&field.confidence),
                json_bool(field.editable),
                if field.editable {
                    "candidate_only_until_edit_gate"
                } else {
                    "read_only"
                },
                json_escape(&field.description)
            );
        }
        out.push_str("],\"refs\":[");
        let mut emitted_ref = 0usize;
        for edge in graph
            .edges
            .iter()
            .filter(|edge| edge.source_record_index == Some(object.record_index))
        {
            if emitted_ref > 0 {
                out.push(',');
            }
            emitted_ref += 1;
            let _ = write!(
                out,
                "{{\"target_record_index\":{},\"owner_field_name\":{},\"owner_local_offset\":{},\"reference_category\":\"{}\",\"resolution_source\":\"{}\",\"confidence\":\"{}\"}}",
                json_optional_usize(edge.target_record_index),
                json_optional_string(edge.owner_field_name.as_deref()),
                json_optional_usize(edge.owner_local_offset),
                json_escape(&edge.reference_category),
                json_escape(&edge.resolution_source),
                json_escape(&edge.confidence)
            );
        }
        out.push_str("]}");
    }
    let _ = write!(
        out,
        "],\"truncated_object_count\":{},\"edit_policy\":{{\"havok_xml_importable\":false,\"semantic_writer_required\":true,\"blocked_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"class_metadata\"]}}}}",
        objects.len().saturating_sub(512)
    );
}

fn representative_hkx_roles() -> [&'static str; 6] {
    [
        "object",
        "meshphysics",
        "character_physics",
        "ragdoll_body",
        "mesh_heavy",
        "animation",
    ]
}

fn push_semantic_writer_gate_v1_json(out: &mut String, readiness: &HkxModdingReadiness) {
    let gate = &readiness.semantic_writer_gate;
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_semantic_writer_gate_v1\",\"status\":\"semantic_writer_disabled_until_byte_identity_proof\",\"source_status\":\"{}\",\"enabled\":false,\"semantic_rebuild_supported\":false,\"havok_xml_import_unblocked\":false,\"raw_preserving_no_edit_writer_available\":true,\"fixed_size_patch_importable\":{},\"patchable_slot_count\":{},\"mismatch_offset\":null,\"unsupported_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\"],\"unsupported_ref_kinds\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"]",
        json_escape(&gate.status),
        json_bool(readiness.fixed_size_patch_importable),
        readiness.patchable_slot_count
    );
    out.push_str(",\"writer_modes\":[");
    for (index, (mode, status, enabled, reason)) in [
        (
            "raw_preserving_no_edit",
            "available",
            true,
            "lossless byte segment writer; not semantic Havok XML import",
        ),
        (
            "semantic_no_edit",
            "disabled_pending_representative_byte_identity",
            false,
            "requires semantic model write to match bytes for all representative roles",
        ),
        (
            "semantic_fixed_edit",
            "disabled_pending_fixed_edit_tests",
            false,
            "requires no-edit identity plus per-field fixed-edit proof",
        ),
        (
            "havok_xml_import",
            "blocked",
            false,
            "blocked until semantic writer gates pass",
        ),
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"mode\":\"{}\",\"status\":\"{}\",\"enabled\":{},\"reason\":\"{}\"}}",
            mode,
            status,
            json_bool(*enabled),
            json_escape(reason)
        );
    }
    out.push(']');
    out.push_str(",\"required_role_coverage\":[");
    for (index, role) in representative_hkx_roles().iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"no_edit_status\":\"required\",\"semantic_no_edit_status\":\"required_not_verified_by_semantic_writer\",\"fixed_edit_status\":\"required\",\"byte_identity_status\":\"required_not_verified_by_semantic_writer\",\"sample_required\":true,\"fixed_size_edits_allowed\":false,\"havok_xml_import_unblocked\":false}}",
            role
        );
    }
    out.push_str("],\"representative_role_gates\":[");
    for (index, role) in representative_hkx_roles().iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"required\":true,\"no_edit_byte_identity\":\"not_proven_by_semantic_writer\",\"mismatch_offset\":null,\"unsupported_field_kinds\":[\"array\",\"ref\",\"string\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\"],\"unsupported_ref_kinds\":[\"data_ref\",\"string_ref\",\"type_class_ref\",\"section_local_ref\",\"packed_or_varuint\",\"unresolved\"],\"fixed_size_edits_allowed\":false,\"status\":\"representative_corpus_required\"}}",
            role
        );
    }
    out.push_str("],\"blocked_edit_classes\":");
    push_json_string_array(out, &gate.blocked_edits);
    out.push_str(",\"requirements\":");
    push_json_string_array(out, &gate.requirements);
    out.push('}');
}

fn write_type_for_slot_name(name: &str) -> &'static str {
    let lower = name.to_ascii_lowercase();
    if lower.contains("x") || lower.contains("y") || lower.contains("z") || lower.contains("w") {
        "f32_component"
    } else {
        "f32"
    }
}

fn edit_candidate_structural_kind(
    class_name: &str,
    member_name: &str,
    category: &str,
) -> &'static str {
    let haystack = format!(
        "{} {} {}",
        class_name.to_ascii_lowercase(),
        member_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if haystack.contains("primitive")
        || haystack.contains("topology")
        || haystack.contains("face")
        || haystack.contains("edge")
        || haystack.contains("count")
        || haystack.contains("array")
        || haystack.contains("ref")
        || haystack.contains("string")
    {
        "structural_blocked"
    } else if haystack.contains("radius")
        || haystack.contains("endpoint")
        || haystack.contains("transform")
        || haystack.contains("orientation")
        || haystack.contains("mass")
        || haystack.contains("friction")
        || haystack.contains("damping")
        || haystack.contains("motor")
        || haystack.contains("constraint")
        || haystack.contains("material")
    {
        "fixed_size_numeric"
    } else {
        "fixed_size_numeric_candidate"
    }
}

fn edit_candidate_task_key(class_name: &str, member_name: &str, category: &str) -> &'static str {
    let haystack = format!(
        "{} {} {}",
        class_name.to_ascii_lowercase(),
        member_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if haystack.contains("material")
        || haystack.contains("friction")
        || haystack.contains("restitution")
        || haystack.contains("surface")
    {
        "material_friction"
    } else if haystack.contains("damping")
        || haystack.contains("motion")
        || haystack.contains("velocity")
        || haystack.contains("sharedmotion")
    {
        "damping_motion"
    } else if haystack.contains("constraint")
        || haystack.contains("motor")
        || haystack.contains("stiffness")
        || haystack.contains("strength")
        || haystack.contains("force")
        || haystack.contains("torque")
        || haystack.contains("limit")
        || haystack.contains("hinge")
        || haystack.contains("ragdoll")
    {
        "joint_strength"
    } else if haystack.contains("body")
        || haystack.contains("transform")
        || haystack.contains("orientation")
        || haystack.contains("mass")
    {
        "body_transform"
    } else if haystack.contains("primitive")
        || haystack.contains("winding")
        || haystack.contains("aabb")
        || haystack.contains("topology")
    {
        "mesh_winding"
    } else if haystack.contains("shape")
        || haystack.contains("collision")
        || haystack.contains("radius")
        || haystack.contains("capsule")
        || haystack.contains("sphere")
        || haystack.contains("extent")
    {
        "collision_size"
    } else {
        "inspect_only"
    }
}

fn edit_candidate_task_label(task_key: &str) -> &'static str {
    match task_key {
        "collision_size" => "Collision Size",
        "body_transform" => "Body Transform",
        "joint_strength" => "Joint Strength",
        "damping_motion" => "Damping / Motion",
        "material_friction" => "Material / Friction",
        "mesh_winding" => "Mesh Winding",
        _ => "Inspect Only",
    }
}

fn edit_candidate_category_key(class_name: &str, member_name: &str, category: &str) -> String {
    if !category.is_empty() {
        return category.to_string();
    }
    match edit_candidate_task_key(class_name, member_name, category) {
        "collision_size" => "collision_size",
        "body_transform" => "body_transform_mass",
        "joint_strength" => "joint_limits_strength",
        "damping_motion" => "motion_damping_solver",
        "material_friction" => "material_surface_response",
        "mesh_winding" => "mesh_winding",
        _ => "native_scalar_candidate",
    }
    .to_string()
}

fn edit_candidate_linked_by(class_name: &str, category: &str, write_enabled: bool) -> &'static str {
    let haystack = format!(
        "{} {}",
        class_name.to_ascii_lowercase(),
        category.to_ascii_lowercase()
    );
    if write_enabled {
        "existing_patch_map"
    } else if haystack.contains("array") {
        "owner_array"
    } else if haystack.contains("ref") {
        "fixup_backed_or_inferred"
    } else {
        "typed_layout"
    }
}

fn push_edit_candidate_map_v1_json(
    out: &mut String,
    physics_tuning_groups: &[PhysicsTuningGroup],
    objects: &[ObjectRecord],
) {
    let tuning_candidate_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let layout_candidate_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let candidate_count = tuning_candidate_count + layout_candidate_count;
    let mut task_categories: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for group in physics_tuning_groups {
        let task_key = edit_candidate_task_key(&group.type_name, "", &group.category);
        let entry = task_categories
            .entry(task_key.to_string())
            .or_insert((0, 0));
        entry.0 += group.slots.len();
    }
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let entry = task_categories
                .entry(task_key.to_string())
                .or_insert((0, 0));
            entry.1 += 1;
        }
    }
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_edit_candidate_map_v1\",\"status\":\"fixed_size_numeric_candidates_only\",\"imported\":false,\"read_only\":false,\"new_editable_fields_enabled\":false,\"existing_patchable_slots_exposed\":{},\"candidate_count\":{},\"write_enabled_candidate_count\":{}",
        json_bool(tuning_candidate_count > 0),
        candidate_count,
        tuning_candidate_count
    );
    out.push_str(",\"blocked_kinds\":[\"arrays\",\"references\",\"strings\",\"topology\",\"counts\",\"compressed_tables\",\"class_metadata\"],\"task_categories\":[");
    for (index, task_key) in [
        "collision_size",
        "material_friction",
        "damping_motion",
        "joint_strength",
        "body_transform",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let (enabled_count, candidate_count) =
            task_categories.get(*task_key).copied().unwrap_or((0, 0));
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{}}}",
            task_key,
            edit_candidate_task_label(task_key),
            status,
            enabled_count,
            candidate_count
        );
    }
    out.push_str("],\"candidates\":[");
    let mut emitted = 0usize;
    for group in physics_tuning_groups {
        let object = objects
            .iter()
            .find(|object| object.record_index == group.record_index);
        let record_absolute_offset = object.and_then(|object| object.absolute_data_offset);
        for slot in &group.slots {
            if emitted > 0 {
                out.push(',');
            }
            emitted += 1;
            let risk_label =
                if slot.confidence == "confirmed" || slot.confidence == "strong inference" {
                    "medium"
                } else {
                    "high"
                };
            let record_relative_offset = slot.item_index * group.stride + slot.offset;
            let absolute_offset = record_absolute_offset.map(|base| base + record_relative_offset);
            let structural_kind =
                edit_candidate_structural_kind(&group.type_name, &slot.name, &group.category);
            let linked_by = edit_candidate_linked_by(&group.type_name, &group.category, true);
            let task_key = edit_candidate_task_key(&group.type_name, &slot.name, &group.category);
            let task_label = edit_candidate_task_label(task_key);
            let _ = write!(
                out,
                "{{\"class\":\"{}\",\"owner_class\":\"{}\",\"category\":\"{}\",\"category_label\":\"{}\",\"task_category\":\"{}\",\"task_label\":\"{}\",\"member\":\"{}\",\"field\":\"{}\",\"name\":\"{}\",\"record\":{},\"record_index\":{},\"item_index\":{},\"local_offset\":{},\"record_relative_offset\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"absolute_offset\":{},\"absolute_offset_hex\":\"{}\",\"byte_size\":4,\"original_value\":{},\"supported_write_type\":\"{}\",\"write_type\":\"{}\",\"value_kind\":\"fixed_size_numeric\",\"structural_kind\":\"{}\",\"import_safety\":\"import_safe\",\"risk_label\":\"{}\",\"risk\":\"{}\",\"confidence\":\"{}\",\"evidence\":\"native physics tuning fixed-size float scan; exact record/item/local offset recovered\",\"link_evidence\":\"{}\",\"linked_by\":\"{}\",\"linked_target\":\"{}\",\"import_path\":\"existing_fixed_size_patch\",\"import_behavior\":\"CDMW fixed-size float patch into original HKX bytes\",\"write_enabled\":true,\"gate_status\":\"enabled\",\"gate_reason\":\"covered by existing fixed-size CDMW patch route\",\"edit_rule\":\"{}\"}}",
                json_escape(&group.type_name),
                json_escape(&group.type_name),
                json_escape(&group.category),
                json_escape(task_label),
                json_escape(task_key),
                json_escape(task_label),
                json_escape(&slot.name),
                json_escape(&slot.name),
                json_escape(&slot.name),
                group.record_index,
                group.record_index,
                slot.item_index,
                slot.offset,
                record_relative_offset,
                slot.offset,
                slot.offset,
                json_optional_usize(absolute_offset),
                absolute_offset
                    .map(|offset| format!("0x{:X}", offset))
                    .unwrap_or_default(),
                if slot.value.is_finite() { slot.value.to_string() } else { "null".to_string() },
                write_type_for_slot_name(&slot.name),
                write_type_for_slot_name(&slot.name),
                structural_kind,
                risk_label,
                risk_label,
                json_escape(&slot.confidence),
                linked_by,
                linked_by,
                json_escape(&group.label),
                json_escape(&group.edit_rule)
            );
        }
    }
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            if emitted > 0 {
                out.push(',');
            }
            emitted += 1;
            let absolute_offset = object.absolute_data_offset.map(|base| base + field.offset);
            let structural_kind =
                edit_candidate_structural_kind(&object.type_name, &field.name, "");
            let linked_by = edit_candidate_linked_by(&object.type_name, "", false);
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let task_label = edit_candidate_task_label(task_key);
            let write_type = if field.data_type.contains("float") {
                "f32"
            } else {
                "fixed_size_numeric"
            };
            let _ = write!(
                out,
                "{{\"class\":\"{}\",\"owner_class\":\"{}\",\"category\":\"{}\",\"category_label\":\"{}\",\"task_category\":\"{}\",\"task_label\":\"{}\",\"member\":\"{}\",\"field\":\"{}\",\"name\":\"{}\",\"record\":{},\"record_index\":{},\"item_index\":null,\"local_offset\":{},\"record_relative_offset\":{},\"offset\":{},\"offset_hex\":\"0x{:X}\",\"absolute_offset\":{},\"absolute_offset_hex\":\"{}\",\"byte_size\":{},\"original_value\":{},\"supported_write_type\":\"{}\",\"write_type\":\"{}\",\"value_kind\":\"fixed_size_numeric_candidate\",\"structural_kind\":\"{}\",\"import_safety\":\"read_only\",\"risk_label\":\"high\",\"risk\":\"high\",\"confidence\":\"{}\",\"evidence\":\"typed layout editable flag; exact byte span observed, but write route requires fixed-edit proof\",\"link_evidence\":\"{}\",\"linked_by\":\"{}\",\"linked_target\":\"record/{}\",\"import_path\":\"blocked_until_fixed_edit_test\",\"import_behavior\":\"read-only until fixed-edit tests prove byte patch safety\",\"write_enabled\":false,\"gate_status\":\"candidate_only\",\"gate_reason\":\"decoded fixed-size field candidate lacks approved import route\",\"edit_rule\":\"candidate_only\"}}",
                json_escape(&object.type_name),
                json_escape(&object.type_name),
                json_escape(&category),
                json_escape(task_label),
                json_escape(task_key),
                json_escape(task_label),
                json_escape(&field.name),
                json_escape(&field.name),
                json_escape(&field.name),
                object.record_index,
                object.record_index,
                field.offset,
                field.offset,
                field.offset,
                field.offset,
                json_optional_usize(absolute_offset),
                absolute_offset
                    .map(|offset| format!("0x{:X}", offset))
                    .unwrap_or_default(),
                field.size,
                json_layout_value(&field.value),
                write_type,
                write_type,
                structural_kind,
                json_escape(&field.confidence),
                linked_by,
                linked_by,
                object.record_index
            );
        }
    }
    out.push_str("]}");
}

fn push_hkx_edit_gate_v1_json(
    out: &mut String,
    physics_tuning_groups: &[PhysicsTuningGroup],
    objects: &[ObjectRecord],
) {
    let write_enabled_count: usize = physics_tuning_groups
        .iter()
        .map(|group| group.slots.len())
        .sum();
    let candidate_only_count: usize = objects
        .iter()
        .map(|object| object.fields.iter().filter(|field| field.editable).count())
        .sum();
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_edit_gate_v1\",\"status\":\"fixed_size_patch_gate\",\"read_only\":true,\"new_editable_fields_enabled\":false,\"write_enabled_candidate_count\":{},\"candidate_only_count\":{},\"blocked_policy\":\"arrays, strings, references, topology, counts, compressed tables, and class metadata remain blocked until semantic rebuild proof\"",
        write_enabled_count,
        candidate_only_count
    );
    out.push_str(",\"required_role_coverage\":[");
    for (index, role) in [
        "object",
        "meshphysics",
        "character_physics",
        "ragdoll_body",
        "mesh_heavy",
        "animation",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"role\":\"{}\",\"no_edit_status\":\"required\",\"fixed_edit_status\":\"required\",\"status\":\"representative_corpus_required\"}}",
            role
        );
    }
    out.push_str("],\"categories\":[");
    let mut emitted = 0usize;
    let mut categories: BTreeMap<String, (usize, usize, String)> = BTreeMap::new();
    let mut task_categories: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for group in physics_tuning_groups {
        let entry = categories
            .entry(group.category.clone())
            .or_insert_with(|| (0, 0, group.type_name.clone()));
        entry.0 += group.slots.len();
        let task_key = edit_candidate_task_key(&group.type_name, "", &group.category);
        let task_entry = task_categories
            .entry(task_key.to_string())
            .or_insert((0, 0));
        task_entry.0 += group.slots.len();
    }
    for object in objects {
        for field in object.fields.iter().filter(|field| field.editable) {
            let category = edit_candidate_category_key(&object.type_name, &field.name, "");
            let entry = categories
                .entry(category.clone())
                .or_insert_with(|| (0, 0, object.type_name.clone()));
            entry.1 += 1;
            let task_key = edit_candidate_task_key(&object.type_name, &field.name, &category);
            let task_entry = task_categories
                .entry(task_key.to_string())
                .or_insert((0, 0));
            task_entry.1 += 1;
        }
    }
    for (category, (enabled_count, candidate_count, owner_class)) in categories {
        if emitted > 0 {
            out.push(',');
        }
        emitted += 1;
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let reason = if enabled_count > 0 {
            "existing fixed-size patch route"
        } else if candidate_count > 0 {
            "decoded candidate lacks fixed-edit corpus proof"
        } else {
            "no approved fixed-size patch target"
        };
        let _ = write!(
            out,
            "{{\"category\":\"{}\",\"owner_class\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{},\"fixed_edit_test_status\":\"{}\",\"gate_reason\":\"{}\"}}",
            json_escape(&category),
            json_escape(&owner_class),
            status,
            enabled_count,
            candidate_count,
            if enabled_count > 0 { "existing_route" } else { "required" },
            reason
        );
    }
    if emitted > 0 {
        out.push(',');
    }
    out.push_str("{\"category\":\"structural_edits\",\"owner_class\":\"*\",\"status\":\"blocked\",\"write_enabled_count\":0,\"candidate_only_count\":0,\"fixed_edit_test_status\":\"blocked\",\"gate_reason\":\"topology/count/reference/string/array edits require semantic rebuild proof\"}");
    out.push_str("],\"task_categories\":[");
    for (index, task_key) in [
        "collision_size",
        "material_friction",
        "damping_motion",
        "joint_strength",
        "body_transform",
    ]
    .iter()
    .enumerate()
    {
        if index > 0 {
            out.push(',');
        }
        let (enabled_count, candidate_count) =
            task_categories.get(*task_key).copied().unwrap_or((0, 0));
        let status = if enabled_count > 0 {
            "enabled"
        } else if candidate_count > 0 {
            "candidate_only"
        } else {
            "blocked"
        };
        let reason = if enabled_count > 0 {
            "existing fixed-size patch route"
        } else if candidate_count > 0 {
            "decoded candidate lacks fixed-edit corpus proof"
        } else {
            "no approved fixed-size patch target"
        };
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"write_enabled_count\":{},\"candidate_only_count\":{},\"fixed_edit_test_status\":\"{}\",\"gate_reason\":\"{}\"}}",
            task_key,
            edit_candidate_task_label(task_key),
            status,
            enabled_count,
            candidate_count,
            if enabled_count > 0 { "existing_route" } else { "required" },
            reason
        );
    }
    out.push_str("],\"blocked_kinds\":[\"array\",\"string\",\"reference\",\"topology\",\"count\",\"compressed_table\",\"class_metadata\",\"shape_primitive_count\"]}");
}

fn push_class_decoder_evidence_v2_json(
    out: &mut String,
    decoder: &DecoderEvidenceV2,
    hard: &HardInternalEvidenceReport,
) {
    let mut hard_by_type: BTreeMap<String, Vec<&HardInternalEvidenceTarget>> = BTreeMap::new();
    for target in &hard.targets {
        for type_name in &target.observed_types {
            hard_by_type
                .entry(type_name.clone())
                .or_default()
                .push(target);
        }
    }
    let status = if decoder.class_status_count > 0 {
        "class_specific_decode_evidence_available"
    } else {
        "class_specific_decode_evidence_not_recovered"
    };
    let _ = write!(
        out,
        "{{\"format\":\"cd_hkx_class_decoder_evidence_v2\",\"status\":\"{}\",\"source_format\":\"{}\",\"imported\":{},\"read_only\":true,\"class_status_count\":{},\"hard_target_count\":{},\"observed_hard_target_count\":{}",
        status,
        json_escape(&decoder.format),
        json_bool(decoder.imported),
        decoder.class_status_count,
        hard.target_count,
        hard.observed_target_count
    );
    out.push_str(",\"class_statuses\":[");
    for (index, row) in decoder.class_statuses.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let hard_targets = hard_by_type.get(&row.type_name);
        let _ = write!(
            out,
            "{{\"class\":\"{}\",\"type_name\":\"{}\",\"record_count\":{},\"byte_count\":{},\"decoded_field_count\":{},\"reference_count\":{},\"editable_candidate_count\":{},\"status\":\"{}\",\"friendly_status\":\"{}\",\"read_only\":{},\"corpus_priority_score\":{}",
            json_escape(&row.type_name),
            json_escape(&row.type_name),
            row.record_count,
            row.byte_count,
            row.decoded_field_count,
            row.reference_count,
            row.editable_field_count,
            json_escape(&row.status),
            json_escape(&row.friendly_status),
            json_bool(row.read_only),
            row.corpus_priority_score
        );
        out.push_str(",\"missing_requirements\":");
        push_json_string_array(out, &row.missing_requirements);
        out.push_str(",\"link_evidence\":");
        push_json_string_array(out, &row.link_evidence);
        out.push_str(",\"hard_internal_targets\":[");
        if let Some(targets) = hard_targets {
            for (target_index, target) in targets.iter().enumerate() {
                if target_index > 0 {
                    out.push(',');
                }
                let _ = write!(
                    out,
                    "{{\"key\":\"{}\",\"label\":\"{}\",\"status\":\"{}\",\"proof_status\":\"{}\",\"resolved\":{},\"confidence\":\"{}\"}}",
                    json_escape(&target.key),
                    json_escape(&target.label),
                    json_escape(&target.status),
                    json_escape(&target.proof_status),
                    json_bool(target.resolved),
                    json_escape(&target.confidence)
                );
            }
        }
        out.push_str("]}");
    }
    out.push_str("],\"missing_semantics_policy\":\"read-only until class layout, refs, arrays, and writer gate are proven\"}");
}

fn push_decoder_evidence_v2_json(out: &mut String, report: &DecoderEvidenceV2) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"read_only\":{},\"class_status_count\":{},\"priority_class_count\":{},\"total_partial_byte_count\":{},\"unresolved_or_packed_case_count\":{},\"owner_array_count\":{}",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        json_bool(report.read_only),
        report.class_status_count,
        report.priority_class_count,
        report.total_partial_byte_count,
        report.unresolved_or_packed_case_count,
        report.owner_array_count
    );
    out.push_str(",\"reference_semantic_counts\":");
    push_json_count_map(out, &report.reference_semantic_counts);
    out.push_str(",\"link_evidence_counts\":");
    push_json_count_map(out, &report.link_evidence_counts);
    out.push_str(",\"class_statuses\":[");
    for (index, row) in report.class_statuses.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"type_name\":\"{}\",\"record_count\":{},\"byte_count\":{},\"decoded_field_count\":{},\"reference_count\":{},\"editable_field_count\":{},\"status\":\"{}\",\"friendly_status\":\"{}\",\"corpus_priority_score\":{},\"read_only\":{}",
            json_escape(&row.type_name),
            row.record_count,
            row.byte_count,
            row.decoded_field_count,
            row.reference_count,
            row.editable_field_count,
            json_escape(&row.status),
            json_escape(&row.friendly_status),
            row.corpus_priority_score,
            json_bool(row.read_only)
        );
        out.push_str(",\"missing_requirements\":[");
        for (requirement_index, requirement) in row.missing_requirements.iter().enumerate() {
            if requirement_index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(requirement));
        }
        out.push_str("],\"link_evidence\":[");
        for (evidence_index, evidence) in row.link_evidence.iter().enumerate() {
            if evidence_index > 0 {
                out.push(',');
            }
            let _ = write!(out, "\"{}\"", json_escape(evidence));
        }
        out.push_str("]}");
    }
    out.push_str("],\"fixup_backed_fields\":[");
    for (index, field) in report.fixup_backed_fields.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"class_name\":\"{}\",\"field_name\":\"{}\",\"reference_category\":\"{}\",\"count\":{},\"confidence\":\"{}\"}}",
            json_escape(&field.class_name),
            json_escape(&field.field_name),
            json_escape(&field.reference_category),
            field.count,
            json_escape(&field.confidence)
        );
    }
    out.push_str("]}");
}

fn push_json_string_array(out: &mut String, values: &[String]) {
    out.push('[');
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(value));
    }
    out.push(']');
}

fn push_hkx_modding_readiness_json(out: &mut String, report: &HkxModdingReadiness) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"read_only\":{},\"per_file_label\":\"{}\",\"fixed_size_patch_importable\":{},\"havok_xml_importable\":{},\"new_editable_fields_enabled\":{},\"decoded_object_count\":{},\"patchable_slot_count\":{},\"fixup_backed_reference_edge_count\":{},\"owner_array_count\":{},\"unresolved_or_packed_case_count\":{}",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        json_bool(report.read_only),
        json_escape(&report.per_file_label),
        json_bool(report.fixed_size_patch_importable),
        json_bool(report.havok_xml_importable),
        json_bool(report.new_editable_fields_enabled),
        report.decoded_object_count,
        report.patchable_slot_count,
        report.fixup_backed_reference_edge_count,
        report.owner_array_count,
        report.unresolved_or_packed_case_count
    );
    out.push_str(",\"readiness_labels\":");
    push_json_string_array(out, &report.readiness_labels);
    out.push_str(",\"semantic_writer_gate\":");
    let gate = &report.semantic_writer_gate;
    let _ = write!(
        out,
        "{{\"status\":\"{}\",\"mode\":\"{}\",\"enabled\":{},\"raw_preserving_no_edit_writer_required\":{},\"semantic_rebuild_supported\":{},\"fixed_size_value_edits_allowed\":{}",
        json_escape(&gate.status),
        json_escape(&gate.mode),
        json_bool(gate.enabled),
        json_bool(gate.raw_preserving_no_edit_writer_required),
        json_bool(gate.semantic_rebuild_supported),
        json_bool(gate.fixed_size_value_edits_allowed)
    );
    out.push_str(",\"allowed_edits\":");
    push_json_string_array(out, &gate.allowed_edits);
    out.push_str(",\"blocked_edits\":");
    push_json_string_array(out, &gate.blocked_edits);
    out.push_str(",\"requirements\":");
    push_json_string_array(out, &gate.requirements);
    out.push_str("},\"task_groups\":[");
    for (index, group) in report.task_groups.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"readiness_label\":\"{}\",\"patchable_slot_count\":{},\"context_record_count\":{},\"risk\":\"{}\",\"import_safe\":{},\"description\":\"{}\",\"evidence\":",
            json_escape(&group.key),
            json_escape(&group.label),
            json_escape(&group.readiness_label),
            group.patchable_slot_count,
            group.context_record_count,
            json_escape(&group.risk),
            json_bool(group.import_safe),
            json_escape(&group.description)
        );
        push_json_string_array(out, &group.evidence);
        out.push('}');
    }
    out.push_str("]}");
}

pub fn summary_to_json(summary: &HkxSummary) -> String {
    let mut out = String::new();
    out.push('{');
    let _ = write!(
        out,
        "\"declared_size\":{},\"size_matches\":{},\"sdk_version\":\"{}\",\"tag0_offset\":{},",
        json_optional_u32(summary.declared_size),
        if summary.size_matches {
            "true"
        } else {
            "false"
        },
        json_escape(&summary.sdk_version),
        json_optional_usize(summary.tag0_offset)
    );
    out.push_str("\"tag_items\":[");
    for (index, item) in summary.tag_items.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"offset\":{},\"length_word_offset\":{},\"raw_length_word\":{},\"declared_length\":{},\"length_flags\":{},\"marker_end_offset\":{},\"word_end_offset\":{}}}",
            json_escape(&item.name),
            item.offset,
            json_optional_usize(item.length_word_offset),
            json_optional_u32(item.raw_length_word),
            json_optional_u32(item.declared_length),
            json_optional_u32(item.length_flags),
            json_optional_usize(item.marker_end_offset),
            json_optional_usize(item.word_end_offset)
        );
    }
    out.push_str("],\"string_table_names\":[");
    for (index, name) in summary.string_table_names.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(name));
    }
    out.push_str("],\"type_infos\":[");
    for (index, info) in summary.type_infos.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"index\":{},\"name\":\"{}\",\"display_name\":\"{}\",\"template_parameters\":[",
            info.index,
            json_escape(&info.name),
            json_escape(&info.display_name())
        );
        for (parameter_index, (name, value)) in info.template_parameters.iter().enumerate() {
            if parameter_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"value\":{}}}",
                json_escape(name),
                value
            );
        }
        out.push_str("]}");
    }
    out.push_str("],");
    let _ = write!(
        out,
        "\"declared_type_name_count\":{},",
        json_optional_u32(summary.declared_type_name_count)
    );
    out.push_str("\"type_names\":[");
    for (index, name) in summary.type_names.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(name));
    }
    out.push_str("],\"item_records\":[");
    for (index, record) in summary.item_records.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"index\":{},\"raw_type_flags\":{},\"type_index\":{},\"flags\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"count\":{},\"type_name\":\"{}\"}}",
            record.index,
            record.raw_type_flags,
            record.type_index,
            record.flags,
            record.data_offset,
            json_optional_usize(record.absolute_data_offset),
            record.count,
            json_escape(&record.type_name)
        );
    }
    out.push_str("],\"object_records\":[");
    for (index, object) in summary.object_records.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"record_index\":{},\"type_index\":{},\"type_name\":\"{}\",\"count\":{},\"data_offset\":{},\"absolute_data_offset\":{},\"byte_length\":{},\"stride\":{},\"status\":\"{}\",\"raw_hex_prefix\":\"{}\",\"fields\":[",
            object.record_index,
            object.type_index,
            json_escape(&object.type_name),
            object.count,
            object.data_offset,
            json_optional_usize(object.absolute_data_offset),
            object.byte_length,
            json_optional_f32(object.stride),
            json_escape(&object.status),
            json_escape(&object.raw_hex_prefix)
        );
        for (field_index, field) in object.fields.iter().enumerate() {
            if field_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"name\":\"{}\",\"offset\":{},\"hex_offset\":\"0x{:X}\",\"size\":{},\"data_type\":\"{}\",\"value\":{},\"description\":\"{}\",\"confidence\":\"{}\",\"editable\":{}}}",
                json_escape(&field.name),
                field.offset,
                field.offset,
                field.size,
                json_escape(&field.data_type),
                json_layout_value(&field.value),
                json_escape(&field.description),
                json_escape(&field.confidence),
                if field.editable { "true" } else { "false" }
            );
        }
        out.push_str("],\"references\":[");
        for (reference_index, reference) in object.references.iter().enumerate() {
            if reference_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"offset\":{},\"hex_offset\":\"0x{:X}\",\"reference_kind\":\"{}\",\"reference_category\":\"{}\",\"owner_field_name\":{},\"raw_value\":{},\"raw_value_hex\":\"0x{:X}\",\"target_record_index\":{},\"target_type_index\":{},\"target_type_name\":\"{}\",\"confidence\":\"experimental\"}}",
                reference.offset,
                reference.offset,
                json_escape(&reference.reference_kind),
                json_escape(&reference.reference_category),
                json_optional_string(reference.owner_field_name.as_deref()),
                reference.raw_value,
                reference.raw_value,
                reference.target_record_index,
                reference.target_type_index,
                json_escape(&reference.target_type_name)
            );
        }
        out.push_str("]}");
    }
    out.push_str("],\"tagfile_reference_fixups\":{");
    let fixups = &summary.tagfile_reference_fixups;
    let _ = write!(
        out,
        "\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"section_count\":{},\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_resolved_patch_site_count\":{},\"ptch_null_patch_site_count\":{},\"ptch_unresolved_patch_site_count\":{},\"match_kind_counts\":",
        json_escape(&fixups.format),
        json_escape(&fixups.status),
        if fixups.imported { "true" } else { "false" },
        fixups.section_count,
        fixups.ptch_table_count,
        fixups.ptch_patch_site_count,
        fixups.ptch_resolved_patch_site_count,
        fixups.ptch_null_patch_site_count,
        fixups.ptch_unresolved_patch_site_count
    );
    push_json_count_map(&mut out, &fixups.match_kind_counts);
    out.push_str(",\"reference_category_counts\":");
    push_json_count_map(&mut out, &fixups.reference_category_counts);
    out.push_str(",\"sections\":[");
    for (section_index, section) in fixups.sections.iter().enumerate() {
        if section_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"name\":\"{}\",\"offset\":{},\"payload_byte_length\":{},\"word_count\":{},\"shown_word_count\":{},\"truncated_word_count\":{},\"match_kind_counts\":",
            json_escape(&section.name),
            section.offset,
            section.payload_byte_length,
            section.word_count,
            section.shown_word_count,
            section.truncated_word_count
        );
        push_json_count_map(&mut out, &section.match_kind_counts);
        out.push_str(",\"reference_category_counts\":");
        push_json_count_map(&mut out, &section.reference_category_counts);
        let _ = write!(
            out,
            ",\"record_offset_match_count\":{},\"null_word_count\":{},\"type_index_match_count\":{},\"string_table_index_match_count\":{},\"ptch_tables\":[",
            section.record_offset_match_count,
            section.null_word_count,
            section.type_index_match_count,
            section.string_table_index_match_count
        );
        for (table_index, table) in section.ptch_tables.iter().enumerate() {
            if table_index > 0 {
                out.push(',');
            }
            push_ptch_table_json(&mut out, table);
        }
        out.push_str("],\"resolved_references\":[");
        for (word_index, word) in section.resolved_references.iter().enumerate() {
            if word_index > 0 {
                out.push(',');
            }
            push_fixup_word_json(&mut out, word);
        }
        out.push_str("],\"words\":[");
        for (word_index, word) in section.words.iter().enumerate() {
            if word_index > 0 {
                out.push(',');
            }
            push_fixup_word_json(&mut out, word);
        }
        out.push_str("]}");
    }
    out.push_str("]},\"fixup_semantics_report\":");
    push_fixup_semantics_report_json(&mut out, &summary.fixup_semantics_report);
    out.push_str(",\"native_model_graph\":");
    push_native_model_graph_json(&mut out, &summary.native_model_graph);
    out.push_str(",\"hard_internal_evidence\":");
    push_hard_internal_evidence_json(&mut out, &summary.hard_internal_evidence);
    out.push_str(",\"real_hkclass_metadata\":");
    push_real_hkclass_metadata_json(&mut out, &summary.real_hkclass_metadata);
    out.push_str(",\"real_hkclass_metadata_v2\":");
    push_real_hkclass_metadata_v2_json(&mut out, &summary.real_hkclass_metadata);
    out.push_str(",\"fixup_semantics_v2\":");
    push_fixup_semantics_v2_json(
        &mut out,
        &summary.tagfile_reference_fixups,
        &summary.fixup_semantics_report,
    );
    out.push_str(",\"semantic_model_v1\":");
    push_semantic_model_v1_json(
        &mut out,
        &summary.object_records,
        &summary.native_model_graph,
        &summary.real_hkclass_metadata,
    );
    out.push_str(",\"decoder_evidence_v2\":");
    push_decoder_evidence_v2_json(&mut out, &summary.decoder_evidence_v2);
    out.push_str(",\"modding_readiness\":");
    push_hkx_modding_readiness_json(&mut out, &summary.modding_readiness);
    out.push_str(",\"semantic_writer_gate_v1\":");
    push_semantic_writer_gate_v1_json(&mut out, &summary.modding_readiness);
    out.push_str(",\"edit_candidate_map_v1\":");
    push_edit_candidate_map_v1_json(
        &mut out,
        &summary.physics_tuning_groups,
        &summary.object_records,
    );
    out.push_str(",\"hkx_edit_gate_v1\":");
    push_hkx_edit_gate_v1_json(
        &mut out,
        &summary.physics_tuning_groups,
        &summary.object_records,
    );
    out.push_str(",\"class_decoder_evidence_v2\":");
    push_class_decoder_evidence_v2_json(
        &mut out,
        &summary.decoder_evidence_v2,
        &summary.hard_internal_evidence,
    );
    out.push_str(",\"physics_tuning_groups\":[");
    for (group_index, group) in summary.physics_tuning_groups.iter().enumerate() {
        if group_index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"category\":\"{}\",\"label\":\"{}\",\"type_name\":\"{}\",\"record_index\":{},\"count\":{},\"byte_length\":{},\"stride\":{},\"description\":\"{}\",\"confidence\":\"{}\",\"edit_rule\":\"{}\",\"slots\":[",
            json_escape(&group.category),
            json_escape(&group.label),
            json_escape(&group.type_name),
            group.record_index,
            group.count,
            group.byte_length,
            group.stride,
            json_escape(&group.description),
            json_escape(&group.confidence),
            json_escape(&group.edit_rule)
        );
        for (slot_index, slot) in group.slots.iter().enumerate() {
            if slot_index > 0 {
                out.push(',');
            }
            let _ = write!(
                out,
                "{{\"item_index\":{},\"offset\":{},\"hex_offset\":\"0x{:X}\",\"name\":\"{}\",\"value\":{},\"description\":\"{}\",\"confidence\":\"{}\"}}",
                slot.item_index,
                slot.offset,
                slot.offset,
                json_escape(&slot.name),
                if slot.value.is_finite() { slot.value.to_string() } else { "null".to_string() },
                json_escape(&slot.description),
                json_escape(&slot.confidence)
            );
        }
        out.push_str("]}");
    }
    out.push_str("],\"warnings\":[");
    for (index, warning) in summary.warnings.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(warning));
    }
    out.push_str("]}");
    out
}

pub fn summary_to_json_with_no_edit_report(
    summary: &HkxSummary,
    report: &NoEditBinaryWriterReport,
) -> String {
    let mut out = summary_to_json(summary);
    if out.ends_with('}') {
        out.pop();
    }
    out.push_str(",\"no_edit_binary_writer\":");
    push_no_edit_binary_writer_report_json(&mut out, report);
    out.push('}');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tag_item(marker: &[u8], payload: &[u8], flags: u32) -> Vec<u8> {
        let length = 4 + payload.len() as u32 + 4;
        let mut out = Vec::new();
        out.extend_from_slice(&(flags | length).to_be_bytes());
        out.extend_from_slice(marker);
        out.extend_from_slice(payload);
        out
    }

    fn sample_hkx() -> Vec<u8> {
        let type_names = b"hknpCompoundShape\0hknpConvexShape\0hkFloat3\0\xff";
        let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
        let mut item_payload = vec![0u8; 12];
        item_payload.extend_from_slice(&0x10000001u32.to_le_bytes());
        item_payload.extend_from_slice(&0u32.to_le_bytes());
        item_payload.extend_from_slice(&1u32.to_le_bytes());
        item_payload.extend_from_slice(&0x20000002u32.to_le_bytes());
        item_payload.extend_from_slice(&32u32.to_le_bytes());
        item_payload.extend_from_slice(&4u32.to_le_bytes());
        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &[0u8; 64], 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn array_ref_hkx() -> Vec<u8> {
        let type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff";
        let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
        let mut data_payload = vec![0u8; 64];
        data_payload[0..8].copy_from_slice(&32u64.to_le_bytes());
        data_payload[8..12].copy_from_slice(&3u32.to_le_bytes());
        data_payload[12..16].copy_from_slice(&0x8000_0003u32.to_le_bytes());
        data_payload[16..24].copy_from_slice(&32u64.to_le_bytes());
        data_payload[32..36].copy_from_slice(&0.25f32.to_le_bytes());
        data_payload[36..40].copy_from_slice(&1.5f32.to_le_bytes());

        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 16u32, 1u32),
            (0x1000_0003u32, 32u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        let mut indx_payload = Vec::new();
        for word in [0u32, 32u32, 1u32] {
            indx_payload.extend_from_slice(&word.to_le_bytes());
        }
        body.extend(tag_item(b"INDX", &indx_payload, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn nested_indx_ptch_hkx() -> Vec<u8> {
        let type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff";
        let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
        let mut data_payload = vec![0u8; 64];
        data_payload[16..24].copy_from_slice(&2u64.to_le_bytes());
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 16u32, 1u32),
            (0x1000_0003u32, 32u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }
        let mut item_section = Vec::new();
        item_section
            .extend_from_slice(&(0x4000_0000u32 | (8 + item_payload.len() as u32)).to_be_bytes());
        item_section.extend_from_slice(b"ITEM");
        item_section.extend_from_slice(&item_payload);
        let mut ptch_payload = Vec::new();
        for word in [1u32, 1, 0, 2, 1, 16] {
            ptch_payload.extend_from_slice(&word.to_le_bytes());
        }
        let mut indx_payload = item_section;
        indx_payload.extend(tag_item(b"PTCH", &ptch_payload, 0x40000000));

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend(tag_item(b"TPAD", b"", 0));
        body.extend(tag_item(b"INDX", &indx_payload, 0));
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn motor_hkx() -> Vec<u8> {
        let type_names = b"hknpPositionConstraintMotor\0\xff";
        let tna1 = [2u8, 0, 0];
        let mut data_payload = vec![0u8; 64];
        for (offset, value) in [
            (0x20usize, -1_000_000.0f32),
            (0x24usize, 1_000_000.0f32),
            (0x28usize, 0.8f32),
            (0x2Cusize, 1.0f32),
            (0x30usize, 2.0f32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
        item_payload.extend_from_slice(&0u32.to_le_bytes());
        item_payload.extend_from_slice(&1u32.to_le_bytes());

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn sphere_hkx() -> Vec<u8> {
        let type_names = b"hknpSphereShape\0\xff";
        let tna1 = [2u8, 0, 0];
        let mut data_payload = vec![0u8; 128];
        data_payload[0x68..0x6C].copy_from_slice(&0.25f32.to_le_bytes());
        let mut item_payload = vec![0u8; 12];
        item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
        item_payload.extend_from_slice(&0u32.to_le_bytes());
        item_payload.extend_from_slice(&1u32.to_le_bytes());

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn compressed_mass_hkx() -> Vec<u8> {
        let type_names =
            b"hknpShapeMassProperties\0hkCompressedMassProperties\0hkPackedVector3\0\xff";
        let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
        let mut data_payload = vec![0u8; 160];
        for (index, value) in [
            1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0, 7.0, 8.0,
        ]
        .iter()
        .copied()
        .enumerate()
        {
            data_payload[index * 4..index * 4 + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (index, value) in [0x1122_3344u32, 0x5566_7788, 0x0001_0002, 0x0003_0004]
            .iter()
            .copied()
            .enumerate()
        {
            let offset = 64 + index * 4;
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        data_payload[128..140].copy_from_slice(&[0, 64, 128, 255, 1, 2, 3, 4, 250, 251, 252, 253]);
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 64u32, 1u32),
            (0x2000_0003u32, 128u32, 3u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn scalar_enum_hkx() -> Vec<u8> {
        let type_names = b"unsigned int\0unsigned short\0unsigned long long\0hknpShapeType::Enum\0hknpShape::FlagsEnum\0\xff";
        let tna1 = [6u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0];
        let mut data_payload = vec![0u8; 80];
        for (index, value) in [7u32, 8, 0xABCD_EF01].iter().copied().enumerate() {
            let offset = index * 4;
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (index, value) in [1u16, 2, u16::MAX, 1024].iter().copied().enumerate() {
            let offset = 16 + index * 2;
            data_payload[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
        }
        for (index, value) in [0x1122_3344_5566_7788u64, 0x0102_0304_0506_0708]
            .iter()
            .copied()
            .enumerate()
        {
            let offset = 32 + index * 8;
            data_payload[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
        }
        data_payload[64..67].copy_from_slice(&[3, 4, 7]);
        data_payload[68..72].copy_from_slice(&0x10u32.to_le_bytes());
        data_payload[72..76].copy_from_slice(&0x20u32.to_le_bytes());

        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x2000_0001u32, 0u32, 3u32),
            (0x2000_0002u32, 16u32, 4u32),
            (0x2000_0003u32, 32u32, 2u32),
            (0x2000_0004u32, 64u32, 3u32),
            (0x2000_0005u32, 68u32, 2u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn box_hkx() -> Vec<u8> {
        let type_names = b"hknpBoxShape\0\xff";
        let tna1 = [2u8, 0, 0];
        let mut data_payload = vec![0u8; 192];
        for (offset, value) in [
            (0x30usize, 14u32),
            (0x38usize, 136u32),
            (0x3Cusize, 8u32),
            (0x40usize, 224u32),
            (0x44usize, 6u32),
            (0x48usize, 312u32),
            (0x4Cusize, 6u32),
            (0x50usize, 336u32),
            (0x54usize, 24u32),
            (0x58usize, 360u32),
            (0x5Cusize, 24u32),
            (0x60usize, 448u32),
            (0x64usize, 8u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (offset, value) in [(0x68usize, 0.015f32), (0x6Cusize, 0.008f32)] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (index, value) in [
            1.0f32, 0.0, 0.0, 0.075, 0.0, 1.0, 0.0, 0.048, 0.0, 0.0, 1.0, 0.009, -4.5, 1.0, 6.25,
            0.5,
        ]
        .iter()
        .enumerate()
        {
            let offset = 0x80usize + index * 4;
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        item_payload.extend_from_slice(&0x1000_0001u32.to_le_bytes());
        item_payload.extend_from_slice(&0u32.to_le_bytes());
        item_payload.extend_from_slice(&1u32.to_le_bytes());

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn skeleton_support_hkx() -> Vec<u8> {
        let type_names =
            b"char\0HavokShapeNameProperty\0hkQsTransform\0hkBone\0hkInt16\0hkSkeleton\0hknpMaterial\0\xff";
        let tna1 = [8u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0];
        let mut data_payload = vec![0u8; 480];
        data_payload[0..10].copy_from_slice(b"Bone_Test\0");
        data_payload[32 + 0x20..32 + 0x24].copy_from_slice(&1u32.to_le_bytes());
        for row_index in 0..2usize {
            let base = 80 + row_index * 48;
            for (component, value) in [row_index as f32, 1.0, 2.0, 1.0].iter().enumerate() {
                data_payload[base + component * 4..base + component * 4 + 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
            for (component, value) in [0.0f32, 0.0, 0.0, 1.0].iter().enumerate() {
                data_payload[base + 16 + component * 4..base + 20 + component * 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
            for (component, value) in [1.0f32, 1.0, 1.0, 1.0].iter().enumerate() {
                data_payload[base + 32 + component * 4..base + 36 + component * 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
        }
        for (offset, value) in [(176usize, 1u32), (184usize, u32::MAX), (192usize, 1u32)] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        data_payload[208..210].copy_from_slice(&(-1i16).to_le_bytes());
        data_payload[210..212].copy_from_slice(&0i16.to_le_bytes());
        for (offset, value) in [
            (224 + 0x18, 176u32),
            (224 + 0x1C, 2u32),
            (224 + 0x28, 208u32),
            (224 + 0x2C, 2u32),
            (224 + 0x38, 80u32),
            (224 + 0x3C, 2u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for material_index in 0..2usize {
            let base = 320 + material_index * 80;
            data_payload[base..base + 4]
                .copy_from_slice(&(27u32 + material_index as u32).to_le_bytes());
            for (component, value) in [1.0f32, 0.25, 0.1].iter().enumerate() {
                data_payload[base + 24 + component * 4..base + 28 + component * 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
            data_payload[base + 48..base + 52].copy_from_slice(&5.0f32.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 11u32),
            (0x1000_0002u32, 32u32, 1u32),
            (0x2000_0003u32, 80u32, 2u32),
            (0x2000_0004u32, 176u32, 2u32),
            (0x2000_0005u32, 208u32, 2u32),
            (0x1000_0006u32, 224u32, 1u32),
            (0x2000_0007u32, 320u32, 2u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn skeleton_mapper_support_hkx() -> Vec<u8> {
        let type_names =
            b"char\0hkaSkeletonMapper\0hkaSkeletonMapperData::SimpleMapping\0hkaAnimationContainer\0int\0\xff";
        let tna1 = [6u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0];
        let mut data_payload = vec![0u8; 512];
        data_payload[0..15].copy_from_slice(b"SkeletonMapper\0");
        for (offset, value) in [(32 + 0x20, 17u32), (32 + 0x28, 19u32), (32 + 0x60, 2u32)] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for row_index in 0..2usize {
            let base = 240 + row_index * 64;
            for (offset, value) in [
                (0usize, row_index as u32),
                (4usize, row_index as u32 + 10),
                (8usize, row_index as u32 + 20),
                (0x3Cusize, row_index as u32 + 30),
            ] {
                data_payload[base + offset..base + offset + 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
            for (component, value) in [0.5f32 + row_index as f32, 1.0, 1.0, 1.0]
                .iter()
                .enumerate()
            {
                data_payload[base + 0x20 + component * 4..base + 0x24 + component * 4]
                    .copy_from_slice(&value.to_le_bytes());
            }
        }
        data_payload[368 + 0x18..368 + 0x1C].copy_from_slice(&4u32.to_le_bytes());
        for (index, value) in [0i32, 1, 2, 3].iter().enumerate() {
            let offset = 480 + index * 4;
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 15u32),
            (0x1000_0002u32, 32u32, 1u32),
            (0x2000_0003u32, 240u32, 2u32),
            (0x1000_0004u32, 368u32, 1u32),
            (0x2000_0005u32, 480u32, 4u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn root_container_hkx() -> Vec<u8> {
        let type_names = b"hkRootLevelContainer\0hkRootLevelContainer::NamedVariant\0hknpPhysicsSceneData\0hknpConstraintCinfo\0\xff";
        let tna1 = [5u8, 0, 0, 1, 0, 2, 0, 3, 0];
        let mut data_payload = vec![0u8; 160];
        data_payload[0..8].copy_from_slice(&32u64.to_le_bytes());
        data_payload[8..12].copy_from_slice(&1u32.to_le_bytes());
        data_payload[12..16].copy_from_slice(&0x8000_0001u32.to_le_bytes());
        data_payload[32..40].copy_from_slice(&72u64.to_le_bytes());
        data_payload[40..48].copy_from_slice(&88u64.to_le_bytes());
        data_payload[48..56].copy_from_slice(&96u64.to_le_bytes());
        data_payload[96..100].copy_from_slice(&128u32.to_le_bytes());
        data_payload[100..104].copy_from_slice(&1u32.to_le_bytes());
        data_payload[128..132].copy_from_slice(&32u32.to_le_bytes());
        data_payload[132..136].copy_from_slice(&96u32.to_le_bytes());
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 32u32, 1u32),
            (0x1000_0003u32, 96u32, 1u32),
            (0x1000_0004u32, 128u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn root_reference_payload_hkx() -> Vec<u8> {
        let type_names = b"hkRefVariant\0hkStringPtr\0hkMemoryResourceContainer\0hknpPhysicsSystemData\0hknpConstraintData\0hknpRefDragProperties\0hknpRefMassDistribution\0\xff";
        let tna1 = [8u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0];
        let mut data_payload = vec![0u8; 256];
        data_payload[0..8].copy_from_slice(&64u64.to_le_bytes());
        data_payload[8..12].copy_from_slice(&4u32.to_le_bytes());
        data_payload[12..16].copy_from_slice(&8u32.to_le_bytes());
        data_payload[16..24].copy_from_slice(&80u64.to_le_bytes());
        data_payload[24..28].copy_from_slice(&12u32.to_le_bytes());
        data_payload[28..32].copy_from_slice(&16u32.to_le_bytes());
        for (base, pair_a, pair_b, value) in [
            (32usize, 64u32, 2u32, 0.25f32),
            (64usize, 112u32, 1u32, 1.5f32),
            (112usize, 160u32, 6u32, 2.5f32),
            (160usize, 208u32, 7u32, 0.75f32),
            (208usize, 32u32, 9u32, 3.25f32),
        ] {
            data_payload[base..base + 4].copy_from_slice(&pair_a.to_le_bytes());
            data_payload[base + 4..base + 8].copy_from_slice(&pair_b.to_le_bytes());
            data_payload[base + 16..base + 20].copy_from_slice(&value.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 16u32, 1u32),
            (0x1000_0003u32, 32u32, 1u32),
            (0x1000_0004u32, 64u32, 1u32),
            (0x1000_0005u32, 112u32, 1u32),
            (0x1000_0006u32, 160u32, 1u32),
            (0x1000_0007u32, 208u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn body_constraint_reference_hkx() -> Vec<u8> {
        let type_names = b"hknpPhysicsSystemData\0hknpPhysicsSystemData::ExtendedBodyCinfo\0hknpConstraintCinfo\0\xff";
        let tna1 = [4u8, 0, 0, 1, 0, 2, 0];
        let mut data_payload = vec![0u8; 256];
        for (offset, low, high) in [
            (0x00usize, 320u32, 2u32),
            (0x08usize, 352u32, 3u32),
            (0x10usize, 64u32, 1u32),
            (0x18usize, 192u32, 1u32),
            (0x20usize, 400u32, 4u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
            data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
        }
        for (offset, low, high) in [
            (64usize + 0x08, 400u32, 12u32),
            (64usize + 0x10, 352u32, 3u32),
            (64usize + 0x18, 27u32, 5u32),
            (64usize + 0x20, 99u32, 2u32),
            (64usize + 0x60, 123u32, 456u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
            data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
        }
        for (index, value) in [1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0]
            .iter()
            .copied()
            .enumerate()
        {
            let offset = 64 + 0x30 + index * 4;
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (offset, low, high) in [
            (192usize + 0x00, 10u32, 0u32),
            (192usize + 0x08, 11u32, 0u32),
            (192usize + 0x10, 160u32, 1u32),
            (192usize + 0x18, 7u32, 9u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&low.to_le_bytes());
            data_payload[offset + 4..offset + 8].copy_from_slice(&high.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0002u32, 64u32, 1u32),
            (0x1000_0003u32, 192u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn compound_blocker_hkx() -> Vec<u8> {
        let type_names = b"hknpCompoundShape\0hknpShapeInstance\0hkcdSimdTreeNamespace::Node\0hknpShapeProperties::Entry\0hkFreeListArrayElement<tVALUE_TYPE=7>\0hknpShapeMassProperties\0\xff";
        let tna1 = [7u8, 0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0];
        let mut data_payload = vec![0u8; 416];
        for (offset, value) in [
            (0x20usize, 128u32),
            (0x24usize, 2u32),
            (0x30usize, 192u32),
            (0x34usize, 2u32),
            (0x40usize, 288u32),
            (0x44usize, 2u32),
        ] {
            data_payload[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for base in [128usize, 160, 192, 208, 256, 272, 288, 320] {
            for index in 0..4usize {
                data_payload[base + index * 4..base + index * 4 + 4]
                    .copy_from_slice(&((base + index) as u32).to_le_bytes());
            }
        }
        for (index, value) in [
            1.0f32, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0, 7.0, 8.0,
        ]
        .iter()
        .enumerate()
        {
            data_payload[352 + index * 4..352 + index * 4 + 4]
                .copy_from_slice(&value.to_le_bytes());
        }
        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x2000_0002u32, 128u32, 2u32),
            (0x2000_0003u32, 192u32, 2u32),
            (0x2000_0004u32, 256u32, 2u32),
            (0x2000_0005u32, 288u32, 2u32),
            (0x1000_0006u32, 352u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    fn real_hkclass_metadata_hkx() -> Vec<u8> {
        let type_names = b"char\0hkClass\0hkClassMember\0hknpFoo\0\xff";
        let tna1 = [5u8, 0, 0, 1, 0, 2, 0, 3, 0];
        let mut data_payload = vec![0u8; 288];
        data_payload[16..24].copy_from_slice(b"hknpFoo\0");
        data_payload[32..37].copy_from_slice(b"mass\0");
        data_payload[48..54].copy_from_slice(b"child\0");

        data_payload[80..88].copy_from_slice(&2u64.to_le_bytes());
        data_payload[104] = 11;
        data_payload[105] = 0;
        data_payload[106..108].copy_from_slice(&0u16.to_le_bytes());
        data_payload[108..110].copy_from_slice(&0x1234u16.to_le_bytes());
        data_payload[110..112].copy_from_slice(&0x20u16.to_le_bytes());

        data_payload[120..128].copy_from_slice(&3u64.to_le_bytes());
        data_payload[128..136].copy_from_slice(&5u64.to_le_bytes());
        data_payload[144] = 20;
        data_payload[145] = 25;
        data_payload[146..148].copy_from_slice(&0u16.to_le_bytes());
        data_payload[148..150].copy_from_slice(&1u16.to_le_bytes());
        data_payload[150..152].copy_from_slice(&0x28u16.to_le_bytes());

        data_payload[160..168].copy_from_slice(&1u64.to_le_bytes());
        data_payload[176..180].copy_from_slice(&64u32.to_le_bytes());
        data_payload[200..208].copy_from_slice(&4u64.to_le_bytes());
        data_payload[208..212].copy_from_slice(&2u32.to_le_bytes());
        data_payload[232..236].copy_from_slice(&4u32.to_le_bytes());
        data_payload[236..240].copy_from_slice(&3u32.to_le_bytes());
        data_payload[240..244].copy_from_slice(&0xABCDEF01u32.to_le_bytes());

        let mut item_payload = vec![0u8; 12];
        for (raw_type_flags, offset, count) in [
            (0x1000_0001u32, 0u32, 1u32),
            (0x1000_0001u32, 16u32, 8u32),
            (0x1000_0001u32, 32u32, 5u32),
            (0x1000_0001u32, 48u32, 6u32),
            (0x1000_0003u32, 80u32, 2u32),
            (0x1000_0002u32, 160u32, 1u32),
        ] {
            item_payload.extend_from_slice(&raw_type_flags.to_le_bytes());
            item_payload.extend_from_slice(&offset.to_le_bytes());
            item_payload.extend_from_slice(&count.to_le_bytes());
        }

        let mut body = b"TAG0".to_vec();
        body.extend(tag_item(b"SDKV", b"20240200", 0x40000000));
        body.extend(tag_item(b"DATA", &data_payload, 0x40000000));
        body.extend(tag_item(b"TST1", type_names, 0x40000000));
        body.extend(tag_item(b"TNA1", &tna1, 0x40000000));
        body.extend((8u32 + item_payload.len() as u32).to_be_bytes());
        body.extend_from_slice(b"ITEM");
        body.extend(item_payload);
        let mut out = ((body.len() + 4) as u32).to_be_bytes().to_vec();
        out.extend(body);
        out
    }

    #[test]
    fn parses_modern_tagfile_sections_types_and_items() {
        let data = sample_hkx();
        let summary = parse_summary(&data);
        assert_eq!(summary.sdk_version, "20240200");
        assert!(summary.size_matches);
        assert_eq!(summary.declared_type_name_count, Some(4));
        assert_eq!(
            summary.type_names,
            vec!["hknpCompoundShape", "hknpConvexShape", "hkFloat3"]
        );
        assert_eq!(summary.item_records.len(), 2);
        assert_eq!(summary.item_records[1].type_name, "hknpConvexShape");
        assert_eq!(summary.item_records[1].data_offset, 32);
        assert_eq!(summary.item_records[1].count, 4);
        assert_eq!(summary.object_records.len(), 2);
        assert_eq!(summary.object_records[1].byte_length, 32);
        assert!(summary_to_json(&summary).contains("\"item_records\""));
        assert!(summary_to_json(&summary).contains("\"object_records\""));
        assert!(summary_to_json(&summary).contains("\"semantic_model_v1\""));
        assert!(summary_to_json(&summary).contains("\"semantic_writer_gate_v1\""));
        assert!(summary_to_json(&summary).contains("\"class_decoder_evidence_v2\""));
        assert_eq!(
            summary.modding_readiness.format,
            "cd_hkx_modding_readiness_v1"
        );
        assert!(!summary.modding_readiness.havok_xml_importable);
        assert!(
            !summary
                .modding_readiness
                .semantic_writer_gate
                .semantic_rebuild_supported
        );
        assert!(summary_to_json(&summary).contains("\"modding_readiness\""));
    }

    #[test]
    fn no_edit_binary_model_writes_identical_bytes() {
        let data = sample_hkx();
        let model = read_no_edit_model(&data).unwrap();
        assert_eq!(model.summary.item_records.len(), 2);
        assert!(!model.raw_segments.is_empty());
        assert_eq!(
            model
                .raw_segments
                .iter()
                .map(|segment| segment.byte_length)
                .sum::<usize>(),
            data.len()
        );
        let output = write_no_edit_model(&model).unwrap();
        assert_eq!(output, data);

        let (roundtrip, report) = roundtrip_no_edit(&data);
        assert_eq!(roundtrip, data);
        assert_eq!(report.format, "cd_hkx_no_edit_binary_writer_v1");
        assert_eq!(report.status, "byte_identical");
        assert_eq!(report.native_writer_status, "available");
        assert_eq!(
            report.no_edit_roundtrip_mode,
            "native_read_model_write_lossless_bytes"
        );
        assert!(report.native_read_model_write_available);
        assert!(report.byte_identical_no_edit_rebuild_supported);
        assert!(!report.semantic_rebuild_supported);
        assert!(report.parsed_raw_segment_count > 0);
        assert_eq!(report.first_mismatch_offset, None);

        let summary = parse_summary(&data);
        let json = summary_to_json_with_no_edit_report(&summary, &report);
        assert!(json.contains("\"no_edit_binary_writer\""));
        assert!(json.contains("\"status\":\"byte_identical\""));
    }

    #[test]
    fn no_edit_binary_model_rejects_non_hkx_input() {
        let report = verify_no_edit_roundtrip(b"not hkx");
        assert_eq!(report.status, "read_error");
        assert!(!report.native_read_model_write_available);
        assert!(!report.byte_identical_no_edit_rebuild_supported);
        assert!(!report.validation_errors.is_empty());
    }

    #[test]
    fn decodes_object_layouts_and_reference_candidates() {
        let data = array_ref_hkx();
        let summary = parse_summary(&data);
        assert_eq!(summary.object_records.len(), 3);

        let array = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkArray")
            .unwrap();
        assert_eq!(array.status, "partially_decoded");
        assert!(array
            .fields
            .iter()
            .any(|field| field.name == "size" && field.value == Some(LayoutValue::U32(3))));
        assert!(array
            .references
            .iter()
            .any(|reference| reference.target_record_index == 2
                && reference.reference_kind == "data_offset"
                && reference.reference_category == "array_data_reference"
                && reference.owner_field_name == Some("data".to_string())));

        let reference = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkRefPtr")
            .unwrap();
        assert!(reference
            .fields
            .iter()
            .any(|field| field.name == "referenced_object"));
        assert!(reference
            .references
            .iter()
            .any(|link| link.target_type_name == "hknpShape"
                && link.reference_category == "object_reference"));

        let shape = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpShape")
            .unwrap();
        assert!(shape
            .fields
            .iter()
            .any(|field| field.name == "finite_float_0x0"));
        let json = summary_to_json(&summary);
        assert!(json.contains("\"references\""));
        assert!(json.contains("\"reference_category\":\"array_data_reference\""));
        assert!(json.contains("\"tagfile_reference_fixups\""));
        assert_eq!(summary.tagfile_reference_fixups.section_count, 1);
        let indx = &summary.tagfile_reference_fixups.sections[0];
        assert_eq!(indx.name, "INDX");
        assert_eq!(indx.null_word_count, 1);
        assert!(indx.record_offset_match_count >= 1);
        assert!(indx.type_index_match_count >= 1);
        assert!(indx
            .resolved_references
            .iter()
            .any(|word| word.reference_category == "object_reference"));
        assert!(json.contains("\"finite_float_0x0\""));
    }

    #[test]
    fn decodes_nested_indx_item_and_ptch_tables() {
        let data = nested_indx_ptch_hkx();
        let summary = parse_summary(&data);

        assert!(summary.tag_items.iter().any(|item| item.name == "PTCH"));
        assert_eq!(summary.item_records.len(), 3);
        let section = summary
            .tagfile_reference_fixups
            .sections
            .iter()
            .find(|section| section.name == "INDX")
            .unwrap();
        assert_eq!(
            section.match_kind_counts.get("item_type_flags").copied(),
            Some(3)
        );
        assert_eq!(
            section.match_kind_counts.get("item_data_offset").copied(),
            Some(3)
        );
        assert_eq!(
            section.match_kind_counts.get("ptch_length_word").copied(),
            Some(1)
        );
        assert_eq!(
            section.match_kind_counts.get("ptch_marker").copied(),
            Some(1)
        );
        assert_eq!(
            section.match_kind_counts.get("ptch_header_word").copied(),
            Some(4)
        );
        assert_eq!(
            section
                .match_kind_counts
                .get("ptch_patch_site_count")
                .copied(),
            Some(1)
        );
        assert_eq!(
            section
                .match_kind_counts
                .get("ptch_object_patch_offset")
                .copied(),
            Some(1)
        );
        assert_eq!(summary.tagfile_reference_fixups.ptch_table_count, 1);
        assert_eq!(summary.tagfile_reference_fixups.ptch_patch_site_count, 1);
        assert_eq!(
            summary
                .tagfile_reference_fixups
                .ptch_resolved_patch_site_count,
            1
        );
        assert_eq!(
            summary.tagfile_reference_fixups.ptch_null_patch_site_count,
            0
        );
        assert_eq!(
            summary
                .tagfile_reference_fixups
                .ptch_unresolved_patch_site_count,
            0
        );
        assert_eq!(section.ptch_tables.len(), 1);
        let ptch_table = &section.ptch_tables[0];
        let ptch_item = summary
            .tag_items
            .iter()
            .find(|item| item.name == "PTCH")
            .unwrap();
        assert_eq!(ptch_table.offset, ptch_item.offset);
        assert_eq!(ptch_table.payload_byte_length, 24);
        assert_eq!(ptch_table.header, [1, 1, 0, 2]);
        assert_eq!(ptch_table.patch_site_count, 1);
        assert_eq!(ptch_table.resolved_patch_site_count, 1);
        assert_eq!(ptch_table.patch_sites.len(), 1);
        let patch_site = &ptch_table.patch_sites[0];
        assert_eq!(patch_site.ptch_word_index, 5);
        assert_eq!(patch_site.section_word_index, Some(21));
        assert_eq!(patch_site.patch_site_offset, 16);
        assert_eq!(patch_site.owner_record_index, Some(1));
        assert_eq!(patch_site.owner_local_offset, Some(0));
        assert_eq!(patch_site.patch_value, Some(2));
        assert_eq!(patch_site.target_status, "object");
        assert_eq!(patch_site.target_record_index, Some(2));
        assert!(!section.match_kind_counts.contains_key("unresolved_word"));
        let patch_word = section
            .words
            .iter()
            .find(|word| word.match_kind == "ptch_object_patch_offset")
            .unwrap();
        assert_eq!(patch_word.owner_record_index, Some(1));
        assert_eq!(patch_word.owner_local_offset, Some(0));
        assert_eq!(patch_word.patch_value, Some(2));
        assert_eq!(patch_word.target_record_index, Some(2));
        assert_eq!(patch_word.reference_category, "object_reference");
        let graph = &summary.native_model_graph;
        assert_eq!(graph.format, "cd_hkx_native_model_graph_v1");
        assert_eq!(graph.node_count, 3);
        assert_eq!(graph.fixup_backed_reference_edge_count, 1);
        assert!(graph.edges.iter().any(|edge| {
            edge.source_record_index == Some(1)
                && edge.target_record_index == Some(2)
                && edge.owner_field_name.as_deref() == Some("ptr")
                && edge.reference_category == "object_reference"
                && edge.resolution_source == "ptch"
        }));
        assert!(graph.graph_order.contains(&2));
        let semantics = &summary.fixup_semantics_report;
        assert_eq!(semantics.format, "cd_hkx_fixup_semantics_report_v1");
        assert_eq!(semantics.ptch_table_count, 1);
        assert_eq!(semantics.ptch_patch_site_count, 1);
        assert_eq!(semantics.ptch_object_patch_site_count, 1);
        assert_eq!(
            semantics.ptch_tuple_shape_counts.get("1,1,0,2").copied(),
            Some(1)
        );
        assert_eq!(
            semantics
                .ptch_payload_match_kind_counts
                .get("ptch_object_patch_offset")
                .copied(),
            Some(1)
        );
        assert_eq!(
            semantics.ptch_target_status_counts.get("object").copied(),
            Some(1)
        );

        let json = summary_to_json(&summary);
        assert!(json.contains("\"fixup_semantics_report\""));
        assert!(json.contains("\"fixup_semantics_v2\""));
        assert!(json.contains("\"semantic_bucket\":\"object_ref\""));
        assert!(json.contains("\"semantic_bucket_counts\""));
        assert!(json.contains("\"semantic_bucket_taxonomy\""));
        assert!(json.contains("\"data_ref\""));
        assert!(json.contains("\"string_ref\""));
        assert!(json.contains("\"type_class_ref\""));
        assert!(json.contains("\"section_local_ref\""));
        assert!(json.contains("\"packed_or_varuint\""));
        assert!(json.contains("\"corpus_evidence_counters\""));
        assert!(json.contains("\"patch_site_count\":1"));
        assert!(json.contains("\"cd_hkx_fixup_semantics_report_v1\""));
        assert!(json.contains("\"ptch_object_patch_offset\""));
        assert!(json.contains("\"ptch_tables\""));
        assert!(json.contains("\"target_status\":\"object\""));
        assert!(json.contains("\"owner_record_index\":1"));
        assert!(json.contains("\"native_model_graph\""));
        assert!(json.contains("\"resolution_source\":\"ptch\""));
        assert!(json.contains("\"decoder_evidence_v2\""));
        assert!(json.contains("\"fixup_backed\""));
        assert!(json.contains("\"object\""));
        assert!(json.contains("\"semantic_model_v1\""));
        assert!(json.contains("\"source_priority\""));
        assert!(json.contains("\"field_kind_taxonomy\""));
        assert!(json.contains("\"semantic_writer_gate_v1\""));
        assert!(json.contains("\"writer_modes\""));
        assert!(json.contains("\"representative_role_gates\""));
        assert!(json.contains("\"semantic_no_edit_status\""));
    }

    #[test]
    fn normalizes_decoder_evidence_v2_reference_and_link_semantics() {
        assert_eq!(
            decoder_reference_semantic_from_parts("object_reference", "data_offset", ""),
            "object"
        );
        assert_eq!(
            decoder_reference_semantic_from_parts("null_reference", "null", "null"),
            "null"
        );
        assert_eq!(
            decoder_reference_semantic_from_parts("array_data_reference", "data_offset", ""),
            "data_candidate"
        );
        assert_eq!(
            decoder_reference_semantic_from_parts("string_reference", "string_table_index", ""),
            "string_candidate"
        );
        assert_eq!(
            decoder_reference_semantic_from_parts("type_class_reference", "string_table_index", ""),
            "type_class"
        );
        assert_eq!(
            decoder_reference_semantic_from_parts("unresolved_fixup_word", "packed_varuint", ""),
            "packed_or_varuint"
        );

        let data = nested_indx_ptch_hkx();
        let summary = parse_summary(&data);
        let evidence = &summary.decoder_evidence_v2;
        assert_eq!(evidence.format, "cd_hkx_decoder_evidence_v2");
        assert_eq!(evidence.status, "read_only_native_evidence");
        assert!(evidence.read_only);
        assert!(
            evidence
                .reference_semantic_counts
                .get("object")
                .copied()
                .unwrap_or(0)
                >= 1
        );
        assert!(
            evidence
                .link_evidence_counts
                .get("fixup_backed")
                .copied()
                .unwrap_or(0)
                >= 1
        );
        assert!(evidence.fixup_backed_fields.iter().any(|field| {
            field.class_name == "hkRefPtr"
                && field.field_name == "ptr"
                && field.reference_category == "object_reference"
        }));
        assert!(evidence
            .class_statuses
            .iter()
            .any(|row| row.type_name == "hkRefPtr"
                && row
                    .link_evidence
                    .iter()
                    .any(|value| value == "fixup_backed")));
    }

    #[test]
    fn decoder_evidence_v2_reports_owner_arrays_and_class_gaps() {
        let data = root_container_hkx();
        let summary = parse_summary(&data);
        let evidence = &summary.decoder_evidence_v2;
        assert!(evidence.owner_array_count >= 1);
        assert!(
            evidence
                .link_evidence_counts
                .get("declared_owner_array")
                .copied()
                .unwrap_or(0)
                >= 1
        );
        assert!(evidence.class_statuses.iter().any(|row| {
            row.type_name == "hkRootLevelContainer"
                && row
                    .link_evidence
                    .iter()
                    .any(|value| value == "declared_owner_array")
        }));

        let mesh_data = compound_blocker_hkx();
        let mesh_summary = parse_summary(&mesh_data);
        let mesh_evidence = &mesh_summary.decoder_evidence_v2;
        assert!(mesh_evidence.class_statuses.iter().any(|row| {
            row.type_name == "hknpCompoundShape"
                && row.friendly_status.contains("compound child transform")
                && row.read_only
        }));
        let json = summary_to_json(&mesh_summary);
        assert!(json.contains("\"friendly_status\""));
        assert!(json.contains("compound child transform"));
    }

    #[test]
    fn exports_physics_tuning_groups_for_motor_slots() {
        let data = motor_hkx();
        let summary = parse_summary(&data);

        assert_eq!(summary.physics_tuning_groups.len(), 1);
        let group = &summary.physics_tuning_groups[0];
        assert_eq!(group.category, "motor_force_response");
        assert_eq!(group.record_index, 0);
        assert!(group.slots.iter().any(|slot| {
            slot.offset == 0x28 && slot.name == "stiffness_or_strength" && slot.value == 0.8f32
        }));
        assert!(group
            .slots
            .iter()
            .any(|slot| slot.offset == 0x20 && slot.confidence == "strong inference"));
        let motor_object = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpPositionConstraintMotor")
            .unwrap();
        assert!(motor_object
            .fields
            .iter()
            .any(|field| field.name == "stiffness_or_strength[0]" && field.editable));
        let json = summary_to_json(&summary);
        assert!(json.contains("\"physics_tuning_groups\""));
        assert!(json.contains("\"edit_candidate_map_v1\""));
        assert!(json.contains("\"write_enabled\":true"));
        assert!(json.contains("\"new_editable_fields_enabled\":false"));
        assert!(json.contains("\"motor_force_response\""));
        assert!(json.contains("\"stiffness_or_strength\""));
    }

    #[test]
    fn patches_supported_fixed_float_slots_only() {
        let data = motor_hkx();
        let patched = patch_fixed_float(&data, 0, 0, 0x28, 0.6).unwrap();
        let summary = parse_summary(&patched);
        let group = &summary.physics_tuning_groups[0];
        assert!(group
            .slots
            .iter()
            .any(|slot| slot.offset == 0x28 && (slot.value - 0.6).abs() < 0.000_001));
        assert_eq!(patched.len(), data.len());
        assert!(patch_fixed_float(&data, 0, 0, 0x04, 0.6).is_err());
        assert!(patch_fixed_float(&data, 0, 0, 0x28, f32::NAN).is_err());
    }

    #[test]
    fn decodes_sphere_radius_layout() {
        let data = sphere_hkx();
        let summary = parse_summary(&data);
        let sphere = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpSphereShape")
            .unwrap();
        assert!(sphere.fields.iter().any(|field| {
            field.name == "radius" && field.value == Some(LayoutValue::F32(0.25)) && field.editable
        }));
    }

    #[test]
    fn decodes_mass_properties_and_packed_vectors() {
        let data = compressed_mass_hkx();
        let summary = parse_summary(&data);
        let mass = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpShapeMassProperties")
            .unwrap();
        assert!(mass.fields.iter().any(|field| field.name
            == "mass_properties_row3_center_mass_or_scale"
            && field.editable));
        let compressed = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkCompressedMassProperties")
            .unwrap();
        assert!(compressed
            .fields
            .iter()
            .any(|field| field.name == "compressed_mass_properties_sample" && !field.editable));
        let packed = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkPackedVector3")
            .unwrap();
        assert!(packed
            .fields
            .iter()
            .any(|field| field.name == "packed_vector3_rows" && !field.editable));
        let hard_target = summary
            .hard_internal_evidence
            .targets
            .iter()
            .find(|target| target.key == "compressed_mass_properties")
            .unwrap();
        assert_eq!(hard_target.status, "open_observed_unproven");
        assert!(hard_target.present_in_file);
        assert!(hard_target
            .observed_types
            .contains(&"hkCompressedMassProperties".to_string()));
        let json = summary_to_json(&summary);
        assert!(json.contains("compressed_mass_properties_sample"));
        assert!(json.contains("packed_vector3_rows"));
        assert!(json.contains("\"hard_internal_evidence\""));
        assert!(json.contains("\"compressed_mass_properties\""));
    }

    #[test]
    fn decodes_scalar_arrays_and_enum_records() {
        let data = scalar_enum_hkx();
        let summary = parse_summary(&data);
        for (type_name, field_name) in [
            ("unsigned int", "uint32_values"),
            ("unsigned short", "uint16_values"),
            ("unsigned long long", "uint64_values"),
            ("hknpShapeType::Enum", "enum_or_flags_values"),
            ("hknpShape::FlagsEnum", "enum_or_flags_values"),
        ] {
            let object = summary
                .object_records
                .iter()
                .find(|record| record.type_name == type_name)
                .unwrap();
            assert!(
                object
                    .fields
                    .iter()
                    .any(|field| field.name == field_name && !field.editable),
                "missing {field_name} in {type_name}"
            );
        }
        let json = summary_to_json(&summary);
        assert!(json.contains("uint32_values"));
        assert!(json.contains("enum_or_flags_values"));
    }

    #[test]
    fn decodes_box_shape_layout_fields() {
        let data = box_hkx();
        let summary = parse_summary(&data);
        let box_shape = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpBoxShape")
            .unwrap();
        assert!(box_shape
            .fields
            .iter()
            .any(|field| field.name == "box_vertices_offset_count"
                && field.confidence == "strong inference"));
        assert!(box_shape
            .fields
            .iter()
            .any(|field| field.name == "convex_radius_or_collision_margin"
                && field.value == Some(LayoutValue::F32(0.015))));
        assert!(box_shape
            .fields
            .iter()
            .any(|field| field.name == "box_local_frame_or_extents"));
    }

    #[test]
    fn decodes_skeleton_and_material_support_layouts() {
        let data = skeleton_support_hkx();
        let summary = parse_summary(&data);
        for (type_name, field_name) in [
            ("HavokShapeNameProperty", "shape_name_reference"),
            ("hkQsTransform", "qs_transform[0]"),
            ("hkBone", "bone[0]"),
            ("hkInt16", "int16_values"),
            ("hkSkeleton", "bones_reference_or_count_pair"),
            ("hknpMaterial", "material[0]"),
            ("hknpMaterial", "material_surface_response_a[0]"),
        ] {
            let object = summary
                .object_records
                .iter()
                .find(|record| record.type_name == type_name)
                .unwrap();
            assert!(
                object.fields.iter().any(|field| field.name == field_name),
                "missing {field_name} in {type_name}"
            );
        }
    }

    #[test]
    fn decodes_skeleton_mapper_support_layouts() {
        let data = skeleton_mapper_support_hkx();
        let summary = parse_summary(&data);
        for (type_name, field_name) in [
            ("char", "ascii_or_utf8_text"),
            ("hkaSkeletonMapper", "source_skeleton_or_root_reference"),
            ("hkaSkeletonMapperData::SimpleMapping", "simple_mapping[0]"),
            ("hkaAnimationContainer", "animation_container_pair_0x18"),
            ("int", "int32_values"),
        ] {
            let object = summary
                .object_records
                .iter()
                .find(|record| record.type_name == type_name)
                .unwrap();
            assert!(
                object.fields.iter().any(|field| field.name == field_name),
                "missing {field_name} in {type_name}"
            );
        }
    }

    #[test]
    fn decodes_root_scene_and_constraint_container_layouts() {
        let data = root_container_hkx();
        let summary = parse_summary(&data);
        let root = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkRootLevelContainer")
            .unwrap();
        assert!(root
            .fields
            .iter()
            .any(|field| field.name == "named_variants_size"));
        let variant = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkRootLevelContainer::NamedVariant")
            .unwrap();
        assert!(variant
            .fields
            .iter()
            .any(|field| field.name == "object_reference"));
        let scene = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpPhysicsSceneData")
            .unwrap();
        assert!(scene
            .fields
            .iter()
            .any(|field| field.name == "u32_pair_0x0"));
        let constraint = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpConstraintCinfo")
            .unwrap();
        assert!(constraint
            .fields
            .iter()
            .any(|field| field.name == "body_a_reference_or_index_pair"));
        let graph = &summary.native_model_graph;
        assert_eq!(graph.root.record_index, Some(0));
        assert_eq!(graph.root.method, "native_hkRootLevelContainer");
        assert!(graph.owner_array_count >= 1);
        assert!(graph.owner_arrays.iter().any(|array| {
            array.owner_record_index == 0
                && array.field_name == "namedVariants"
                && array.array_type == "hkArray<hkRootLevelContainer::NamedVariant>"
                && array.numelements == Some(1)
        }));
        assert_eq!(graph.graph_order.first().copied(), Some(0));
    }

    #[test]
    fn decodes_root_reference_and_physics_system_payloads() {
        let data = root_reference_payload_hkx();
        let summary = parse_summary(&data);
        for (type_name, field_name) in [
            ("hkRefVariant", "referenced_value"),
            ("hkStringPtr", "reference_metadata_pair"),
            ("hkMemoryResourceContainer", "reference_or_value_pair_0x0"),
            ("hknpPhysicsSystemData", "materials_array_or_reference_pair"),
            ("hknpConstraintData", "reference_or_value_pair_0x0"),
            ("hknpRefDragProperties", "finite_float_candidates"),
            ("hknpRefMassDistribution", "finite_float_candidates"),
        ] {
            let object = summary
                .object_records
                .iter()
                .find(|record| record.type_name == type_name)
                .unwrap();
            assert!(
                object
                    .fields
                    .iter()
                    .any(|field| field.name == field_name && !field.editable),
                "missing {field_name} in {type_name}"
            );
        }
    }

    #[test]
    fn decodes_real_hkclass_member_metadata_records() {
        let data = real_hkclass_metadata_hkx();
        let summary = parse_summary(&data);
        let metadata = &summary.real_hkclass_metadata;

        assert_eq!(metadata.format, "cd_hkx_real_hkclass_metadata_v1");
        assert_eq!(metadata.status, "real_hkclass_records_decoded");
        assert_eq!(metadata.class_count, 1);
        assert_eq!(metadata.member_count, 2);
        assert_eq!(
            metadata.recovered_requirements.get("member_type_codes"),
            Some(&true)
        );
        assert_eq!(
            metadata.recovered_requirements.get("member_flags"),
            Some(&true)
        );
        assert_eq!(
            metadata.recovered_requirements.get("signatures"),
            Some(&true)
        );
        assert_eq!(metadata.recovered_requirements.get("versions"), Some(&true));
        assert_eq!(
            metadata.recovered_requirements.get("template_refs"),
            Some(&true)
        );

        let class_info = &metadata.classes[0];
        assert_eq!(class_info.name, "hknpFoo");
        assert_eq!(class_info.object_size, Some(64));
        assert_eq!(class_info.version, Some(3));
        assert_eq!(class_info.flags, Some(4));
        assert_eq!(class_info.signature, Some(0xABCDEF01));
        assert_eq!(class_info.declared_member_count, 2);
        assert_eq!(class_info.members_record_index, Some(4));
        let mass = class_info
            .members
            .iter()
            .find(|member| member.name == "mass")
            .unwrap();
        assert_eq!(mass.type_code, 11);
        assert_eq!(mass.type_name, "TYPE_REAL");
        assert_eq!(mass.flags, 0x1234);
        assert_eq!(mass.offset, 0x20);
        let child = class_info
            .members
            .iter()
            .find(|member| member.name == "child")
            .unwrap();
        assert_eq!(child.type_name, "TYPE_POINTER");
        assert_eq!(child.subtype_name, "TYPE_STRUCT");
        assert_eq!(child.class_ref_name.as_deref(), Some("hknpFoo"));
        assert_eq!(child.template_ref.as_deref(), Some("hknpFoo"));

        let json = summary_to_json(&summary);
        assert!(json.contains("\"real_hkclass_metadata\""));
        assert!(json.contains("\"real_hkclass_metadata_v2\""));
        assert!(json.contains("\"havok_member_type_code\":11"));
        assert!(json.contains("\"reference_status\":\"reference\""));
        assert!(json.contains("\"synthetic_fallback_required\":false"));
        assert!(json.contains("\"type_code\":11"));
        assert!(json.contains("\"flags_hex\":\"0x1234\""));
        assert!(json.contains("\"signature_hex\":\"0xABCDEF01\""));
    }

    #[test]
    fn decodes_body_and_constraint_reference_fields() {
        let data = body_constraint_reference_hkx();
        let summary = parse_summary(&data);
        for (type_name, field_name) in [
            (
                "hknpPhysicsSystemData",
                "body_cinfo_array_or_reference_pair",
            ),
            (
                "hknpPhysicsSystemData::ExtendedBodyCinfo",
                "shape_reference_or_key_pair",
            ),
            (
                "hknpPhysicsSystemData::ExtendedBodyCinfo",
                "motion_properties_reference_pair",
            ),
            (
                "hknpPhysicsSystemData::ExtendedBodyCinfo",
                "body_transform_or_orientation_row0_x[0]",
            ),
            ("hknpConstraintCinfo", "body_a_reference_or_index_pair"),
            ("hknpConstraintCinfo", "constraint_data_reference_pair"),
        ] {
            let object = summary
                .object_records
                .iter()
                .find(|record| record.type_name == type_name)
                .unwrap();
            assert!(
                object.fields.iter().any(|field| field.name == field_name),
                "missing {field_name} in {type_name}"
            );
        }
    }

    #[test]
    fn decodes_compound_tree_instance_and_property_blocker_layouts() {
        let data = compound_blocker_hkx();
        let summary = parse_summary(&data);
        let compound = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpCompoundShape")
            .unwrap();
        assert!(compound
            .fields
            .iter()
            .any(|field| field.name == "shape_instances_or_storage_pair"));
        let instance = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpShapeInstance")
            .unwrap();
        assert!(instance
            .fields
            .iter()
            .any(|field| field.name == "shape_instance[0]"));
        let node = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hkcdSimdTreeNamespace::Node")
            .unwrap();
        assert!(node
            .fields
            .iter()
            .any(|field| field.name == "simd_tree_node[0]"));
        let property = summary
            .object_records
            .iter()
            .find(|record| record.type_name == "hknpShapeProperties::Entry")
            .unwrap();
        assert!(property
            .fields
            .iter()
            .any(|field| field.name == "property_entry[0]"));
        let hard = &summary.hard_internal_evidence;
        assert_eq!(hard.format, "cd_hkx_hard_internal_evidence_v1");
        assert_eq!(hard.status, "hard_internals_observed_unproven");
        for key in [
            "compound_child_transforms",
            "hknp_mesh_aabb_tree",
            "material_property_entries",
            "compressed_mass_properties",
        ] {
            let target = hard
                .targets
                .iter()
                .find(|target| target.key == key)
                .unwrap();
            assert!(target.present_in_file, "missing hard target {key}");
            assert_eq!(target.proof_status, "needs_corpus_proof");
            assert!(!target.resolved);
            assert!(target.observed_record_count > 0);
        }
    }
}
