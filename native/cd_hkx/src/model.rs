use std::collections::BTreeMap;

pub(crate) const TAG_ITEM_MARKERS: [&str; 10] = [
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
