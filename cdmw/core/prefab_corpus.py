from __future__ import annotations

from cdmw.core.prefab_corpus_contracts import (
    EDIT_PROBES_DISABLED_REASON,
    NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON,
    NO_SAFE_RESOURCE_LENGTH_PROBE_REASON,
    OVERLAPPING_OFFSET_CANDIDATES_REASON,
    PREFAB_JSON_IMPORT_CORPUS_FORMAT,
    T,
)

from cdmw.core.prefab_corpus_array_metrics import (
    _array_descriptor_signature_counts,
    _array_descriptor_signature_offset_candidate_counts,
    _array_descriptor_signature_offset_candidate_target_counts,
    _array_descriptor_word_value_counts,
    _array_stride_hint_type_counts,
    _array_count_hint_type_counts,
    _array_count_hint_member_counts,
    _array_word3_relation_counts,
    _array_theoretical_payload_shape_counts,
    _span_overlaps,
    _member_descriptor_overlaps,
    _array_theoretical_payload_span_fit_metrics,
    _array_exact_payload_owner_counts,
    _array_word2_delta_member_counts,
    _array_word2_delta_word3_member_counts,
    _array_word2_delta_word3_member_offset_candidate_counts,
    _array_nonzero_word3_offset_candidate_status_counts,
    _array_classification_source_counts,
    _array_word3_category_counts,
)

from cdmw.core.prefab_corpus_audit import (
    audit_prefab_json_import_sample,
)

from cdmw.core.prefab_corpus_candidate_offsets_0 import (
    _offset_candidate_overlap_count,
    _offset_candidate_overlap_groups,
    _offset_candidate_group_metrics,
    _offset_candidate_metrics,
    _offset_candidate_outside_descriptor_metrics,
    _mod4_counts,
    _sum_count_maps,
    _offset_candidate_outside_descriptor_mod4_counts,
    _offset_candidate_neighbor_byte_class,
    _offset_candidate_neighbor_byte_class_counts,
    _offset_candidate_target_role_counts,
    _offset_candidate_target_role_kind_counts,
    _offset_candidate_target_role_kind_span_position_counts,
    _offset_candidate_target_role_kind_neighbor_byte_class_counts,
    _offset_candidate_target_role_kind_span_position_neighbor_byte_class_counts,
    _resource_reference_target_field_indexes,
    _outside_member_descriptor_offset_candidates,
    _outside_member_descriptor_resource_reference_offset_candidates,
    _outside_member_descriptor_preserved_middle_offset_candidates,
    _preserved_span_byte_length_bucket,
    _offset_candidate_preserved_span_byte_length_counts,
    _offset_candidate_outside_descriptor_target_role_counts,
    _offset_candidate_outside_descriptor_resource_reference_metrics,
    _offset_candidate_alignment_target_kind_counts,
    _aligned_isolated_offset_candidates,
    _offset_candidate_outside_descriptor_preserved_middle_metrics,
    _offset_candidate_resource_reference_mod4_counts,
    _offset_candidate_resource_reference_alignment_target_kind_counts,
    _offset_candidate_resource_reference_alignment_target_kind_extension_counts,
    _offset_candidate_resource_reference_alignment_target_kind_role_counts,
    _offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts,
    _preserved_span_position_bucket,
    _offset_candidate_resource_reference_alignment_target_kind_span_position_counts,
    _offset_candidate_resource_reference_target_profile_span_position_counts,
    _offset_candidate_signed_distance_bucket,
    _offset_candidate_target_role_kind_signed_distance_counts,
    _offset_candidate_resource_reference_target_profile_distance_counts,
    _offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts,
    _offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts,
    _offset_candidate_preserved_span_shape_counts,
)

from cdmw.core.prefab_corpus_candidate_offsets_1 import (
    _offset_candidate_resource_reference_span_metrics,
    _offset_candidate_outside_descriptor_aligned_isolated_span_metrics,
    _offset_candidate_descriptor_metrics,
    _candidate_member_descriptor_owner,
    _candidate_member_descriptor_owner_from_declarations,
    _offset_candidate_span_metrics,
    _offset_candidates_remapped_after_resize,
    _offset_candidate_remap_metrics_after_resize,
)

from cdmw.core.prefab_corpus_candidate_roles import (
    _editable_row_record_end,
    _string_field_role,
    _string_field_relation_to_declaration,
    _member_descriptor_relation_to_declaration,
    _candidate_target_role,
    _offset_candidate_targets_edit_metadata,
    _candidate_owner_kind,
    _candidate_target_text,
    _candidate_resource_reference_extension,
    _candidate_resource_reference_name,
    _top_count_map,
    _resize_impact_offset_candidate_target_role_kind_counts,
    _resize_impact_offset_candidate_owner_kind_target_counts,
    _candidate_identity,
    _unique_offset_candidates,
    _resize_impact_offset_candidate_multiplicities,
    _resize_impact_offset_candidates,
    _resize_impact_resource_reference_candidate_multiplicities,
    _resize_impact_resource_reference_candidates,
    _resize_impact_unique_offset_candidate_count,
    _resize_impact_unique_offset_candidate_target_role_kind_counts,
    _resize_impact_unique_offset_candidate_owner_kind_target_counts,
)

