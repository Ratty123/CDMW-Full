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


def _selected_resize_offset_candidate_metrics(decoded: object | None, edit_deltas: Sequence[tuple[int, int]], payload: bytes=b'') -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _unique_offset_candidates
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]
    candidates = tuple(getattr(decoded, 'offset_candidates', ())) if decoded is not None else ()
    result = {}
    result.update({'selected_resize_offset_candidate_count': 0, 'selected_resize_offset_candidate_non_overlapping_count': 0})
    result.update({'selected_resize_offset_candidate_overlapping_count': 0, 'selected_resize_offset_candidate_target_role_kind_counts': {}})
    result.update({'selected_resize_offset_candidate_owner_kind_target_counts': {}, 'selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts': {'same_target_overlap_group_count': 0, 'same_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}})
    result.update({'selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts': {}, 'selected_resize_offset_candidate_same_target_resource_alias_counts': {'same_target_shift_conflict_group_count': 0, 'same_target_shift_conflict_candidate_count': 0, 'resource_alias_group_count': 0, 'resource_alias_candidate_count': 0, 'resource_reference_non_alias_group_count': 0, 'resource_reference_non_alias_candidate_count': 0, 'other_group_count': 0, 'other_candidate_count': 0}})
    result.update({'selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts': {'mixed_target_overlap_group_count': 0, 'mixed_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}, 'selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts': {}})
    result.update({'selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts': {}})
    if not deltas or not candidates:
        return result

    def shift(position: int) -> int:
        return int(position) + sum((delta for edit_end, delta in deltas if int(position) >= edit_end))
    selected = _unique_offset_candidates(tuple((candidate for candidate in candidates if shift(int(candidate.offset)) != int(candidate.offset) or shift(int(candidate.value)) != int(candidate.value))))
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    target_counts: dict[str, int] = {}
    owner_counts: dict[str, int] = {}
    non_overlapping = 0
    overlapping = 0
    for candidate in selected:
        if id(candidate) in overlapping_ids:
            overlapping += 1
        else:
            non_overlapping += 1
        target_key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}'
        owner_key = f'{_candidate_owner_kind(decoded, candidate)}|{target_key}'
        target_counts[target_key] = target_counts.get(target_key, 0) + 1
        owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1
    result['selected_resize_offset_candidate_count'] = len(selected)
    result['selected_resize_offset_candidate_non_overlapping_count'] = non_overlapping
    result['selected_resize_offset_candidate_overlapping_count'] = overlapping
    result['selected_resize_offset_candidate_target_role_kind_counts'] = dict(sorted(target_counts.items()))
    result['selected_resize_offset_candidate_owner_kind_target_counts'] = dict(sorted(owner_counts.items()))
    selected_ids = {id(candidate) for candidate in selected}
    same_counts = result['selected_resize_offset_candidate_same_target_overlap_shift_conflict_counts']
    mixed_counts = result['selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_counts']
    same_resource_alias_counts = result['selected_resize_offset_candidate_same_target_resource_alias_counts']
    same_profile_counts: dict[str, int] = {}
    mixed_profile_counts: dict[str, int] = {}
    mixed_resource_reference_detail_counts: dict[str, int] = {}
    data = bytes(payload or b'')
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))

    def profile_key(group: Sequence[object], impacted: Sequence[object], status: str) -> str:
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas_key = ','.join((str(offset - base) for offset in offsets))
        group_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group}))
        impacted_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in impacted}))
        return f'{status}|size_{len(group)}|width_{width}|deltas_{deltas_key}|group={group_profiles}|impacted={impacted_profiles}'

    def span_position(candidate: object) -> str:
        start = int(candidate.offset)
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start <= int(getattr(span, 'end', 0)) - 4), None)
        return 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, start + 4, span)

    def detail_key(group: Sequence[object], impacted: Sequence[object], status: str) -> str:
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        deltas_key = ','.join((str(offset - base) for offset in offsets))

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            end = start + 4
            return f'delta_{start - base}:{_candidate_target_identity_key(decoded, candidate)}|word_{bytes(payload[start:end]).hex()}|mod4_{start % 4}|{span_position(candidate)}'
        group_details = ','.join(sorted((detail(candidate) for candidate in group)))
        impacted_details = ','.join(sorted((detail(candidate) for candidate in impacted)))
        return f'{status}|size_{len(group)}|deltas_{deltas_key}|group={group_details}|impacted={impacted_details}'
    for group in overlap_groups:
        impacted = tuple((candidate for candidate in group if id(candidate) in selected_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        if len(group_targets) == 1:
            target_value = int(group[0].value) + 1
            for candidate in group:
                local_offset = int(candidate.offset) - base
                segment[local_offset:local_offset + 4] = target_value.to_bytes(4, 'little', signed=False)
            consistent = all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == target_value for candidate in group))
            same_counts['same_target_overlap_group_count'] += 1
            same_counts['same_target_overlap_candidate_count'] += len(impacted)
            if consistent:
                same_counts['shift_consistent_group_count'] += 1
                same_counts['shift_consistent_candidate_count'] += len(impacted)
                status = 'shift_consistent'
            else:
                same_counts['shift_conflict_group_count'] += 1
                same_counts['shift_conflict_candidate_count'] += len(impacted)
                status = 'shift_conflict'
                same_resource_alias_counts['same_target_shift_conflict_group_count'] += 1
                same_resource_alias_counts['same_target_shift_conflict_candidate_count'] += len(impacted)
                is_resource_reference_group = all((_candidate_target_role(decoded, candidate) == 'resource_reference' for candidate in group))
                is_alias = len(group) == 2 and len(impacted) == 2 and (tuple((offset - base for offset in offsets)) == (0, 3)) and is_resource_reference_group and all((int(candidate.value) == 65536 for candidate in group)) and all((bytes(payload[int(candidate.offset):int(candidate.offset) + 4]).hex() == '00000100' for candidate in group)) and all((span_position(candidate) == 'near_end_le_64' for candidate in group))
                if is_alias:
                    same_resource_alias_counts['resource_alias_group_count'] += 1
                    same_resource_alias_counts['resource_alias_candidate_count'] += len(impacted)
                elif is_resource_reference_group:
                    same_resource_alias_counts['resource_reference_non_alias_group_count'] += 1
                    same_resource_alias_counts['resource_reference_non_alias_candidate_count'] += len(impacted)
                else:
                    same_resource_alias_counts['other_group_count'] += 1
                    same_resource_alias_counts['other_candidate_count'] += len(impacted)
            key = profile_key(group, impacted, status)
            same_profile_counts[key] = same_profile_counts.get(key, 0) + 1
            continue
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset:local_offset + 4] = target_value.to_bytes(4, 'little', signed=False)
        consistent = all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == expected_by_id[id(candidate)] for candidate in group))
        mixed_counts['mixed_target_overlap_group_count'] += 1
        mixed_counts['mixed_target_overlap_candidate_count'] += len(impacted)
        if consistent:
            mixed_counts['shift_consistent_group_count'] += 1
            mixed_counts['shift_consistent_candidate_count'] += len(impacted)
            status = 'shift_consistent'
        else:
            mixed_counts['shift_conflict_group_count'] += 1
            mixed_counts['shift_conflict_candidate_count'] += len(impacted)
            status = 'shift_conflict'
        key = profile_key(group, impacted, status)
        mixed_profile_counts[key] = mixed_profile_counts.get(key, 0) + 1
        if any((_candidate_target_role(decoded, candidate) == 'resource_reference' for candidate in impacted)):
            key = detail_key(group, impacted, status)
            mixed_resource_reference_detail_counts[key] = mixed_resource_reference_detail_counts.get(key, 0) + 1
    result['selected_resize_offset_candidate_same_target_overlap_shift_conflict_profile_counts'] = dict(sorted(same_profile_counts.items()))
    result['selected_resize_offset_candidate_mixed_target_overlap_shift_conflict_profile_counts'] = dict(sorted(mixed_profile_counts.items()))
    result['selected_resize_offset_candidate_mixed_target_resource_reference_group_detail_counts'] = dict(sorted(mixed_resource_reference_detail_counts.items()))
    return result


