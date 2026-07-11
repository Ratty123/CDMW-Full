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


def _report_from_rows_stage_0(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    from cdmw.core.prefab_corpus_resize_impact_1 import _identity_repeat_summary
    rows, = (state['rows'],)
    passed = sum((1 for row in rows if row.get('status') == 'passed'))
    failed = len(rows) - passed
    layout_rebuild_passed = sum((1 for row in rows if row.get('layout_rebuild_byte_identical') is True))
    layout_rebuild_failed = len(rows) - layout_rebuild_passed
    json_layout_rebuild_passed = sum((1 for row in rows if row.get('json_layout_rebuild_byte_identical') is True))
    json_layout_rebuild_failed = len(rows) - json_layout_rebuild_passed
    editable_reference_count = sum((int(row.get('editable_reference_count') or 0) for row in rows))
    editable_placement_field_count = sum((int(row.get('editable_placement_field_count') or 0) for row in rows))
    resource_resize_impact_count = sum((int(row.get('resource_resize_impact_offset_candidate_count') or 0) for row in rows))
    placement_resize_impact_count = sum((int(row.get('placement_resize_impact_offset_candidate_count') or 0) for row in rows))
    resource_resize_impact_target_role_kind_counts = _sum_count_maps(rows, 'resource_resize_impact_target_role_kind_counts', {})
    placement_resize_impact_target_role_kind_counts = _sum_count_maps(rows, 'placement_resize_impact_target_role_kind_counts', {})
    resource_resize_impact_owner_kind_target_counts = _sum_count_maps(rows, 'resource_resize_impact_owner_kind_target_counts', {})
    placement_resize_impact_owner_kind_target_counts = _sum_count_maps(rows, 'placement_resize_impact_owner_kind_target_counts', {})
    resource_resize_impact_resource_reference_target_profile_distance_counts = _sum_count_maps(rows, 'resource_resize_impact_resource_reference_target_profile_distance_counts', {})
    placement_resize_impact_resource_reference_target_profile_distance_counts = _sum_count_maps(rows, 'placement_resize_impact_resource_reference_target_profile_distance_counts', {})
    resource_resize_impact_resource_reference_target_profile_span_position_counts = _sum_count_maps(rows, 'resource_resize_impact_resource_reference_target_profile_span_position_counts', {})
    placement_resize_impact_resource_reference_target_profile_span_position_counts = _sum_count_maps(rows, 'placement_resize_impact_resource_reference_target_profile_span_position_counts', {})
    resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = _sum_count_maps(rows, 'resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts', {})
    placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts = _sum_count_maps(rows, 'placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts', {})
    resource_resize_impact_unique_offset_candidate_count = sum((int(row.get('resource_resize_impact_unique_offset_candidate_count') or 0) for row in rows))
    placement_resize_impact_unique_offset_candidate_count = sum((int(row.get('placement_resize_impact_unique_offset_candidate_count') or 0) for row in rows))
    resource_resize_impact_unique_target_role_kind_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_target_role_kind_counts', {})
    placement_resize_impact_unique_target_role_kind_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_target_role_kind_counts', {})
    resource_resize_impact_unique_owner_kind_target_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_owner_kind_target_counts', {})
    placement_resize_impact_unique_owner_kind_target_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_owner_kind_target_counts', {})
    resource_resize_impact_unique_candidate_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_candidate_profile_counts', {})
    placement_resize_impact_unique_candidate_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_candidate_profile_counts', {})
    resource_resize_impact_unique_overlap_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_overlap_profile_counts', {})
    placement_resize_impact_unique_overlap_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_overlap_profile_counts', {})
    resource_resize_impact_unique_overlap_group_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_overlap_group_profile_counts', {})
    placement_resize_impact_unique_overlap_group_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_overlap_group_profile_counts', {})
    resource_resize_impact_unique_overlap_group_target_identity_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_overlap_group_target_identity_counts', {})
    placement_resize_impact_unique_overlap_group_target_identity_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_overlap_group_target_identity_counts', {})
    collapse_defaults = {}
    collapse_defaults.update({'impacted_overlap_group_count': 0, 'impacted_overlap_candidate_count': 0})
    collapse_defaults.update({'same_target_duplicate_group_count': 0, 'same_target_duplicate_candidate_count': 0})
    collapse_defaults.update({'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0})
    collapse_defaults.update({'blocker_group_count_after_same_target_collapse': 0, 'blocker_candidate_count_after_same_target_collapse': 0})
    resource_resize_impact_unique_same_target_overlap_collapse_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_same_target_overlap_collapse_counts', collapse_defaults)
    placement_resize_impact_unique_same_target_overlap_collapse_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_same_target_overlap_collapse_counts', collapse_defaults)
    shift_conflict_defaults = {}
    shift_conflict_defaults.update({'same_target_overlap_group_count': 0, 'same_target_overlap_candidate_count': 0})
    shift_conflict_defaults.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    shift_conflict_defaults.update({'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0})
    resource_resize_impact_unique_same_target_overlap_shift_conflict_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_same_target_overlap_shift_conflict_counts', shift_conflict_defaults)
    placement_resize_impact_unique_same_target_overlap_shift_conflict_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_same_target_overlap_shift_conflict_counts', shift_conflict_defaults)
    resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts', {})
    placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts', {})
    same_target_alias_defaults = {}
    same_target_alias_defaults.update({'same_target_conflict_group_count': 0, 'same_target_conflict_candidate_count': 0})
    same_target_alias_defaults.update({'resource_alias_group_count': 0, 'resource_alias_candidate_count': 0})
    same_target_alias_defaults.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    resource_resize_impact_unique_same_target_resource_alias_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_same_target_resource_alias_counts', same_target_alias_defaults)
    placement_resize_impact_unique_same_target_resource_alias_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_same_target_resource_alias_counts', same_target_alias_defaults)
    mixed_shift_conflict_defaults = {}
    mixed_shift_conflict_defaults.update({'mixed_target_overlap_group_count': 0, 'mixed_target_overlap_candidate_count': 0})
    mixed_shift_conflict_defaults.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    mixed_shift_conflict_defaults.update({'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0})
    resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts', mixed_shift_conflict_defaults)
    placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts', mixed_shift_conflict_defaults)
    resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts', {})
    placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts', {})
    resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts', {})
    placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts', {})
    resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts', {})
    placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts', {})
    resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts', {})
    placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts', {})
    metadata_collision_defaults = {}
    metadata_collision_defaults.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    metadata_collision_defaults.update({'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0})
    metadata_collision_defaults.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts', metadata_collision_defaults)
    placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts', metadata_collision_defaults)
    resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts', {})
    placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts', {})
    resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts', {})
    placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts', {})
    resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = _identity_repeat_summary(resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts)
    placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary = _identity_repeat_summary(placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts)
    high_repeat_collapse_defaults = {}
    high_repeat_collapse_defaults.update({'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0})
    high_repeat_collapse_defaults.update({'high_repeat_identity_count': 0, 'high_repeat_candidate_count': 0})
    high_repeat_collapse_defaults.update({'remaining_group_count_after_high_repeat_collapse': 0, 'remaining_candidate_count_after_high_repeat_collapse': 0})
    resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts', high_repeat_collapse_defaults)
    placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts', high_repeat_collapse_defaults)
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts', {})
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts', {})
    result = {}
    result.update({'editable_placement_field_count': editable_placement_field_count, 'editable_reference_count': editable_reference_count, 'failed': failed, 'json_layout_rebuild_failed': json_layout_rebuild_failed, 'json_layout_rebuild_passed': json_layout_rebuild_passed})
    result.update({'layout_rebuild_failed': layout_rebuild_failed, 'layout_rebuild_passed': layout_rebuild_passed, 'passed': passed, 'placement_resize_impact_count': placement_resize_impact_count, 'placement_resize_impact_owner_kind_target_counts': placement_resize_impact_owner_kind_target_counts})
    result.update({'placement_resize_impact_resource_reference_target_profile_distance_counts': placement_resize_impact_resource_reference_target_profile_distance_counts, 'placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts, 'placement_resize_impact_resource_reference_target_profile_span_position_counts': placement_resize_impact_resource_reference_target_profile_span_position_counts, 'placement_resize_impact_target_role_kind_counts': placement_resize_impact_target_role_kind_counts, 'placement_resize_impact_unique_candidate_profile_counts': placement_resize_impact_unique_candidate_profile_counts})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts, 'placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts': placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts, 'placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts': placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts, 'placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary': placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts': placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts, 'placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts': placement_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts, 'placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts': placement_resize_impact_unique_mixed_target_shift_consistent_identity_counts, 'placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts': placement_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts, 'placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts': placement_resize_impact_unique_mixed_target_shift_consistent_profile_counts})
    result.update({'placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts': placement_resize_impact_unique_mixed_target_shift_consistent_shape_counts, 'placement_resize_impact_unique_offset_candidate_count': placement_resize_impact_unique_offset_candidate_count, 'placement_resize_impact_unique_overlap_group_profile_counts': placement_resize_impact_unique_overlap_group_profile_counts, 'placement_resize_impact_unique_overlap_group_target_identity_counts': placement_resize_impact_unique_overlap_group_target_identity_counts, 'placement_resize_impact_unique_overlap_profile_counts': placement_resize_impact_unique_overlap_profile_counts})
    result.update({'placement_resize_impact_unique_owner_kind_target_counts': placement_resize_impact_unique_owner_kind_target_counts, 'placement_resize_impact_unique_same_target_overlap_collapse_counts': placement_resize_impact_unique_same_target_overlap_collapse_counts, 'placement_resize_impact_unique_same_target_overlap_shift_conflict_counts': placement_resize_impact_unique_same_target_overlap_shift_conflict_counts, 'placement_resize_impact_unique_same_target_resource_alias_counts': placement_resize_impact_unique_same_target_resource_alias_counts, 'placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts': placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts})
    result.update({'placement_resize_impact_unique_target_role_kind_counts': placement_resize_impact_unique_target_role_kind_counts, 'resource_resize_impact_count': resource_resize_impact_count, 'resource_resize_impact_owner_kind_target_counts': resource_resize_impact_owner_kind_target_counts, 'resource_resize_impact_resource_reference_target_profile_distance_counts': resource_resize_impact_resource_reference_target_profile_distance_counts, 'resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts})
    result.update({'resource_resize_impact_resource_reference_target_profile_span_position_counts': resource_resize_impact_resource_reference_target_profile_span_position_counts, 'resource_resize_impact_target_role_kind_counts': resource_resize_impact_target_role_kind_counts, 'resource_resize_impact_unique_candidate_profile_counts': resource_resize_impact_unique_candidate_profile_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts': resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts, 'resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts': resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts, 'resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary': resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary, 'resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts': resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts, 'resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts': resource_resize_impact_unique_mixed_target_shift_consistent_group_detail_counts})
    result.update({'resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts': resource_resize_impact_unique_mixed_target_shift_consistent_identity_counts, 'resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts': resource_resize_impact_unique_mixed_target_shift_consistent_metadata_collision_counts, 'resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts': resource_resize_impact_unique_mixed_target_shift_consistent_profile_counts, 'resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts': resource_resize_impact_unique_mixed_target_shift_consistent_shape_counts, 'resource_resize_impact_unique_offset_candidate_count': resource_resize_impact_unique_offset_candidate_count})
    result.update({'resource_resize_impact_unique_overlap_group_profile_counts': resource_resize_impact_unique_overlap_group_profile_counts, 'resource_resize_impact_unique_overlap_group_target_identity_counts': resource_resize_impact_unique_overlap_group_target_identity_counts, 'resource_resize_impact_unique_overlap_profile_counts': resource_resize_impact_unique_overlap_profile_counts, 'resource_resize_impact_unique_owner_kind_target_counts': resource_resize_impact_unique_owner_kind_target_counts, 'resource_resize_impact_unique_same_target_overlap_collapse_counts': resource_resize_impact_unique_same_target_overlap_collapse_counts})
    result.update({'resource_resize_impact_unique_same_target_overlap_shift_conflict_counts': resource_resize_impact_unique_same_target_overlap_shift_conflict_counts, 'resource_resize_impact_unique_same_target_resource_alias_counts': resource_resize_impact_unique_same_target_resource_alias_counts, 'resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts': resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts, 'resource_resize_impact_unique_target_role_kind_counts': resource_resize_impact_unique_target_role_kind_counts})
    return result


def _report_from_rows_stage_1(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    rows, = (state['rows'],)
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts', {})
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts', {})
    high_repeat_remaining_role_defaults = {}
    high_repeat_remaining_role_defaults.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    high_repeat_remaining_role_defaults.update({'remaining_resource_reference_candidate_count': 0, 'remaining_metadata_candidate_count': 0})
    high_repeat_remaining_role_defaults.update({'remaining_resource_reference_group_count': 0, 'remaining_metadata_only_group_count': 0})
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts', high_repeat_remaining_role_defaults)
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts', high_repeat_remaining_role_defaults)
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts', {})
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts', {})
    rr_metadata_collision_defaults = {}
    rr_metadata_collision_defaults.update({'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0})
    rr_metadata_collision_defaults.update({'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0})
    rr_metadata_collision_defaults.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts', rr_metadata_collision_defaults)
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts', rr_metadata_collision_defaults)
    rr_nonimpacted_reference_collision_defaults = {}
    rr_nonimpacted_reference_collision_defaults.update({'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0})
    rr_nonimpacted_reference_collision_defaults.update({'nonimpacted_reference_collision_group_count': 0, 'nonimpacted_reference_collision_candidate_count': 0})
    rr_nonimpacted_reference_collision_defaults.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts', rr_nonimpacted_reference_collision_defaults)
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts', rr_nonimpacted_reference_collision_defaults)
    resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts', {})
    placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts', {})
    resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts', {})
    placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts', {})
    resource_resize_impact_unique_resource_reference_target_profile_distance_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_resource_reference_target_profile_distance_counts', {})
    placement_resize_impact_unique_resource_reference_target_profile_distance_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_resource_reference_target_profile_distance_counts', {})
    overlap_defaults = {'non_overlapping_count': 0, 'overlapping_count': 0}
    resource_resize_impact_unique_overlap_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_overlap_counts', overlap_defaults)
    placement_resize_impact_unique_overlap_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_overlap_counts', overlap_defaults)
    resource_resize_impact_unique_resource_reference_overlap_counts = _sum_count_maps(rows, 'resource_resize_impact_unique_resource_reference_overlap_counts', overlap_defaults)
    placement_resize_impact_unique_resource_reference_overlap_counts = _sum_count_maps(rows, 'placement_resize_impact_unique_resource_reference_overlap_counts', overlap_defaults)
    length_change_tail_only_candidate_count = sum((int(row.get('length_change_tail_only_candidate_count') or 0) for row in rows))
    length_change_downstream_rebuild_row_count = sum((int(row.get('length_change_downstream_rebuild_row_count') or 0) for row in rows))
    length_change_offset_rebuild_row_count = sum((int(row.get('length_change_offset_rebuild_row_count') or 0) for row in rows))
    policy_resize_readiness_editable_rows = 0
    policy_resize_readiness_impacted_rows = 0
    policy_resize_readiness_offset_candidate_rows = 0
    policy_length_changing_ready_files = 0
    files_with_policy_resize_impacts = 0
    for row in rows:
        readiness = row.get('policy_resize_readiness')
        if not isinstance(readiness, Mapping):
            continue
        policy_resize_readiness_editable_rows += int(readiness.get('editable_row_count') or 0)
        impacted_rows = int(readiness.get('editable_rows_with_resize_impact') or 0)
        policy_resize_readiness_impacted_rows += impacted_rows
        affected_offsets = int(readiness.get('affected_offset_candidate_rows') or 0)
        policy_resize_readiness_offset_candidate_rows += affected_offsets
        if affected_offsets:
            files_with_policy_resize_impacts += 1
        if readiness.get('length_changing_import_ready') is True:
            policy_length_changing_ready_files += 1
    member_declaration_count = sum((int(row.get('member_declaration_count') or 0) for row in rows))
    member_descriptor_bytes = sum((int(row.get('member_descriptor_bytes') or 0) for row in rows))
    descriptor_tail_member_kind_counts = _sum_count_maps(rows, 'descriptor_tail_member_kind_counts', {})
    descriptor_tail_byte_kind_counts = _sum_count_maps(rows, 'descriptor_tail_byte_kind_counts', {})
    descriptor_tail_member_detail_counts = _sum_count_maps(rows, 'descriptor_tail_member_detail_counts', {})
    transform_member_count = sum((int(row.get('transform_member_count') or 0) for row in rows))
    decoded_transform_payload_value_rows = sum((int(row.get('decoded_transform_payload_value_rows') or 0) for row in rows))
    transform_members_without_payload_values = sum((int(row.get('transform_members_without_payload_values') or 0) for row in rows))
    transform_members_with_descriptor_tail_bytes = sum((int(row.get('transform_members_with_descriptor_tail_bytes') or 0) for row in rows))
    transform_descriptor_tail_bytes = sum((int(row.get('transform_descriptor_tail_bytes') or 0) for row in rows))
    transform_theoretical_payload_member_rows = sum((int(row.get('transform_theoretical_payload_member_rows') or 0) for row in rows))
    transform_theoretical_payload_byte_count = sum((int(row.get('transform_theoretical_payload_byte_count') or 0) for row in rows))
    transform_theoretical_payload_exact_preserved_span_rows = sum((int(row.get('transform_theoretical_payload_exact_preserved_span_rows') or 0) for row in rows))
    transform_theoretical_payload_later_preserved_span_fit_rows = sum((int(row.get('transform_theoretical_payload_later_preserved_span_fit_rows') or 0) for row in rows))
    transform_theoretical_payload_no_preserved_span_fit_rows = sum((int(row.get('transform_theoretical_payload_no_preserved_span_fit_rows') or 0) for row in rows))
    transform_theoretical_payload_immediate_window_string_span_overlap_rows = sum((int(row.get('transform_theoretical_payload_immediate_window_string_span_overlap_rows') or 0) for row in rows))
    transform_theoretical_payload_immediate_window_string_span_overlap_count = sum((int(row.get('transform_theoretical_payload_immediate_window_string_span_overlap_count') or 0) for row in rows))
    transform_theoretical_payload_immediate_window_string_span_role_counts = _sum_count_maps(rows, 'transform_theoretical_payload_immediate_window_string_span_role_counts', {})
    transform_theoretical_payload_immediate_window_string_span_relation_counts = _sum_count_maps(rows, 'transform_theoretical_payload_immediate_window_string_span_relation_counts', {})
    transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows = sum((int(row.get('transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows') or 0) for row in rows))
    transform_theoretical_payload_later_fit_gap_string_span_relation_counts = _sum_count_maps(rows, 'transform_theoretical_payload_later_fit_gap_string_span_relation_counts', {})
    transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts = _sum_count_maps(rows, 'transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts', {})
    transform_name_only_member_count = sum((int(row.get('transform_name_only_member_count') or 0) for row in rows))
    transform_descriptor_signature_counts: dict[str, int] = {}
    transform_descriptor_signature_offset_candidate_counts: dict[str, int] = {}
    result = {}
    result.update({'decoded_transform_payload_value_rows': decoded_transform_payload_value_rows, 'descriptor_tail_byte_kind_counts': descriptor_tail_byte_kind_counts, 'descriptor_tail_member_detail_counts': descriptor_tail_member_detail_counts, 'descriptor_tail_member_kind_counts': descriptor_tail_member_kind_counts, 'files_with_policy_resize_impacts': files_with_policy_resize_impacts})
    result.update({'length_change_downstream_rebuild_row_count': length_change_downstream_rebuild_row_count, 'length_change_offset_rebuild_row_count': length_change_offset_rebuild_row_count, 'length_change_tail_only_candidate_count': length_change_tail_only_candidate_count, 'member_declaration_count': member_declaration_count, 'member_descriptor_bytes': member_descriptor_bytes})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts, 'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts': placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts, 'placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts': placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts, 'placement_resize_impact_unique_overlap_counts': placement_resize_impact_unique_overlap_counts, 'placement_resize_impact_unique_resource_reference_overlap_counts': placement_resize_impact_unique_resource_reference_overlap_counts, 'placement_resize_impact_unique_resource_reference_target_profile_distance_counts': placement_resize_impact_unique_resource_reference_target_profile_distance_counts})
    result.update({'policy_length_changing_ready_files': policy_length_changing_ready_files, 'policy_resize_readiness_editable_rows': policy_resize_readiness_editable_rows, 'policy_resize_readiness_impacted_rows': policy_resize_readiness_impacted_rows, 'policy_resize_readiness_offset_candidate_rows': policy_resize_readiness_offset_candidate_rows, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts, 'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts': resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts': resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts, 'resource_resize_impact_unique_overlap_counts': resource_resize_impact_unique_overlap_counts, 'resource_resize_impact_unique_resource_reference_overlap_counts': resource_resize_impact_unique_resource_reference_overlap_counts, 'resource_resize_impact_unique_resource_reference_target_profile_distance_counts': resource_resize_impact_unique_resource_reference_target_profile_distance_counts, 'transform_descriptor_signature_counts': transform_descriptor_signature_counts})
    result.update({'transform_descriptor_signature_offset_candidate_counts': transform_descriptor_signature_offset_candidate_counts, 'transform_descriptor_tail_bytes': transform_descriptor_tail_bytes, 'transform_member_count': transform_member_count, 'transform_members_with_descriptor_tail_bytes': transform_members_with_descriptor_tail_bytes, 'transform_members_without_payload_values': transform_members_without_payload_values})
    result.update({'transform_name_only_member_count': transform_name_only_member_count, 'transform_theoretical_payload_byte_count': transform_theoretical_payload_byte_count, 'transform_theoretical_payload_exact_preserved_span_rows': transform_theoretical_payload_exact_preserved_span_rows, 'transform_theoretical_payload_immediate_window_string_span_overlap_count': transform_theoretical_payload_immediate_window_string_span_overlap_count, 'transform_theoretical_payload_immediate_window_string_span_overlap_rows': transform_theoretical_payload_immediate_window_string_span_overlap_rows})
    result.update({'transform_theoretical_payload_immediate_window_string_span_relation_counts': transform_theoretical_payload_immediate_window_string_span_relation_counts, 'transform_theoretical_payload_immediate_window_string_span_role_counts': transform_theoretical_payload_immediate_window_string_span_role_counts, 'transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts': transform_theoretical_payload_later_fit_gap_member_descriptor_relation_counts, 'transform_theoretical_payload_later_fit_gap_string_span_relation_counts': transform_theoretical_payload_later_fit_gap_string_span_relation_counts, 'transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows': transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows})
    result.update({'transform_theoretical_payload_later_preserved_span_fit_rows': transform_theoretical_payload_later_preserved_span_fit_rows, 'transform_theoretical_payload_member_rows': transform_theoretical_payload_member_rows, 'transform_theoretical_payload_no_preserved_span_fit_rows': transform_theoretical_payload_no_preserved_span_fit_rows})
    return result


def _report_from_rows_stage_2(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    from cdmw.core.prefab_corpus_descriptor_metrics_0 import _nonzero_word3_offset_candidate_status_counts, _nonzero_word3_offset_candidate_target_counts
    rows, transform_descriptor_signature_counts, transform_descriptor_signature_offset_candidate_counts = (state['rows'], state['transform_descriptor_signature_counts'], state['transform_descriptor_signature_offset_candidate_counts'])
    transform_descriptor_signature_offset_candidate_target_counts: dict[str, int] = {}
    transform_nonzero_word3_offset_candidate_target_counts: dict[str, int] = {}
    transform_descriptor_word0_value_counts: dict[str, int] = {}
    transform_descriptor_word1_value_counts: dict[str, int] = {}
    transform_descriptor_word2_value_counts: dict[str, int] = {}
    transform_descriptor_word3_value_counts: dict[str, int] = {}
    transform_theoretical_payload_shape_counts: dict[str, int] = {}
    for row in rows:
        signatures = row.get('transform_descriptor_signature_counts')
        if isinstance(signatures, Mapping):
            for key, value in signatures.items():
                transform_descriptor_signature_counts[str(key)] = transform_descriptor_signature_counts.get(str(key), 0) + int(value or 0)
        signature_offset_candidates = row.get('transform_descriptor_signature_offset_candidate_counts')
        if isinstance(signature_offset_candidates, Mapping):
            for key, value in signature_offset_candidates.items():
                transform_descriptor_signature_offset_candidate_counts[str(key)] = transform_descriptor_signature_offset_candidate_counts.get(str(key), 0) + int(value or 0)
        signature_offset_candidate_targets = row.get('transform_descriptor_signature_offset_candidate_target_counts')
        if isinstance(signature_offset_candidate_targets, Mapping):
            for key, value in signature_offset_candidate_targets.items():
                transform_descriptor_signature_offset_candidate_target_counts[str(key)] = transform_descriptor_signature_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
        nonzero_word3_targets = row.get('transform_nonzero_word3_offset_candidate_target_counts')
        if isinstance(nonzero_word3_targets, Mapping):
            for key, value in nonzero_word3_targets.items():
                transform_nonzero_word3_offset_candidate_target_counts[str(key)] = transform_nonzero_word3_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
        for source_key, target in (('transform_descriptor_word0_value_counts', transform_descriptor_word0_value_counts), ('transform_descriptor_word1_value_counts', transform_descriptor_word1_value_counts), ('transform_descriptor_word2_value_counts', transform_descriptor_word2_value_counts), ('transform_descriptor_word3_value_counts', transform_descriptor_word3_value_counts), ('transform_theoretical_payload_shape_counts', transform_theoretical_payload_shape_counts)):
            values = row.get(source_key)
            if not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                target[str(key)] = target.get(str(key), 0) + int(value or 0)
    transform_nonzero_word3_offset_candidate_status_counts = _nonzero_word3_offset_candidate_status_counts(transform_descriptor_signature_offset_candidate_counts)
    transform_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(transform_descriptor_signature_offset_candidate_target_counts)
    array_member_count = sum((int(row.get('array_member_count') or 0) for row in rows))
    decoded_array_payload_element_rows = sum((int(row.get('decoded_array_payload_element_rows') or 0) for row in rows))
    array_members_without_payload_elements = sum((int(row.get('array_members_without_payload_elements') or 0) for row in rows))
    array_members_with_descriptor_tail_bytes = sum((int(row.get('array_members_with_descriptor_tail_bytes') or 0) for row in rows))
    array_descriptor_tail_bytes = sum((int(row.get('array_descriptor_tail_bytes') or 0) for row in rows))
    array_theoretical_payload_member_rows = sum((int(row.get('array_theoretical_payload_member_rows') or 0) for row in rows))
    array_theoretical_payload_byte_count = sum((int(row.get('array_theoretical_payload_byte_count') or 0) for row in rows))
    array_theoretical_payload_non_tiny_member_rows = sum((int(row.get('array_theoretical_payload_non_tiny_member_rows') or 0) for row in rows))
    array_theoretical_payload_non_tiny_byte_count = sum((int(row.get('array_theoretical_payload_non_tiny_byte_count') or 0) for row in rows))
    array_theoretical_payload_exact_preserved_span_rows = sum((int(row.get('array_theoretical_payload_exact_preserved_span_rows') or 0) for row in rows))
    array_theoretical_payload_later_preserved_span_fit_rows = sum((int(row.get('array_theoretical_payload_later_preserved_span_fit_rows') or 0) for row in rows))
    array_theoretical_payload_no_preserved_span_fit_rows = sum((int(row.get('array_theoretical_payload_no_preserved_span_fit_rows') or 0) for row in rows))
    array_theoretical_payload_immediate_window_string_span_overlap_rows = sum((int(row.get('array_theoretical_payload_immediate_window_string_span_overlap_rows') or 0) for row in rows))
    array_theoretical_payload_immediate_window_string_span_overlap_count = sum((int(row.get('array_theoretical_payload_immediate_window_string_span_overlap_count') or 0) for row in rows))
    array_theoretical_payload_immediate_window_string_span_role_counts = _sum_count_maps(rows, 'array_theoretical_payload_immediate_window_string_span_role_counts', {})
    array_theoretical_payload_immediate_window_string_span_relation_counts = _sum_count_maps(rows, 'array_theoretical_payload_immediate_window_string_span_relation_counts', {})
    array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows = sum((int(row.get('array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows') or 0) for row in rows))
    array_theoretical_payload_later_fit_gap_string_span_relation_counts = _sum_count_maps(rows, 'array_theoretical_payload_later_fit_gap_string_span_relation_counts', {})
    array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts = _sum_count_maps(rows, 'array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts', {})
    array_member_stride_hint_count = sum((int(row.get('array_member_stride_hint_count') or 0) for row in rows))
    array_member_count_hint_count = sum((int(row.get('array_member_count_hint_count') or 0) for row in rows))
    array_descriptor_signature_counts: dict[str, int] = {}
    array_descriptor_signature_offset_candidate_counts: dict[str, int] = {}
    array_descriptor_signature_offset_candidate_target_counts: dict[str, int] = {}
    for row in rows:
        signatures = row.get('array_descriptor_signature_counts')
        if not isinstance(signatures, Mapping):
            signatures = {}
        for key, value in signatures.items():
            array_descriptor_signature_counts[str(key)] = array_descriptor_signature_counts.get(str(key), 0) + int(value or 0)
        signature_offset_candidates = row.get('array_descriptor_signature_offset_candidate_counts')
        if isinstance(signature_offset_candidates, Mapping):
            for key, value in signature_offset_candidates.items():
                array_descriptor_signature_offset_candidate_counts[str(key)] = array_descriptor_signature_offset_candidate_counts.get(str(key), 0) + int(value or 0)
        signature_offset_candidate_targets = row.get('array_descriptor_signature_offset_candidate_target_counts')
        if isinstance(signature_offset_candidate_targets, Mapping):
            for key, value in signature_offset_candidate_targets.items():
                array_descriptor_signature_offset_candidate_target_counts[str(key)] = array_descriptor_signature_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
    result = {}
    result.update({'array_descriptor_signature_counts': array_descriptor_signature_counts, 'array_descriptor_signature_offset_candidate_counts': array_descriptor_signature_offset_candidate_counts, 'array_descriptor_signature_offset_candidate_target_counts': array_descriptor_signature_offset_candidate_target_counts, 'array_descriptor_tail_bytes': array_descriptor_tail_bytes, 'array_member_count': array_member_count})
    result.update({'array_member_count_hint_count': array_member_count_hint_count, 'array_member_stride_hint_count': array_member_stride_hint_count, 'array_members_with_descriptor_tail_bytes': array_members_with_descriptor_tail_bytes, 'array_members_without_payload_elements': array_members_without_payload_elements, 'array_theoretical_payload_byte_count': array_theoretical_payload_byte_count})
    result.update({'array_theoretical_payload_exact_preserved_span_rows': array_theoretical_payload_exact_preserved_span_rows, 'array_theoretical_payload_immediate_window_string_span_overlap_count': array_theoretical_payload_immediate_window_string_span_overlap_count, 'array_theoretical_payload_immediate_window_string_span_overlap_rows': array_theoretical_payload_immediate_window_string_span_overlap_rows, 'array_theoretical_payload_immediate_window_string_span_relation_counts': array_theoretical_payload_immediate_window_string_span_relation_counts, 'array_theoretical_payload_immediate_window_string_span_role_counts': array_theoretical_payload_immediate_window_string_span_role_counts})
    result.update({'array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts': array_theoretical_payload_later_fit_gap_member_descriptor_relation_counts, 'array_theoretical_payload_later_fit_gap_string_span_relation_counts': array_theoretical_payload_later_fit_gap_string_span_relation_counts, 'array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows': array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows, 'array_theoretical_payload_later_preserved_span_fit_rows': array_theoretical_payload_later_preserved_span_fit_rows, 'array_theoretical_payload_member_rows': array_theoretical_payload_member_rows})
    result.update({'array_theoretical_payload_no_preserved_span_fit_rows': array_theoretical_payload_no_preserved_span_fit_rows, 'array_theoretical_payload_non_tiny_byte_count': array_theoretical_payload_non_tiny_byte_count, 'array_theoretical_payload_non_tiny_member_rows': array_theoretical_payload_non_tiny_member_rows, 'decoded_array_payload_element_rows': decoded_array_payload_element_rows, 'transform_descriptor_signature_offset_candidate_target_counts': transform_descriptor_signature_offset_candidate_target_counts})
    result.update({'transform_descriptor_word0_value_counts': transform_descriptor_word0_value_counts, 'transform_descriptor_word1_value_counts': transform_descriptor_word1_value_counts, 'transform_descriptor_word2_value_counts': transform_descriptor_word2_value_counts, 'transform_descriptor_word3_value_counts': transform_descriptor_word3_value_counts, 'transform_nonzero_word3_offset_candidate_status_counts': transform_nonzero_word3_offset_candidate_status_counts})
    result.update({'transform_nonzero_word3_offset_candidate_target_counts': transform_nonzero_word3_offset_candidate_target_counts, 'transform_theoretical_payload_shape_counts': transform_theoretical_payload_shape_counts})
    return result


def _report_from_rows_stage_3(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_array_metrics import _array_nonzero_word3_offset_candidate_status_counts
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    from cdmw.core.prefab_corpus_descriptor_metrics_0 import _nonzero_word3_offset_candidate_target_counts
    array_descriptor_signature_offset_candidate_target_counts, rows = (state['array_descriptor_signature_offset_candidate_target_counts'], state['rows'])
    array_descriptor_word0_value_counts: dict[str, int] = {}
    array_descriptor_word1_value_counts: dict[str, int] = {}
    array_descriptor_word2_value_counts: dict[str, int] = {}
    array_descriptor_word3_value_counts: dict[str, int] = {}
    array_stride_hint_type_counts: dict[str, int] = {}
    array_count_hint_type_counts: dict[str, int] = {}
    array_count_hint_member_counts: dict[str, int] = {}
    array_word3_relation_counts = _sum_count_maps(rows, 'array_word3_relation_counts', {'array_rows': 0, 'with_count_hint_rows': 0, 'with_stride_hint_rows': 0, 'word3_zero_rows': 0, 'word3_nonzero_rows': 0, 'word3_equals_count_hint_rows': 0, 'word3_nonzero_equals_count_hint_rows': 0, 'count_hint_positive_word3_equals_count_hint_rows': 0, 'count_hint_positive_word3_not_count_hint_rows': 0, 'word3_equals_stride_hint_rows': 0, 'word3_equals_word2_delta_rows': 0, 'word3_nonzero_without_count_hint_rows': 0, 'word3_nonzero_without_stride_hint_rows': 0})
    array_theoretical_payload_shape_counts: dict[str, int] = {}
    array_word2_delta_member_counts: dict[str, int] = {}
    array_word2_delta_word3_member_counts: dict[str, int] = {}
    array_word2_delta_word3_member_offset_candidate_counts: dict[str, int] = {}
    array_nonzero_word3_offset_candidate_target_counts: dict[str, int] = {}
    for row in rows:
        word0_values = row.get('array_descriptor_word0_value_counts')
        if isinstance(word0_values, Mapping):
            for key, value in word0_values.items():
                array_descriptor_word0_value_counts[str(key)] = array_descriptor_word0_value_counts.get(str(key), 0) + int(value or 0)
        word1_values = row.get('array_descriptor_word1_value_counts')
        if isinstance(word1_values, Mapping):
            for key, value in word1_values.items():
                array_descriptor_word1_value_counts[str(key)] = array_descriptor_word1_value_counts.get(str(key), 0) + int(value or 0)
        word2_values = row.get('array_descriptor_word2_value_counts')
        if isinstance(word2_values, Mapping):
            for key, value in word2_values.items():
                array_descriptor_word2_value_counts[str(key)] = array_descriptor_word2_value_counts.get(str(key), 0) + int(value or 0)
        word3_values = row.get('array_descriptor_word3_value_counts')
        if isinstance(word3_values, Mapping):
            for key, value in word3_values.items():
                array_descriptor_word3_value_counts[str(key)] = array_descriptor_word3_value_counts.get(str(key), 0) + int(value or 0)
        stride_hint_types = row.get('array_stride_hint_type_counts')
        if isinstance(stride_hint_types, Mapping):
            for key, value in stride_hint_types.items():
                array_stride_hint_type_counts[str(key)] = array_stride_hint_type_counts.get(str(key), 0) + int(value or 0)
        count_hint_types = row.get('array_count_hint_type_counts')
        if isinstance(count_hint_types, Mapping):
            for key, value in count_hint_types.items():
                array_count_hint_type_counts[str(key)] = array_count_hint_type_counts.get(str(key), 0) + int(value or 0)
        count_hint_members = row.get('array_count_hint_member_counts')
        if isinstance(count_hint_members, Mapping):
            for key, value in count_hint_members.items():
                array_count_hint_member_counts[str(key)] = array_count_hint_member_counts.get(str(key), 0) + int(value or 0)
        theoretical_payload_shapes = row.get('array_theoretical_payload_shape_counts')
        if isinstance(theoretical_payload_shapes, Mapping):
            for key, value in theoretical_payload_shapes.items():
                array_theoretical_payload_shape_counts[str(key)] = array_theoretical_payload_shape_counts.get(str(key), 0) + int(value or 0)
        word2_delta_members = row.get('array_word2_delta_member_counts')
        if isinstance(word2_delta_members, Mapping):
            for key, value in word2_delta_members.items():
                array_word2_delta_member_counts[str(key)] = array_word2_delta_member_counts.get(str(key), 0) + int(value or 0)
        word2_delta_word3_members = row.get('array_word2_delta_word3_member_counts')
        if isinstance(word2_delta_word3_members, Mapping):
            for key, value in word2_delta_word3_members.items():
                array_word2_delta_word3_member_counts[str(key)] = array_word2_delta_word3_member_counts.get(str(key), 0) + int(value or 0)
        word2_delta_word3_member_offset_candidates = row.get('array_word2_delta_word3_member_offset_candidate_counts')
        if isinstance(word2_delta_word3_member_offset_candidates, Mapping):
            for key, value in word2_delta_word3_member_offset_candidates.items():
                array_word2_delta_word3_member_offset_candidate_counts[str(key)] = array_word2_delta_word3_member_offset_candidate_counts.get(str(key), 0) + int(value or 0)
        nonzero_word3_targets = row.get('array_nonzero_word3_offset_candidate_target_counts')
        if isinstance(nonzero_word3_targets, Mapping):
            for key, value in nonzero_word3_targets.items():
                array_nonzero_word3_offset_candidate_target_counts[str(key)] = array_nonzero_word3_offset_candidate_target_counts.get(str(key), 0) + int(value or 0)
    array_nonzero_word3_offset_candidate_status_counts = _array_nonzero_word3_offset_candidate_status_counts(array_word2_delta_word3_member_offset_candidate_counts)
    array_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(array_descriptor_signature_offset_candidate_target_counts)
    array_classification_source_counts = _sum_count_maps(rows, 'array_classification_source_counts', {'type_vector_count': 0, 'type_brackets_count': 0, 'name_list_flag_count': 0})
    array_word3_category_counts = _sum_count_maps(rows, 'array_word3_category_counts', {'zero_count': 0, 'one_count': 0, 'power_of_two_gt_one_count': 0, 'other_nonzero_count': 0, 'nonzero_with_stride_hint_count': 0, 'nonzero_without_stride_hint_count': 0})
    reference_member_count = sum((int(row.get('reference_member_count') or 0) for row in rows))
    reference_members_without_descriptor_semantics = sum((int(row.get('reference_members_without_descriptor_semantics') or 0) for row in rows))
    reference_members_with_descriptor_tail_bytes = sum((int(row.get('reference_members_with_descriptor_tail_bytes') or 0) for row in rows))
    reference_descriptor_tail_bytes = sum((int(row.get('reference_descriptor_tail_bytes') or 0) for row in rows))
    result = {}
    result.update({'array_classification_source_counts': array_classification_source_counts, 'array_count_hint_member_counts': array_count_hint_member_counts, 'array_count_hint_type_counts': array_count_hint_type_counts, 'array_descriptor_word0_value_counts': array_descriptor_word0_value_counts, 'array_descriptor_word1_value_counts': array_descriptor_word1_value_counts})
    result.update({'array_descriptor_word2_value_counts': array_descriptor_word2_value_counts, 'array_descriptor_word3_value_counts': array_descriptor_word3_value_counts, 'array_nonzero_word3_offset_candidate_status_counts': array_nonzero_word3_offset_candidate_status_counts, 'array_nonzero_word3_offset_candidate_target_counts': array_nonzero_word3_offset_candidate_target_counts, 'array_stride_hint_type_counts': array_stride_hint_type_counts})
    result.update({'array_theoretical_payload_shape_counts': array_theoretical_payload_shape_counts, 'array_word2_delta_member_counts': array_word2_delta_member_counts, 'array_word2_delta_word3_member_counts': array_word2_delta_word3_member_counts, 'array_word2_delta_word3_member_offset_candidate_counts': array_word2_delta_word3_member_offset_candidate_counts, 'array_word3_category_counts': array_word3_category_counts})
    result.update({'array_word3_relation_counts': array_word3_relation_counts, 'reference_descriptor_tail_bytes': reference_descriptor_tail_bytes, 'reference_member_count': reference_member_count, 'reference_members_with_descriptor_tail_bytes': reference_members_with_descriptor_tail_bytes, 'reference_members_without_descriptor_semantics': reference_members_without_descriptor_semantics})
    return result


def _report_from_rows_stage_4(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    from cdmw.core.prefab_corpus_descriptor_metrics_0 import _descriptor_kind_nonzero_word3_offset_candidate_status_counts, _descriptor_kind_nonzero_word3_offset_candidate_target_counts, _nonzero_word3_offset_candidate_status_counts, _nonzero_word3_offset_candidate_target_counts
    array_nonzero_word3_offset_candidate_status_counts, array_nonzero_word3_offset_candidate_target_counts, rows = (state['array_nonzero_word3_offset_candidate_status_counts'], state['array_nonzero_word3_offset_candidate_target_counts'], state['rows'])
    transform_nonzero_word3_offset_candidate_status_counts, transform_nonzero_word3_offset_candidate_target_counts = (state['transform_nonzero_word3_offset_candidate_status_counts'], state['transform_nonzero_word3_offset_candidate_target_counts'])
    reference_descriptor_signature_counts = _sum_count_maps(rows, 'reference_descriptor_signature_counts', {})
    reference_descriptor_tail_record_shape_counts = _sum_count_maps(rows, 'reference_descriptor_tail_record_shape_counts', {})
    reference_descriptor_tail_offset_candidate_mod_counts = _sum_count_maps(rows, 'reference_descriptor_tail_offset_candidate_mod_counts', {})
    reference_descriptor_tail_record_profile_counts = _sum_count_maps(rows, 'reference_descriptor_tail_record_profile_counts', {'exact_tail_members': 0, 'record_count_total': 0, 'unique_record_count_total': 0, 'duplicate_record_count_total': 0, 'offset_candidate_record_count_total': 0, 'offset_candidate_free_record_count_total': 0, 'offset_candidate_multi_kind_record_count_total': 0, 'max_offset_candidates_per_record': 0})
    reference_descriptor_tail_record_profile_counts['max_offset_candidates_per_record'] = max((int(row.get('reference_descriptor_tail_record_profile_counts', {}).get('max_offset_candidates_per_record') or 0) for row in rows if isinstance(row.get('reference_descriptor_tail_record_profile_counts'), Mapping)), default=0)
    reference_descriptor_tail_numeric_profile_counts = _sum_count_maps(rows, 'reference_descriptor_tail_numeric_profile_counts', {'exact_tail_members': 0, 'record_count_total': 0, 'u32_columns_total': 0, 'finite_float_columns': 0, 'worldish_float_columns': 0, 'unitish_float_columns': 0, 'zero_heavy_u32_columns': 0, 'one_float_heavy_columns': 0, 'tiny_or_zero_heavy_float_columns': 0, 'huge_float_columns': 0})
    reference_descriptor_tail_column_profile_counts = _sum_count_maps(rows, 'reference_descriptor_tail_column_profile_counts', {'exact_tail_members': 0, 'record_count_total': 0, 'u32_columns_total': 0, 'constant_u32_columns': 0, 'variable_u32_columns': 0, 'all_zero_u32_columns': 0, 'mostly_zero_u32_columns': 0, 'offset_candidate_u32_columns': 0, 'offset_candidate_free_u32_columns': 0, 'unique_u32_value_total': 0, 'max_unique_u32_values_per_column': 0, 'unaligned_offset_candidate_rows': 0})
    reference_descriptor_tail_column_profile_counts['max_unique_u32_values_per_column'] = max((int(row.get('reference_descriptor_tail_column_profile_counts', {}).get('max_unique_u32_values_per_column') or 0) for row in rows if isinstance(row.get('reference_descriptor_tail_column_profile_counts'), Mapping)), default=0)
    reference_descriptor_signature_offset_candidate_counts = _sum_count_maps(rows, 'reference_descriptor_signature_offset_candidate_counts', {})
    reference_nonzero_word3_offset_candidate_status_counts = _nonzero_word3_offset_candidate_status_counts(reference_descriptor_signature_offset_candidate_counts)
    reference_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(rows, 'reference_descriptor_signature_offset_candidate_target_counts', {})
    reference_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(reference_descriptor_signature_offset_candidate_target_counts)
    scalar_or_bool_descriptor_signature_counts = _sum_count_maps(rows, 'scalar_or_bool_descriptor_signature_counts', {})
    scalar_or_bool_descriptor_signature_offset_candidate_counts = _sum_count_maps(rows, 'scalar_or_bool_descriptor_signature_offset_candidate_counts', {})
    scalar_or_bool_nonzero_word3_offset_candidate_status_counts = _nonzero_word3_offset_candidate_status_counts(scalar_or_bool_descriptor_signature_offset_candidate_counts)
    scalar_or_bool_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(rows, 'scalar_or_bool_descriptor_signature_offset_candidate_target_counts', {})
    scalar_or_bool_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(scalar_or_bool_descriptor_signature_offset_candidate_target_counts)
    string_descriptor_signature_counts = _sum_count_maps(rows, 'string_descriptor_signature_counts', {})
    string_descriptor_signature_offset_candidate_counts = _sum_count_maps(rows, 'string_descriptor_signature_offset_candidate_counts', {})
    string_nonzero_word3_offset_candidate_status_counts = _nonzero_word3_offset_candidate_status_counts(string_descriptor_signature_offset_candidate_counts)
    string_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(rows, 'string_descriptor_signature_offset_candidate_target_counts', {})
    string_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(string_descriptor_signature_offset_candidate_target_counts)
    generic_descriptor_signature_counts = _sum_count_maps(rows, 'generic_descriptor_signature_counts', {})
    generic_descriptor_signature_offset_candidate_counts = _sum_count_maps(rows, 'generic_descriptor_signature_offset_candidate_counts', {})
    generic_nonzero_word3_offset_candidate_status_counts = _nonzero_word3_offset_candidate_status_counts(generic_descriptor_signature_offset_candidate_counts)
    generic_descriptor_signature_offset_candidate_target_counts = _sum_count_maps(rows, 'generic_descriptor_signature_offset_candidate_target_counts', {})
    generic_nonzero_word3_offset_candidate_target_counts = _nonzero_word3_offset_candidate_target_counts(generic_descriptor_signature_offset_candidate_target_counts)
    descriptor_kind_nonzero_word3_offset_candidate_status_counts = _descriptor_kind_nonzero_word3_offset_candidate_status_counts({'array': array_nonzero_word3_offset_candidate_status_counts, 'generic': generic_nonzero_word3_offset_candidate_status_counts, 'reference': reference_nonzero_word3_offset_candidate_status_counts, 'scalar_or_bool': scalar_or_bool_nonzero_word3_offset_candidate_status_counts, 'string': string_nonzero_word3_offset_candidate_status_counts, 'transform': transform_nonzero_word3_offset_candidate_status_counts})
    descriptor_kind_nonzero_word3_offset_candidate_target_counts = _descriptor_kind_nonzero_word3_offset_candidate_target_counts({'array': array_nonzero_word3_offset_candidate_target_counts, 'generic': generic_nonzero_word3_offset_candidate_target_counts, 'reference': reference_nonzero_word3_offset_candidate_target_counts, 'scalar_or_bool': scalar_or_bool_nonzero_word3_offset_candidate_target_counts, 'string': string_nonzero_word3_offset_candidate_target_counts, 'transform': transform_nonzero_word3_offset_candidate_target_counts})
    descriptor_owner_kind_offset_candidate_counts = _sum_count_maps(rows, 'descriptor_owner_kind_offset_candidate_counts', {})
    descriptor_owner_kind_offset_candidate_target_counts = _sum_count_maps(rows, 'descriptor_owner_kind_offset_candidate_target_counts', {})
    offset_candidate_count = sum((int(row.get('offset_candidate_count') or 0) for row in rows))
    offset_candidate_aligned_count = sum((int(row.get('offset_candidate_aligned_count') or 0) for row in rows))
    offset_candidate_unaligned_count = sum((int(row.get('offset_candidate_unaligned_count') or 0) for row in rows))
    offset_candidate_overlap_group_count = sum((int(row.get('offset_candidate_overlap_group_count') or 0) for row in rows))
    offset_candidate_overlapping_window_count = sum((int(row.get('offset_candidate_overlapping_window_count') or 0) for row in rows))
    offset_candidate_isolated_count = sum((int(row.get('offset_candidate_isolated_count') or 0) for row in rows))
    offset_candidate_aligned_isolated_count = sum((int(row.get('offset_candidate_aligned_isolated_count') or 0) for row in rows))
    offset_candidate_unaligned_isolated_count = sum((int(row.get('offset_candidate_unaligned_isolated_count') or 0) for row in rows))
    offset_candidate_unaligned_or_overlapping_count = sum((int(row.get('offset_candidate_unaligned_or_overlapping_count') or 0) for row in rows))
    offset_candidate_target_string_length_prefix_count = sum((int(row.get('offset_candidate_target_string_length_prefix_count') or 0) for row in rows))
    offset_candidate_target_string_value_count = sum((int(row.get('offset_candidate_target_string_value_count') or 0) for row in rows))
    offset_candidate_target_string_end_count = sum((int(row.get('offset_candidate_target_string_end_count') or 0) for row in rows))
    offset_candidate_in_member_descriptor_count = sum((int(row.get('offset_candidate_in_member_descriptor_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_count = sum((int(row.get('offset_candidate_outside_member_descriptor_count') or 0) for row in rows))
    offset_candidate_in_array_descriptor_count = sum((int(row.get('offset_candidate_in_array_descriptor_count') or 0) for row in rows))
    offset_candidate_in_transform_descriptor_count = sum((int(row.get('offset_candidate_in_transform_descriptor_count') or 0) for row in rows))
    offset_candidate_in_reference_descriptor_count = sum((int(row.get('offset_candidate_in_reference_descriptor_count') or 0) for row in rows))
    offset_candidate_in_scalar_or_bool_descriptor_count = sum((int(row.get('offset_candidate_in_scalar_or_bool_descriptor_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_unaligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_unaligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_overlap_group_count = sum((int(row.get('offset_candidate_outside_member_descriptor_overlap_group_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_overlapping_window_count = sum((int(row.get('offset_candidate_outside_member_descriptor_overlapping_window_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_isolated_count = sum((int(row.get('offset_candidate_outside_member_descriptor_isolated_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_unaligned_isolated_count = sum((int(row.get('offset_candidate_outside_member_descriptor_unaligned_isolated_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count = sum((int(row.get('offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_target_string_length_prefix_count = sum((int(row.get('offset_candidate_outside_member_descriptor_target_string_length_prefix_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_target_string_value_count = sum((int(row.get('offset_candidate_outside_member_descriptor_target_string_value_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_target_string_end_count = sum((int(row.get('offset_candidate_outside_member_descriptor_target_string_end_count') or 0) for row in rows))
    mod4_defaults = {'0': 0, '1': 0, '2': 0, '3': 0}
    offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts', mod4_defaults)
    offset_candidate_outside_member_descriptor_target_value_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_target_value_mod4_counts', mod4_defaults)
    offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts', mod4_defaults)
    offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts', mod4_defaults)
    neighbor_byte_class_defaults = {'ascii_like': 0, 'binary_like': 0, 'empty': 0, 'nul_rich': 0}
    offset_candidate_outside_member_descriptor_neighbor_byte_class_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_neighbor_byte_class_counts', neighbor_byte_class_defaults)
    target_role_defaults = {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}
    offset_candidate_outside_member_descriptor_target_role_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_target_role_counts', target_role_defaults)
    offset_candidate_outside_member_descriptor_string_value_target_role_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_string_value_target_role_counts', target_role_defaults)
    result = {}
    result.update({'descriptor_kind_nonzero_word3_offset_candidate_status_counts': descriptor_kind_nonzero_word3_offset_candidate_status_counts, 'descriptor_kind_nonzero_word3_offset_candidate_target_counts': descriptor_kind_nonzero_word3_offset_candidate_target_counts, 'descriptor_owner_kind_offset_candidate_counts': descriptor_owner_kind_offset_candidate_counts, 'descriptor_owner_kind_offset_candidate_target_counts': descriptor_owner_kind_offset_candidate_target_counts, 'generic_descriptor_signature_counts': generic_descriptor_signature_counts})
    result.update({'generic_descriptor_signature_offset_candidate_counts': generic_descriptor_signature_offset_candidate_counts, 'generic_descriptor_signature_offset_candidate_target_counts': generic_descriptor_signature_offset_candidate_target_counts, 'generic_nonzero_word3_offset_candidate_status_counts': generic_nonzero_word3_offset_candidate_status_counts, 'generic_nonzero_word3_offset_candidate_target_counts': generic_nonzero_word3_offset_candidate_target_counts, 'mod4_defaults': mod4_defaults})
    result.update({'neighbor_byte_class_defaults': neighbor_byte_class_defaults, 'offset_candidate_aligned_count': offset_candidate_aligned_count, 'offset_candidate_aligned_isolated_count': offset_candidate_aligned_isolated_count, 'offset_candidate_count': offset_candidate_count, 'offset_candidate_in_array_descriptor_count': offset_candidate_in_array_descriptor_count})
    result.update({'offset_candidate_in_member_descriptor_count': offset_candidate_in_member_descriptor_count, 'offset_candidate_in_reference_descriptor_count': offset_candidate_in_reference_descriptor_count, 'offset_candidate_in_scalar_or_bool_descriptor_count': offset_candidate_in_scalar_or_bool_descriptor_count, 'offset_candidate_in_transform_descriptor_count': offset_candidate_in_transform_descriptor_count, 'offset_candidate_isolated_count': offset_candidate_isolated_count})
    result.update({'offset_candidate_outside_member_descriptor_aligned_count': offset_candidate_outside_member_descriptor_aligned_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_count': offset_candidate_outside_member_descriptor_aligned_isolated_count, 'offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts': offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts, 'offset_candidate_outside_member_descriptor_count': offset_candidate_outside_member_descriptor_count, 'offset_candidate_outside_member_descriptor_isolated_count': offset_candidate_outside_member_descriptor_isolated_count})
    result.update({'offset_candidate_outside_member_descriptor_neighbor_byte_class_counts': offset_candidate_outside_member_descriptor_neighbor_byte_class_counts, 'offset_candidate_outside_member_descriptor_overlap_group_count': offset_candidate_outside_member_descriptor_overlap_group_count, 'offset_candidate_outside_member_descriptor_overlapping_window_count': offset_candidate_outside_member_descriptor_overlapping_window_count, 'offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts': offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts, 'offset_candidate_outside_member_descriptor_string_value_target_role_counts': offset_candidate_outside_member_descriptor_string_value_target_role_counts})
    result.update({'offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts': offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts, 'offset_candidate_outside_member_descriptor_target_role_counts': offset_candidate_outside_member_descriptor_target_role_counts, 'offset_candidate_outside_member_descriptor_target_string_end_count': offset_candidate_outside_member_descriptor_target_string_end_count, 'offset_candidate_outside_member_descriptor_target_string_length_prefix_count': offset_candidate_outside_member_descriptor_target_string_length_prefix_count, 'offset_candidate_outside_member_descriptor_target_string_value_count': offset_candidate_outside_member_descriptor_target_string_value_count})
    result.update({'offset_candidate_outside_member_descriptor_target_value_mod4_counts': offset_candidate_outside_member_descriptor_target_value_mod4_counts, 'offset_candidate_outside_member_descriptor_unaligned_count': offset_candidate_outside_member_descriptor_unaligned_count, 'offset_candidate_outside_member_descriptor_unaligned_isolated_count': offset_candidate_outside_member_descriptor_unaligned_isolated_count, 'offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count': offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count, 'offset_candidate_overlap_group_count': offset_candidate_overlap_group_count})
    result.update({'offset_candidate_overlapping_window_count': offset_candidate_overlapping_window_count, 'offset_candidate_target_string_end_count': offset_candidate_target_string_end_count, 'offset_candidate_target_string_length_prefix_count': offset_candidate_target_string_length_prefix_count, 'offset_candidate_target_string_value_count': offset_candidate_target_string_value_count, 'offset_candidate_unaligned_count': offset_candidate_unaligned_count})
    result.update({'offset_candidate_unaligned_isolated_count': offset_candidate_unaligned_isolated_count, 'offset_candidate_unaligned_or_overlapping_count': offset_candidate_unaligned_or_overlapping_count, 'reference_descriptor_signature_counts': reference_descriptor_signature_counts, 'reference_descriptor_signature_offset_candidate_counts': reference_descriptor_signature_offset_candidate_counts, 'reference_descriptor_signature_offset_candidate_target_counts': reference_descriptor_signature_offset_candidate_target_counts})
    result.update({'reference_descriptor_tail_column_profile_counts': reference_descriptor_tail_column_profile_counts, 'reference_descriptor_tail_numeric_profile_counts': reference_descriptor_tail_numeric_profile_counts, 'reference_descriptor_tail_offset_candidate_mod_counts': reference_descriptor_tail_offset_candidate_mod_counts, 'reference_descriptor_tail_record_profile_counts': reference_descriptor_tail_record_profile_counts, 'reference_descriptor_tail_record_shape_counts': reference_descriptor_tail_record_shape_counts})
    result.update({'reference_nonzero_word3_offset_candidate_status_counts': reference_nonzero_word3_offset_candidate_status_counts, 'reference_nonzero_word3_offset_candidate_target_counts': reference_nonzero_word3_offset_candidate_target_counts, 'scalar_or_bool_descriptor_signature_counts': scalar_or_bool_descriptor_signature_counts, 'scalar_or_bool_descriptor_signature_offset_candidate_counts': scalar_or_bool_descriptor_signature_offset_candidate_counts, 'scalar_or_bool_descriptor_signature_offset_candidate_target_counts': scalar_or_bool_descriptor_signature_offset_candidate_target_counts})
    result.update({'scalar_or_bool_nonzero_word3_offset_candidate_status_counts': scalar_or_bool_nonzero_word3_offset_candidate_status_counts, 'scalar_or_bool_nonzero_word3_offset_candidate_target_counts': scalar_or_bool_nonzero_word3_offset_candidate_target_counts, 'string_descriptor_signature_counts': string_descriptor_signature_counts, 'string_descriptor_signature_offset_candidate_counts': string_descriptor_signature_offset_candidate_counts, 'string_descriptor_signature_offset_candidate_target_counts': string_descriptor_signature_offset_candidate_target_counts})
    result.update({'string_nonzero_word3_offset_candidate_status_counts': string_nonzero_word3_offset_candidate_status_counts, 'string_nonzero_word3_offset_candidate_target_counts': string_nonzero_word3_offset_candidate_target_counts, 'target_role_defaults': target_role_defaults})
    return result


def _report_from_rows_stage_5(state: Mapping[str]) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _sum_count_maps
    mod4_defaults, neighbor_byte_class_defaults, rows = (state['mod4_defaults'], state['neighbor_byte_class_defaults'], state['rows'])
    target_role_defaults, = (state['target_role_defaults'],)
    offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts', {})
    offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count = sum((int(row.get('offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_aligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_aligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_unaligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_unaligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_isolated_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_isolated_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts', target_role_defaults)
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts', {})
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts', {})
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts', {})
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts', {})
    offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts', {})
    span_byte_length_defaults = {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}
    offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts', span_byte_length_defaults)
    mod4_defaults = {'0': 0, '1': 0, '2': 0, '3': 0}
    offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts', mod4_defaults)
    offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts', mod4_defaults)
    offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts', neighbor_byte_class_defaults)
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts', {})
    offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count = sum((int(row.get('offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count') or 0) for row in rows))
    span_byte_length_defaults = {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}
    offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts = _sum_count_maps(rows, 'offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts', span_byte_length_defaults)
    offset_candidate_in_preserved_span_count = sum((int(row.get('offset_candidate_in_preserved_span_count') or 0) for row in rows))
    offset_candidate_outside_preserved_span_count = sum((int(row.get('offset_candidate_outside_preserved_span_count') or 0) for row in rows))
    offset_candidate_preserved_span_exact_4_count = sum((int(row.get('offset_candidate_preserved_span_exact_4_count') or 0) for row in rows))
    offset_candidate_preserved_span_le_8_count = sum((int(row.get('offset_candidate_preserved_span_le_8_count') or 0) for row in rows))
    offset_candidate_at_preserved_span_start_count = sum((int(row.get('offset_candidate_at_preserved_span_start_count') or 0) for row in rows))
    offset_candidate_at_preserved_span_end_count = sum((int(row.get('offset_candidate_at_preserved_span_end_count') or 0) for row in rows))
    offset_candidate_in_preserved_span_middle_count = sum((int(row.get('offset_candidate_in_preserved_span_middle_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_exact_4_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_exact_4_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_le_8_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_le_8_count') or 0) for row in rows))
    offset_candidate_outside_member_descriptor_preserved_span_middle_count = sum((int(row.get('offset_candidate_outside_member_descriptor_preserved_span_middle_count') or 0) for row in rows))
    largest_preserved_span_byte_count = max((int(row.get('largest_preserved_span_byte_count') or 0) for row in rows), default=0)
    preserved_span_with_offset_candidate_count = sum((int(row.get('preserved_span_with_offset_candidate_count') or 0) for row in rows))
    preserved_span_without_offset_candidate_count = sum((int(row.get('preserved_span_without_offset_candidate_count') or 0) for row in rows))
    member_descriptor_preserved_byte_count = sum((int(row.get('member_descriptor_preserved_bytes') or 0) for row in rows))
    member_descriptor_header_preserved_byte_count = sum((int(row.get('member_descriptor_header_preserved_bytes') or 0) for row in rows))
    member_descriptor_tail_preserved_byte_count = sum((int(row.get('member_descriptor_tail_preserved_bytes') or 0) for row in rows))
    preserved_unknown_byte_count_excluding_member_descriptors = sum((int(row.get('preserved_unknown_bytes_excluding_member_descriptors') or 0) for row in rows))
    preserved_unknown_byte_count_excluding_member_descriptor_headers = sum((int(row.get('preserved_unknown_bytes_excluding_member_descriptor_headers') or 0) for row in rows))
    result = {}
    result.update({'largest_preserved_span_byte_count': largest_preserved_span_byte_count, 'member_descriptor_header_preserved_byte_count': member_descriptor_header_preserved_byte_count, 'member_descriptor_preserved_byte_count': member_descriptor_preserved_byte_count, 'member_descriptor_tail_preserved_byte_count': member_descriptor_tail_preserved_byte_count, 'offset_candidate_at_preserved_span_end_count': offset_candidate_at_preserved_span_end_count})
    result.update({'offset_candidate_at_preserved_span_start_count': offset_candidate_at_preserved_span_start_count, 'offset_candidate_in_preserved_span_count': offset_candidate_in_preserved_span_count, 'offset_candidate_in_preserved_span_middle_count': offset_candidate_in_preserved_span_middle_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count': offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count': offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count': offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count': offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count': offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count': offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count, 'offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count': offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts': offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts, 'offset_candidate_outside_member_descriptor_preserved_span_exact_4_count': offset_candidate_outside_member_descriptor_preserved_span_exact_4_count, 'offset_candidate_outside_member_descriptor_preserved_span_le_8_count': offset_candidate_outside_member_descriptor_preserved_span_le_8_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count': offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_count': offset_candidate_outside_member_descriptor_preserved_span_middle_count})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count': offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts': offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count': offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count': offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count': offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count': offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count, 'offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count': offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count, 'offset_candidate_outside_member_descriptor_resource_reference_aligned_count': offset_candidate_outside_member_descriptor_resource_reference_aligned_count, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts': offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts': offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts': offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts': offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts, 'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts': offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts, 'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count': offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count': offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count, 'offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts': offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts, 'offset_candidate_outside_member_descriptor_resource_reference_count': offset_candidate_outside_member_descriptor_resource_reference_count, 'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count': offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count, 'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count': offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_isolated_count': offset_candidate_outside_member_descriptor_resource_reference_isolated_count, 'offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts': offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts, 'offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count': offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count, 'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count': offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count, 'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count': offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts': offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts': offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts': offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts, 'offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts': offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts, 'offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count': offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count': offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count, 'offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count': offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count, 'offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts': offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts, 'offset_candidate_outside_member_descriptor_resource_reference_unaligned_count': offset_candidate_outside_member_descriptor_resource_reference_unaligned_count, 'offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count': offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count})
    result.update({'offset_candidate_outside_preserved_span_count': offset_candidate_outside_preserved_span_count, 'offset_candidate_preserved_span_exact_4_count': offset_candidate_preserved_span_exact_4_count, 'offset_candidate_preserved_span_le_8_count': offset_candidate_preserved_span_le_8_count, 'preserved_span_with_offset_candidate_count': preserved_span_with_offset_candidate_count, 'preserved_span_without_offset_candidate_count': preserved_span_without_offset_candidate_count})
    result.update({'preserved_unknown_byte_count_excluding_member_descriptor_headers': preserved_unknown_byte_count_excluding_member_descriptor_headers, 'preserved_unknown_byte_count_excluding_member_descriptors': preserved_unknown_byte_count_excluding_member_descriptors})
    return result