from cdmw.core.prefab_corpus_descriptor_metrics_0 import (
    _transform_descriptor_signature_counts,
    _transform_descriptor_signature_offset_candidate_counts,
    _nonzero_word3_offset_candidate_status_counts,
    _descriptor_kind_nonzero_word3_offset_candidate_status_counts,
    _descriptor_kind_nonzero_word3_offset_candidate_target_counts,
    _transform_descriptor_signature_offset_candidate_target_counts,
    _nonzero_word3_offset_candidate_target_counts,
    _transform_descriptor_word_value_counts,
    _transform_theoretical_payload_shape_counts,
    _transform_theoretical_payload_span_fit_metrics,
    _transform_exact_payload_owner_counts,
    _reference_descriptor_signature_counts,
    _reference_descriptor_signature_offset_candidate_counts,
    _reference_descriptor_signature_offset_candidate_target_counts,
    _scalar_or_bool_descriptor_signature_counts,
    _scalar_or_bool_descriptor_signature_offset_candidate_counts,
    _scalar_or_bool_descriptor_signature_offset_candidate_target_counts,
    _string_descriptor_signature_counts,
    _string_descriptor_signature_offset_candidate_counts,
    _string_descriptor_signature_offset_candidate_target_counts,
    _generic_descriptor_signature_counts,
    _generic_descriptor_signature_offset_candidate_counts,
    _generic_descriptor_signature_offset_candidate_target_counts,
    _descriptor_owner_kind_offset_candidate_counts,
    _descriptor_owner_kind_offset_candidate_target_counts,
    _descriptor_tail_metrics,
    _descriptor_tail_kind_metrics,
    _descriptor_tail_member_detail_counts,
    _reference_descriptor_tail_record_shape_counts,
    _reference_descriptor_tail_offset_candidate_mod_counts,
)

from cdmw.core.prefab_corpus_descriptor_metrics_1 import (
    _reference_descriptor_tail_record_profile_counts,
    _reference_descriptor_tail_numeric_profile_counts,
    _reference_descriptor_tail_column_profile_counts,
    _preserved_span_metrics,
)

from cdmw.core.prefab_corpus_edit_probes import (
    _audit_same_length_resource_edit_probe,
    _audit_same_length_placement_edit_probe,
    _audit_experimental_length_change_placement_rebuild_probe,
    _audit_experimental_length_change_resource_rebuild_probe,
)

from cdmw.core.prefab_corpus_loading import (
    discover_loose_prefab_corpus_paths,
    _path_label,
    _select_corpus_samples,
    _select_corpus_scan_items,
    build_prefab_json_import_corpus_report,
    build_prefab_json_import_archive_entry_report,
)

from cdmw.core.prefab_corpus_probe_metrics import (
    _policy_resize_readiness,
    _probe_reason_counts,
    _probe_count_map,
    _probe_top_count_map,
    _probe_int_sum,
    _probe_value_counts,
    _probe_status_value_counts,
    _audit_report_only_array_count_hint_mutation_probe,
    _audit_report_only_transform_word3_mutation_probe,
    _audit_report_only_reference_word3_mutation_probe,
    _audit_report_only_preserved_unknown_byte_mutation_probe,
    _audit_report_only_descriptor_word3_mutation_probe,
    _skipped_probe_results,
)

from cdmw.core.prefab_corpus_probe_values import (
    _same_length_probe_value,
    _longer_probe_value,
    _same_length_placement_probe_value,
    _longer_placement_probe_value,
    _changed_only_expected_ranges,
    _expected_length_changed_bytes,
    _effective_offset_value_replacements_after_resize,
    _resize_impact_offset_candidate_count,
    _length_change_plan_counts,
)

from cdmw.core.prefab_corpus_publication import (
    discover_prefab_archive_entries,
    _read_archive_entry_payload,
    build_prefab_json_import_archive_entry_json,
    build_prefab_json_import_corpus_json,
)

from cdmw.core.prefab_corpus_report import (
    _report_from_rows,
    _summary_mapping,
    _merge_coverage,
    merge_prefab_json_import_corpus_reports,
)

from cdmw.core.prefab_corpus_resize_impact_0 import (
    _selected_resize_offset_candidate_metrics,
    _resize_impact_unique_offset_candidate_overlap_counts,
    _resize_impact_unique_offset_candidate_profile_counts,
    _resize_impact_unique_offset_candidate_overlap_profile_counts,
    _resize_impact_unique_offset_candidate_overlap_group_profile_counts,
    _resize_impact_unique_offset_candidate_overlap_group_target_identity_counts,
    _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts,
    _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts,
    _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts,
    _resize_impact_unique_offset_candidate_same_target_resource_alias_counts,
    _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts,
    _mixed_target_shift_consistent_overlap_groups,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts,
    _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_overlap_blocker_profile_counts,
    _candidate_target_identity_key,
)

from cdmw.core.prefab_corpus_resize_impact_1 import (
    _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts,
    _identity_repeat_summary,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts,
    _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts,
    _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_shape_counts,
    _resize_impact_resource_reference_target_profile_distance_counts,
    _resize_impact_unique_resource_reference_target_profile_distance_counts,
    _resize_impact_resource_reference_target_profile_span_position_counts,
    _resize_impact_resource_reference_target_profile_neighbor_byte_class_counts,
)


__all__ = ['PREFAB_JSON_IMPORT_CORPUS_FORMAT', 'audit_prefab_json_import_sample', 'build_prefab_json_import_archive_entry_json', 'build_prefab_json_import_archive_entry_report', 'build_prefab_json_import_corpus_json', 'build_prefab_json_import_corpus_report', 'discover_prefab_archive_entries', 'discover_loose_prefab_corpus_paths', 'merge_prefab_json_import_corpus_reports']