def _resize_impact_unique_offset_candidate_overlap_counts(decoded: object, rows: object, *, target_role: str | None=None) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts = {'non_overlapping_count': 0, 'overlapping_count': 0}
    overlap_groups = _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ())))
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    for candidate in _unique_offset_candidates(candidates):
        if target_role is not None and _candidate_target_role(decoded, candidate) != target_role:
            continue
        key = 'overlapping_count' if id(candidate) in overlapping_ids else 'non_overlapping_count'
        counts[key] += 1
    return counts


def _resize_impact_unique_offset_candidate_profile_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_neighbor_byte_class, _offset_candidate_signed_distance_bucket, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    for candidate in _unique_offset_candidates(candidates):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
        alignment = 'aligned' if start % 4 == 0 else 'unaligned'
        neighbor = _offset_candidate_neighbor_byte_class(payload, candidate)
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|{alignment}|{span_position}|{neighbor}|{distance}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_profile_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_neighbor_byte_class, _offset_candidate_overlap_groups, _offset_candidate_signed_distance_bucket, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    overlap_groups = _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ())))
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    for candidate in _unique_offset_candidates(candidates):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        overlap = 'overlapping' if id(candidate) in overlapping_ids else 'non_overlapping'
        span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
        alignment = 'aligned' if start % 4 == 0 else 'unaligned'
        neighbor = _offset_candidate_neighbor_byte_class(payload, candidate)
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{overlap}|{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|{alignment}|{span_position}|{neighbor}|{distance}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_group_profile_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        if len(group) < 2 or not any((id(candidate) in impacted_ids for candidate in group)):
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group}))
        impacted_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group if id(candidate) in impacted_ids}))
        key = f'size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_overlap_group_target_identity_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        impacted_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in impacted}
        group_relation = 'same_target_identity' if len(group_targets) == 1 else 'mixed_target_identity'
        impacted_relation = 'same_target_identity' if len(impacted_targets) == 1 else 'mixed_target_identity'
        key = f'size_{len(group)}|width_{width}|deltas_{deltas}|group_{group_relation}|impacted_{impacted_relation}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_same_target_overlap_collapse_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts = {}
    counts.update({'impacted_overlap_group_count': 0, 'impacted_overlap_candidate_count': 0})
    counts.update({'same_target_duplicate_group_count': 0, 'same_target_duplicate_candidate_count': 0})
    counts.update({'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0})
    counts.update({'blocker_group_count_after_same_target_collapse': 0, 'blocker_candidate_count_after_same_target_collapse': 0})
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        counts['impacted_overlap_group_count'] += 1
        counts['impacted_overlap_candidate_count'] += len(impacted)
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            counts['same_target_duplicate_group_count'] += 1
            counts['same_target_duplicate_candidate_count'] += len(impacted)
        else:
            counts['mixed_target_group_count'] += 1
            counts['mixed_target_candidate_count'] += len(impacted)
    counts['blocker_group_count_after_same_target_collapse'] = counts['mixed_target_group_count']
    counts['blocker_candidate_count_after_same_target_collapse'] = counts['mixed_target_candidate_count']
    return counts


def _resize_impact_unique_offset_candidate_same_target_overlap_shift_conflict_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts = {}
    counts.update({'same_target_overlap_group_count': 0, 'same_target_overlap_candidate_count': 0})
    counts.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    counts.update({'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0})
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b'')
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset:local_offset + 4] = int(target_value).to_bytes(4, 'little', signed=False)
        consistent = all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == target_value for candidate in group))
        counts['same_target_overlap_group_count'] += 1
        counts['same_target_overlap_candidate_count'] += len(impacted)
        if consistent:
            counts['shift_consistent_group_count'] += 1
            counts['shift_consistent_candidate_count'] += len(impacted)
        else:
            counts['shift_conflict_group_count'] += 1
            counts['shift_conflict_candidate_count'] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_same_target_shift_conflict_group_detail_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b'')
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset:local_offset + 4] = int(target_value).to_bytes(4, 'little', signed=False)
        if all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == target_value for candidate in group)):
            continue

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start <= int(getattr(span, 'end', 0)) - 4), None)
            span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, start + 4, span)
            return f'delta_{start - base}:{_candidate_target_identity_key(decoded, candidate)}|word_{bytes(payload[start:start + 4]).hex()}|mod4_{start % 4}|{span_position}'
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_details = ','.join(sorted((detail(candidate) for candidate in group)))
        impacted_details = ','.join(sorted((detail(candidate) for candidate in impacted)))
        key = f'size_{len(group)}|deltas_{deltas}|group={group_details}|impacted={impacted_details}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_same_target_resource_alias_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts = {}
    counts.update({'same_target_conflict_group_count': 0, 'same_target_conflict_candidate_count': 0})
    counts.update({'resource_alias_group_count': 0, 'resource_alias_candidate_count': 0})
    counts.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b'')
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) != 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        target_value = int(group[0].value) + 1
        segment = bytearray(data[base:end])
        for candidate in group:
            local_offset = int(candidate.offset) - base
            segment[local_offset:local_offset + 4] = int(target_value).to_bytes(4, 'little', signed=False)
        if all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == target_value for candidate in group)):
            continue
        counts['same_target_conflict_group_count'] += 1
        counts['same_target_conflict_candidate_count'] += len(impacted)

        def span_position(candidate: object) -> str:
            start = int(candidate.offset)
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start <= int(getattr(span, 'end', 0)) - 4), None)
            return 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, start + 4, span)
        is_alias = len(group) == 2 and len(impacted) == 2 and (tuple((offset - base for offset in offsets)) == (0, 3)) and all((_candidate_target_role(decoded, candidate) == 'resource_reference' for candidate in group)) and all((int(candidate.value) == 65536 for candidate in group)) and all((bytes(payload[int(candidate.offset):int(candidate.offset) + 4]).hex() == '00000100' for candidate in group)) and all((span_position(candidate) == 'near_end_le_64' for candidate in group))
        if is_alias:
            counts['resource_alias_group_count'] += 1
            counts['resource_alias_candidate_count'] += len(impacted)
        else:
            counts['remaining_group_count'] += 1
            counts['remaining_candidate_count'] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_overlap_shift_conflict_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts = {}
    counts.update({'mixed_target_overlap_group_count': 0, 'mixed_target_overlap_candidate_count': 0})
    counts.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    counts.update({'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0})
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b'')
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset:local_offset + 4] = target_value.to_bytes(4, 'little', signed=False)
        consistent = all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == expected_by_id[id(candidate)] for candidate in group))
        counts['mixed_target_overlap_group_count'] += 1
        counts['mixed_target_overlap_candidate_count'] += len(impacted)
        if consistent:
            counts['shift_consistent_group_count'] += 1
            counts['shift_consistent_candidate_count'] += len(impacted)
        else:
            counts['shift_conflict_group_count'] += 1
            counts['shift_conflict_candidate_count'] += len(impacted)
    return counts


