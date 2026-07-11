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


def _offset_candidate_resource_reference_span_metrics(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_preserved_span_shape_counts, _outside_member_descriptor_resource_reference_offset_candidates
    return _offset_candidate_preserved_span_shape_counts(decoded, _outside_member_descriptor_resource_reference_offset_candidates(decoded))


def _offset_candidate_outside_descriptor_aligned_isolated_span_metrics(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _aligned_isolated_offset_candidates, _offset_candidate_preserved_span_shape_counts, _outside_member_descriptor_offset_candidates
    return _offset_candidate_preserved_span_shape_counts(decoded, _aligned_isolated_offset_candidates(_outside_member_descriptor_offset_candidates(decoded)))


def _offset_candidate_descriptor_metrics(decoded: object) -> dict[str, int]:
    metrics = {}
    metrics.update({'in_member_descriptor_count': 0, 'outside_member_descriptor_count': 0})
    metrics.update({'in_array_descriptor_count': 0, 'in_transform_descriptor_count': 0})
    metrics.update({'in_reference_descriptor_count': 0, 'in_scalar_or_bool_descriptor_count': 0})
    for candidate in getattr(decoded, 'offset_candidates', ()):
        start = int(candidate.offset)
        end = start + 4
        owner = _candidate_member_descriptor_owner(decoded, start, end)
        if owner is None:
            metrics['outside_member_descriptor_count'] += 1
            continue
        metrics['in_member_descriptor_count'] += 1
        if getattr(owner, 'is_array', False):
            metrics['in_array_descriptor_count'] += 1
        if getattr(owner, 'is_transform', False):
            metrics['in_transform_descriptor_count'] += 1
        if getattr(owner, 'is_reference', False):
            metrics['in_reference_descriptor_count'] += 1
        if str(getattr(owner, 'descriptor_kind', '')) in {'scalar', 'bool'}:
            metrics['in_scalar_or_bool_descriptor_count'] += 1
    return metrics


def _candidate_member_descriptor_owner(decoded: object, start: int, end: int) -> object:
    return _candidate_member_descriptor_owner_from_declarations(tuple(getattr(decoded, 'member_declarations', ())), int(start), int(end))


@lru_cache(maxsize=262144)
def _candidate_member_descriptor_owner_from_declarations(declarations: tuple[object, ...], start: int, end: int) -> object:
    return next((declaration for declaration in declarations if int(declaration.descriptor_offset) <= start and end <= int(declaration.descriptor_offset) + int(declaration.descriptor_byte_length)), None)


def _offset_candidate_span_metrics(decoded: object) -> dict[str, int]:
    metrics = {}
    metrics.update({'in_preserved_span_count': 0, 'outside_preserved_span_count': 0})
    metrics.update({'preserved_span_exact_4_count': 0, 'preserved_span_le_8_count': 0})
    metrics.update({'at_preserved_span_start_count': 0, 'at_preserved_span_end_count': 0})
    metrics.update({'in_preserved_span_middle_count': 0, 'outside_member_descriptor_preserved_span_exact_4_count': 0})
    metrics.update({'outside_member_descriptor_preserved_span_le_8_count': 0, 'outside_member_descriptor_preserved_span_middle_count': 0})
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in getattr(decoded, 'offset_candidates', ()):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            metrics['outside_preserved_span_count'] += 1
            continue
        metrics['in_preserved_span_count'] += 1
        span_start = int(span.start)
        span_end = int(span.end)
        span_length = span_end - span_start
        exact_4 = span_length == 4
        le_8 = span_length <= 8
        middle = start != span_start and end != span_end
        if exact_4:
            metrics['preserved_span_exact_4_count'] += 1
        if le_8:
            metrics['preserved_span_le_8_count'] += 1
        if start == span_start:
            metrics['at_preserved_span_start_count'] += 1
        if end == span_end:
            metrics['at_preserved_span_end_count'] += 1
        if middle:
            metrics['in_preserved_span_middle_count'] += 1
        if _candidate_member_descriptor_owner(decoded, start, end) is None:
            if exact_4:
                metrics['outside_member_descriptor_preserved_span_exact_4_count'] += 1
            if le_8:
                metrics['outside_member_descriptor_preserved_span_le_8_count'] += 1
            if middle:
                metrics['outside_member_descriptor_preserved_span_middle_count'] += 1
    return metrics


def _offset_candidates_remapped_after_resize(before: object, after: object, edit_deltas: Sequence[tuple[int, int]]) -> bool:
    return _offset_candidate_remap_metrics_after_resize(before, after, edit_deltas)['remapped'] is True


def _offset_candidate_remap_metrics_after_resize(before: object, after: object, edit_deltas: Sequence[tuple[int, int]], after_payload: bytes | None=None) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_resource_reference_extension, _candidate_resource_reference_name, _candidate_target_role
    from cdmw.core.prefab_corpus_candidate_roles import _offset_candidate_targets_edit_metadata, _top_count_map
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]
    if not deltas:
        _prefab_result = {}
        _prefab_result.update({'remapped': True, 'effectively_remapped': True})
        _prefab_result.update({'report_only_effective_remap_status': 'strict_remap_passed', 'missing_count': 0})
        _prefab_result.update({'missing_target_kind_counts': {}, 'missing_owner_kind_target_role_kind_counts': {}})
        _prefab_result.update({'missing_metadata_target_count': 0, 'missing_non_metadata_target_count': 0})
        _prefab_result.update({'missing_metadata_owner_kind_target_role_kind_counts': {}, 'missing_non_metadata_owner_kind_target_role_kind_counts': {}})
        _prefab_result.update({'missing_non_metadata_resource_reference_extension_counts': {}, 'missing_non_metadata_resource_reference_target_kind_extension_counts': {}})
        _prefab_result.update({'missing_non_metadata_resource_reference_target_name_top_counts': {}, 'missing_unshifted_value_at_expected_offset_count': 0})
        _prefab_result.update({'missing_shifted_value_at_expected_offset_count': 0, 'missing_other_value_at_expected_offset_count': 0})
        _prefab_result.update({'missing_out_of_bounds_expected_offset_count': 0, 'missing_after_excluding_unshifted_value_at_expected_offset_count': 0})
        _prefab_result.update({'remapped_after_excluding_unshifted_value_at_expected_offset': True, 'missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts': {}})
        _prefab_result.update({'missing_shifted_offset_match_count': 0, 'missing_shifted_value_match_count': 0})
        _prefab_result.update({'missing_same_target_match_count': 0, 'stale_unshifted_count': 0})
        _prefab_result.update({'stale_unshifted_target_kind_counts': {}, 'sample_missing': ()})
        _prefab_result.update({'sample_stale_unshifted': ()})
        return _prefab_result
    before_candidates = getattr(before, 'offset_candidates', ())
    after_candidates = getattr(after, 'offset_candidates', ())
    after_keys = {(int(candidate.offset), int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in after_candidates}
    after_offsets = {offset for offset, _value, _target_kind, _target_field_index in after_keys}
    after_values = {value for _offset, value, _target_kind, _target_field_index in after_keys}
    after_targets = {(target_kind, target_field_index) for _offset, _value, target_kind, target_field_index in after_keys}

    def shift(position: int) -> int:
        return int(position) + sum((delta for edit_end, delta in deltas if int(position) >= edit_end))
    missing: list[tuple[int, int, str, int]] = []
    stale_unshifted: list[tuple[int, int, str, int]] = []
    missing_target_kind_counts: dict[str, int] = {}
    stale_unshifted_target_kind_counts: dict[str, int] = {}
    missing_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_metadata_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_non_metadata_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_extension_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_target_kind_extension_counts: dict[str, int] = {}
    missing_non_metadata_resource_reference_target_name_counts: dict[str, int] = {}
    missing_metadata_target_count = 0
    missing_non_metadata_target_count = 0
    missing_unshifted_value_at_expected_offset_count = 0
    missing_shifted_value_at_expected_offset_count = 0
    missing_other_value_at_expected_offset_count = 0
    missing_out_of_bounds_expected_offset_count = 0
    missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts: dict[str, int] = {}
    missing_shifted_offset_match_count = 0
    missing_shifted_value_match_count = 0
    missing_same_target_match_count = 0
    for candidate in before_candidates:
        original = (int(candidate.offset), int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index))
        expected = (shift(candidate.offset), shift(candidate.value), str(candidate.target_kind), int(candidate.target_field_index))
        if expected not in after_keys:
            missing.append(expected)
            target_kind = str(candidate.target_kind)
            missing_target_kind_counts[target_kind] = missing_target_kind_counts.get(target_kind, 0) + 1
            owner_role_key = f'{_candidate_owner_kind(before, candidate)}|{_candidate_target_role(before, candidate)}|{target_kind}'
            missing_owner_kind_target_role_kind_counts[owner_role_key] = missing_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
            if _offset_candidate_targets_edit_metadata(before, candidate):
                missing_metadata_target_count += 1
                missing_metadata_owner_kind_target_role_kind_counts[owner_role_key] = missing_metadata_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
            else:
                missing_non_metadata_target_count += 1
                missing_non_metadata_owner_kind_target_role_kind_counts[owner_role_key] = missing_non_metadata_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
                if _candidate_target_role(before, candidate) == 'resource_reference':
                    extension = _candidate_resource_reference_extension(before, candidate)
                    missing_non_metadata_resource_reference_extension_counts[extension] = missing_non_metadata_resource_reference_extension_counts.get(extension, 0) + 1
                    target_extension_key = f'{target_kind}|{extension}'
                    missing_non_metadata_resource_reference_target_kind_extension_counts[target_extension_key] = missing_non_metadata_resource_reference_target_kind_extension_counts.get(target_extension_key, 0) + 1
                    name = _candidate_resource_reference_name(before, candidate)
                    missing_non_metadata_resource_reference_target_name_counts[name] = missing_non_metadata_resource_reference_target_name_counts.get(name, 0) + 1
            if expected[0] in after_offsets:
                missing_shifted_offset_match_count += 1
            if expected[1] in after_values:
                missing_shifted_value_match_count += 1
            if (expected[2], expected[3]) in after_targets:
                missing_same_target_match_count += 1
            if after_payload is not None:
                expected_offset = int(expected[0])
                if expected_offset < 0 or expected_offset + 4 > len(after_payload):
                    missing_out_of_bounds_expected_offset_count += 1
                else:
                    raw_value = int.from_bytes(after_payload[expected_offset:expected_offset + 4], 'little')
                    if raw_value == int(candidate.value):
                        missing_unshifted_value_at_expected_offset_count += 1
                        missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts[owner_role_key] = missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts.get(owner_role_key, 0) + 1
                    elif raw_value == int(expected[1]):
                        missing_shifted_value_at_expected_offset_count += 1
                    else:
                        missing_other_value_at_expected_offset_count += 1
            if original in after_keys:
                stale_unshifted.append(original)
                stale_unshifted_target_kind_counts[target_kind] = stale_unshifted_target_kind_counts.get(target_kind, 0) + 1
    report_only_status = 'strict_remap_passed' if not missing else 'preserved_raw_exclusion_passed' if len(missing) == missing_unshifted_value_at_expected_offset_count else 'blocked_missing_shifted_or_unknown_values'
    effectively_remapped = report_only_status in {'strict_remap_passed', 'preserved_raw_exclusion_passed'}
    _prefab_result = {}
    _prefab_result.update({'remapped': not missing, 'effectively_remapped': effectively_remapped})
    _prefab_result.update({'report_only_effective_remap_status': report_only_status, 'missing_count': len(missing)})
    _prefab_result.update({'missing_target_kind_counts': dict(sorted(missing_target_kind_counts.items())), 'missing_owner_kind_target_role_kind_counts': dict(sorted(missing_owner_kind_target_role_kind_counts.items()))})
    _prefab_result.update({'missing_metadata_target_count': missing_metadata_target_count, 'missing_non_metadata_target_count': missing_non_metadata_target_count})
    _prefab_result.update({'missing_metadata_owner_kind_target_role_kind_counts': dict(sorted(missing_metadata_owner_kind_target_role_kind_counts.items())), 'missing_non_metadata_owner_kind_target_role_kind_counts': dict(sorted(missing_non_metadata_owner_kind_target_role_kind_counts.items()))})
    _prefab_result.update({'missing_non_metadata_resource_reference_extension_counts': dict(sorted(missing_non_metadata_resource_reference_extension_counts.items())), 'missing_non_metadata_resource_reference_target_kind_extension_counts': dict(sorted(missing_non_metadata_resource_reference_target_kind_extension_counts.items()))})
    _prefab_result.update({'missing_non_metadata_resource_reference_target_name_top_counts': _top_count_map(missing_non_metadata_resource_reference_target_name_counts), 'missing_unshifted_value_at_expected_offset_count': missing_unshifted_value_at_expected_offset_count})
    _prefab_result.update({'missing_shifted_value_at_expected_offset_count': missing_shifted_value_at_expected_offset_count, 'missing_other_value_at_expected_offset_count': missing_other_value_at_expected_offset_count})
    _prefab_result.update({'missing_out_of_bounds_expected_offset_count': missing_out_of_bounds_expected_offset_count, 'missing_after_excluding_unshifted_value_at_expected_offset_count': len(missing) - missing_unshifted_value_at_expected_offset_count})
    _prefab_result.update({'remapped_after_excluding_unshifted_value_at_expected_offset': len(missing) == missing_unshifted_value_at_expected_offset_count, 'missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts': dict(sorted(missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts.items()))})
    _prefab_result.update({'missing_shifted_offset_match_count': missing_shifted_offset_match_count, 'missing_shifted_value_match_count': missing_shifted_value_match_count})
    _prefab_result.update({'missing_same_target_match_count': missing_same_target_match_count, 'stale_unshifted_count': len(stale_unshifted)})
    _prefab_result.update({'stale_unshifted_target_kind_counts': dict(sorted(stale_unshifted_target_kind_counts.items())), 'sample_missing': tuple(({'offset': offset, 'value': value, 'target_kind': target_kind, 'target_field_index': target_field_index} for offset, value, target_kind, target_field_index in missing[:5]))})
    _prefab_result.update({'sample_stale_unshifted': tuple(({'offset': offset, 'value': value, 'target_kind': target_kind, 'target_field_index': target_field_index} for offset, value, target_kind, target_field_index in stale_unshifted[:5]))})
    return _prefab_result
