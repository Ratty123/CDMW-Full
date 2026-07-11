from __future__ import annotations

import json
import math
import struct
import time
from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, TypeVar

from cdmw.core.common import raise_if_cancelled
from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import decode_prefab, rebuild_prefab_no_edit
from cdmw.core.prefab_json import (
    PrefabEditJsonError,
    apply_prefab_edit_document,
    build_prefab_edit_document,
    rebuild_prefab_no_edit_from_edit_document,
)
from cdmw.models import ArchiveEntry
from cdmw.core.prefab_corpus_contracts import (
    EDIT_PROBES_DISABLED_REASON,
    NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON,
    NO_SAFE_RESOURCE_LENGTH_PROBE_REASON,
    OVERLAPPING_OFFSET_CANDIDATES_REASON,
    PREFAB_JSON_IMPORT_CORPUS_FORMAT,
    T,
)


def _build_audit_error_row_part_3(state, exc) -> dict[str, object]:
    result = {}
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts': {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts': {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts': {'ascii_like': 0, 'binary_like': 0, 'empty': 0, 'nul_rich': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts': {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}})
    result.update({'offset_candidate_in_preserved_span_count': 0})
    result.update({'offset_candidate_outside_preserved_span_count': 0})
    result.update({'offset_candidate_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_at_preserved_span_start_count': 0})
    result.update({'offset_candidate_at_preserved_span_end_count': 0})
    result.update({'offset_candidate_in_preserved_span_middle_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_count': 0})
    result.update({'largest_preserved_span_byte_count': 0})
    result.update({'preserved_span_with_offset_candidate_count': 0})
    result.update({'preserved_span_without_offset_candidate_count': 0})
    result.update({'member_descriptor_preserved_bytes': 0})
    result.update({'member_descriptor_header_preserved_bytes': 0})
    result.update({'member_descriptor_tail_preserved_bytes': 0})
    result.update({'preserved_unknown_bytes_excluding_member_descriptors': 0})
    result.update({'preserved_unknown_bytes_excluding_member_descriptor_headers': 0})
    result.update({'preserved_unknown_bytes_without_block_semantics': 0})
    result.update({'preserved_span_with_member_descriptor_count': 0})
    result.update({'preserved_span_without_member_descriptor_count': 0})
    result.update({'reference_count': 0})
    result.update({'editable_reference_count': 0})
    result.update({'editable_placement_field_count': 0})
    return result


def _build_audit_error_row_part_4(state, exc) -> dict[str, object]:
    result = {}
    result.update({'resource_resize_impact_offset_candidate_count': 0})
    result.update({'placement_resize_impact_offset_candidate_count': 0})
    result.update({'resource_resize_impact_target_role_kind_counts': {}})
    result.update({'placement_resize_impact_target_role_kind_counts': {}})
    result.update({'resource_resize_impact_owner_kind_target_counts': {}})
    result.update({'placement_resize_impact_owner_kind_target_counts': {}})
    result.update({'resource_resize_impact_resource_reference_target_profile_distance_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_distance_counts': {}})
    result.update({'resource_resize_impact_resource_reference_target_profile_span_position_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_span_position_counts': {}})
    result.update({'resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'resource_resize_impact_unique_offset_candidate_count': 0})
    result.update({'placement_resize_impact_unique_offset_candidate_count': 0})
    result.update({'resource_resize_impact_unique_target_role_kind_counts': {}})
    result.update({'placement_resize_impact_unique_target_role_kind_counts': {}})
    result.update({'resource_resize_impact_unique_owner_kind_target_counts': {}})
    result.update({'placement_resize_impact_unique_owner_kind_target_counts': {}})
    result.update({'resource_resize_impact_unique_candidate_profile_counts': {}})
    result.update({'placement_resize_impact_unique_candidate_profile_counts': {}})
    result.update({'resource_resize_impact_unique_resource_reference_target_profile_distance_counts': {}})
    result.update({'placement_resize_impact_unique_resource_reference_target_profile_distance_counts': {}})
    result.update({'policy_resize_readiness': {}})
    result.update({'length_change_tail_only_candidate_count': 0})
    result.update({'length_change_downstream_rebuild_row_count': 0})
    result.update({'length_change_offset_rebuild_row_count': 0})
    result.update({'layout_rebuild_byte_identical': False})
    result.update({'json_layout_rebuild_byte_identical': False})
    result.update({'no_edit_roundtrip_byte_identical': False})
    result.update({'same_length_resource_edit_probe': {'status': 'failed', 'edited_reference_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}})
    result.update({'same_length_placement_edit_probe': {'status': 'failed', 'edited_field_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}})
    result.update({'experimental_length_change_resource_rebuild_probe': {'status': 'failed', 'edited_reference_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': False, 'replacement_reference_found': False, 'error': str(exc)}})
    result.update({'experimental_length_change_placement_rebuild_probe': {'status': 'failed', 'edited_field_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_low_level_profile_patch': False, 'replacement_field_found': False, 'error': str(exc)}})
    result.update({'report_only_array_count_hint_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_count_hint': 0, 'new_count_hint': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_count_hint_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_transform_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_reference_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_preserved_unknown_byte_mutation_probe': {'status': 'failed', 'span_index': -1, 'span_start': -1, 'span_end': -1, 'mutation_offset': -1, 'old_byte': 0, 'new_byte': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_byte_changed': False, 'span_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_descriptor_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_kind': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'elapsed_ms': round((time.perf_counter() - state['started']) * 1000, 3)})
    result.update({'error': str(exc)})
    return result


def _build_audit_error_row(state, exc) -> dict[str, object]:
    from cdmw.core.prefab_corpus_audit_rows_0 import _build_audit_error_row_part_0, _build_audit_error_row_part_1, _build_audit_error_row_part_2
    result: dict[str, object] = {}
    result.update(_build_audit_error_row_part_0(state, exc))
    result.update(_build_audit_error_row_part_1(state, exc))
    result.update(_build_audit_error_row_part_2(state, exc))
    result.update(_build_audit_error_row_part_3(state, exc))
    result.update(_build_audit_error_row_part_4(state, exc))
    return result