def _mixed_target_shift_consistent_overlap_groups(decoded: object, rows: object, payload: bytes) -> tuple[tuple[tuple[object, ...], tuple[object, ...], str], ...]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    data = bytes(payload or b'')
    groups: list[tuple[tuple[object, ...], tuple[object, ...], str]] = []
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        end = offsets[-1] + 4
        if base < 0 or end > len(data):
            continue
        segment = bytearray(data[base:end])
        expected_by_id: dict[int, int] = {}
        for candidate in group:
            local_offset = int(candidate.offset) - base
            target_value = int(candidate.value) + 1
            expected_by_id[id(candidate)] = target_value
            segment[local_offset:local_offset + 4] = target_value.to_bytes(4, 'little', signed=False)
        if all((int.from_bytes(segment[int(candidate.offset) - base:int(candidate.offset) - base + 4], 'little') == expected_by_id[id(candidate)] for candidate in group)):
            deltas = ','.join((str(offset - base) for offset in offsets))
            groups.append((group, impacted, deltas))
    return tuple(groups)


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_profile_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role
    counts: dict[str, int] = {}
    for group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        width = offsets[-1] + 4 - offsets[0]
        group_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group}))
        impacted_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in impacted}))
        key = f'size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_identity_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _group, impacted, _deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_shape_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _candidate_target_text
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for _group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        for candidate in impacted:
            start = int(candidate.offset)
            end = start + 4
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
            span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
            key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|{_candidate_target_text(decoded, candidate)}|word_{bytes(payload[start:end]).hex()}|mod4_{start % 4}|{span_position}|deltas_{deltas}'
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_group_detail_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _preserved_span_position_bucket
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for group, impacted, deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]

        def detail(candidate: object) -> str:
            start = int(candidate.offset)
            end = start + 4
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
            span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
            return f'delta_{start - base}:{_candidate_target_identity_key(decoded, candidate)}|word_{bytes(payload[start:end]).hex()}|mod4_{start % 4}|{span_position}'
        group_details = ','.join(sorted((detail(candidate) for candidate in group)))
        impacted_details = ','.join(sorted((detail(candidate) for candidate in impacted)))
        key = f'size_{len(group)}|deltas_{deltas}|group={group_details}|impacted={impacted_details}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_shift_consistent_metadata_collision_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _candidate_target_text
    counts = {}
    counts.update({'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0})
    counts.update({'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0})
    counts.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    for group, impacted, _deltas in _mixed_target_shift_consistent_overlap_groups(decoded, rows, payload):
        impacted_ids = {id(candidate) for candidate in impacted}
        counts['shift_consistent_group_count'] += 1
        counts['shift_consistent_candidate_count'] += len(impacted)
        collision = any((id(candidate) not in impacted_ids and _candidate_target_role(decoded, candidate) == 'member_type' and (str(candidate.target_kind) == 'string_end') and (int(candidate.value) == 192) and (int(candidate.target_field_index) == 8) and (_candidate_target_text(decoded, candidate) == 'bool') and (bytes(payload[int(candidate.offset):int(candidate.offset) + 4]).hex() == 'c0000000') for candidate in group))
        if collision:
            counts['metadata_collision_group_count'] += 1
            counts['metadata_collision_candidate_count'] += len(impacted)
        else:
            counts['remaining_group_count'] += 1
            counts['remaining_candidate_count'] += len(impacted)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_overlap_blocker_profile_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group}))
        impacted_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in impacted}))
        key = f'size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|impacted={impacted_profiles}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_target_identity_key(decoded: object, candidate: object) -> str:
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _candidate_target_text
    return f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|{_candidate_target_text(decoded, candidate)}'
