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


def _offset_candidate_overlap_count(decoded: object) -> int:
    previous_end = -1
    overlap_count = 0
    for candidate in sorted(getattr(decoded, 'offset_candidates', ()), key=lambda item: int(item.offset)):
        start = int(candidate.offset)
        end = start + 4
        if start < previous_end:
            overlap_count += 1
        previous_end = max(previous_end, end)
    return overlap_count


def _offset_candidate_overlap_groups(candidates: Sequence[object]) -> list[list[object]]:
    groups: list[list[object]] = []
    current: list[object] = []
    current_end = -1
    for candidate in sorted(candidates, key=lambda item: int(item.offset)):
        start = int(candidate.offset)
        end = start + 4
        if not current or start >= current_end:
            if current:
                groups.append(current)
            current = [candidate]
            current_end = end
            continue
        current.append(candidate)
        current_end = max(current_end, end)
    if current:
        groups.append(current)
    return groups


def _offset_candidate_group_metrics(candidates: Sequence[object]) -> dict[str, int]:
    metrics = {}
    metrics.update({'aligned_count': 0, 'unaligned_count': 0})
    metrics.update({'overlap_group_count': 0, 'overlapping_window_count': 0})
    metrics.update({'isolated_count': 0, 'aligned_isolated_count': 0})
    metrics.update({'unaligned_isolated_count': 0, 'unaligned_or_overlapping_count': 0})
    metrics.update({'target_string_length_prefix_count': 0, 'target_string_value_count': 0})
    metrics.update({'target_string_end_count': 0})
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    metrics['overlap_group_count'] = sum((1 for group in overlap_groups if len(group) > 1))
    metrics['overlapping_window_count'] = len(overlapping_ids)
    metrics['isolated_count'] = len(candidates) - len(overlapping_ids)
    for candidate in candidates:
        aligned = int(candidate.offset) % 4 == 0
        if int(candidate.offset) % 4 == 0:
            metrics['aligned_count'] += 1
        else:
            metrics['unaligned_count'] += 1
        if id(candidate) in overlapping_ids:
            metrics['unaligned_or_overlapping_count'] += 1
        elif aligned:
            metrics['aligned_isolated_count'] += 1
        else:
            metrics['unaligned_isolated_count'] += 1
            metrics['unaligned_or_overlapping_count'] += 1
        key = f'target_{str(candidate.target_kind)}_count'
        if key in metrics:
            metrics[key] += 1
    return metrics


def _offset_candidate_metrics(decoded: object) -> dict[str, int]:
    return _offset_candidate_group_metrics(tuple(getattr(decoded, 'offset_candidates', ())))


def _offset_candidate_outside_descriptor_metrics(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    outside_candidates = tuple((candidate for candidate in getattr(decoded, 'offset_candidates', ()) if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None))
    return _offset_candidate_group_metrics(outside_candidates)


def _mod4_counts(values: Sequence[int]) -> dict[str, int]:
    counts = {str(index): 0 for index in range(4)}
    for value in values:
        key = str(int(value) % 4)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sum_count_maps(rows: Sequence[Mapping[str, object]], key: str, defaults: Mapping[str, int]) -> dict[str, int]:
    counts = {str(name): int(value) for name, value in defaults.items()}
    for row in rows:
        values = row.get(key)
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            counts[str(name)] = counts.get(str(name), 0) + int(value or 0)
    return dict(sorted(counts.items(), key=lambda item: str(item[0])))


def _offset_candidate_outside_descriptor_mod4_counts(decoded: object) -> dict[str, dict[str, int]]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    outside_candidates = tuple((candidate for candidate in getattr(decoded, 'offset_candidates', ()) if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None))
    string_value_candidates = tuple((candidate for candidate in outside_candidates if str(candidate.target_kind) == 'string_value'))
    return {'candidate_offset_mod4_counts': _mod4_counts(tuple((int(candidate.offset) for candidate in outside_candidates))), 'target_value_mod4_counts': _mod4_counts(tuple((int(candidate.value) for candidate in outside_candidates))), 'string_value_candidate_offset_mod4_counts': _mod4_counts(tuple((int(candidate.offset) for candidate in string_value_candidates))), 'string_value_target_value_mod4_counts': _mod4_counts(tuple((int(candidate.value) for candidate in string_value_candidates)))}


def _offset_candidate_neighbor_byte_class(data: bytes, candidate: object) -> str:
    start = int(getattr(candidate, 'offset', -1))
    end = start + 4
    if start < 0 or end > len(data):
        return 'empty'
    context = data[max(0, start - 8):start] + data[end:min(len(data), end + 8)]
    if not context:
        return 'empty'
    if context.count(0) * 4 >= len(context):
        return 'nul_rich'
    printable = sum((1 for value in context if 32 <= value <= 126 or value in {9, 10, 13}))
    if printable * 4 >= len(context) * 3:
        return 'ascii_like'
    return 'binary_like'


def _offset_candidate_neighbor_byte_class_counts(data: bytes, candidates: Sequence[object]) -> dict[str, int]:
    counts = {'ascii_like': 0, 'binary_like': 0, 'empty': 0, 'nul_rich': 0}
    for candidate in candidates:
        key = _offset_candidate_neighbor_byte_class(data, candidate)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _offset_candidate_target_role_counts(candidates: Sequence[object], decoded: object) -> dict[str, int]:
    counts = {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}
    reference_indexes = {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            counts['resource_reference_count'] += 1
        elif field_index in member_name_indexes:
            counts['member_name_count'] += 1
        elif field_index in member_type_indexes:
            counts['member_type_count'] += 1
        else:
            counts['other_string_count'] += 1
    return counts


def _offset_candidate_target_role_kind_counts(candidates: Sequence[object], decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f'{role}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_span_position_counts(decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        position = _preserved_span_position_bucket(start, end, span)
        key = f'{role}|{candidate.target_kind}|{position}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_neighbor_byte_class_counts(data: bytes, decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f'{role}|{candidate.target_kind}|{byte_class}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_target_role_kind_span_position_neighbor_byte_class_counts(data: bytes, decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        position = _preserved_span_position_bucket(start, end, span)
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f'{role}|{candidate.target_kind}|{position}|{byte_class}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resource_reference_target_field_indexes(decoded: object) -> set[int]:
    return {int(getattr(getattr(reference, 'field', None), 'index', -1)) for reference in getattr(decoded, 'references', ())}


def _outside_member_descriptor_offset_candidates(decoded: object) -> tuple[object, ...]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    return tuple((candidate for candidate in getattr(decoded, 'offset_candidates', ()) if _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is None))


def _outside_member_descriptor_resource_reference_offset_candidates(decoded: object) -> tuple[object, ...]:
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    return tuple((candidate for candidate in _outside_member_descriptor_offset_candidates(decoded) if int(candidate.target_field_index) in reference_indexes))


def _outside_member_descriptor_preserved_middle_offset_candidates(decoded: object) -> tuple[object, ...]:
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    candidates = []
    for candidate in _outside_member_descriptor_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is not None and start != int(span.start) and (end != int(span.end)):
            candidates.append(candidate)
    return tuple(candidates)


def _preserved_span_byte_length_bucket(byte_length: int) -> str:
    if byte_length <= 16:
        return 'le_16'
    if byte_length <= 32:
        return 'le_32'
    if byte_length <= 64:
        return 'le_64'
    if byte_length <= 128:
        return 'le_128'
    return 'gt_128'


def _offset_candidate_preserved_span_byte_length_counts(decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    counts = {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in candidates:
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        bucket = _preserved_span_byte_length_bucket(int(span.end) - int(span.start))
        counts[bucket] += 1
    return counts


def _offset_candidate_outside_descriptor_target_role_counts(decoded: object) -> dict[str, dict[str, int]]:
    outside_candidates = _outside_member_descriptor_offset_candidates(decoded)
    string_value_candidates = tuple((candidate for candidate in outside_candidates if str(candidate.target_kind) == 'string_value'))
    return {'target_role_counts': _offset_candidate_target_role_counts(outside_candidates, decoded), 'string_value_target_role_counts': _offset_candidate_target_role_counts(string_value_candidates, decoded)}


def _offset_candidate_outside_descriptor_resource_reference_metrics(decoded: object) -> dict[str, int]:
    candidates = _outside_member_descriptor_resource_reference_offset_candidates(decoded)
    metrics = _offset_candidate_group_metrics(candidates)
    metrics['count'] = len(candidates)
    return metrics


def _offset_candidate_alignment_target_kind_counts(candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        key = f'{alignment}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _aligned_isolated_offset_candidates(candidates: Sequence[object]) -> tuple[object, ...]:
    overlap_groups = _offset_candidate_overlap_groups(candidates)
    overlapping_ids = {id(candidate) for group in overlap_groups if len(group) > 1 for candidate in group}
    return tuple((candidate for candidate in candidates if id(candidate) not in overlapping_ids and int(candidate.offset) % 4 == 0))


def _offset_candidate_outside_descriptor_preserved_middle_metrics(decoded: object, data: bytes) -> dict[str, object]:
    candidates = _outside_member_descriptor_preserved_middle_offset_candidates(decoded)
    metrics = _offset_candidate_group_metrics(candidates)
    metrics['count'] = len(candidates)
    _prefab_result = {}
    _prefab_result.update({'group_metrics': metrics, 'target_role_counts': _offset_candidate_target_role_counts(candidates, decoded)})
    _prefab_result.update({'target_role_kind_counts': _offset_candidate_target_role_kind_counts(candidates, decoded), 'target_role_kind_span_position_counts': _offset_candidate_target_role_kind_span_position_counts(decoded, candidates)})
    _prefab_result.update({'target_role_kind_neighbor_byte_class_counts': _offset_candidate_target_role_kind_neighbor_byte_class_counts(data, decoded, candidates), 'target_role_kind_span_position_neighbor_byte_class_counts': _offset_candidate_target_role_kind_span_position_neighbor_byte_class_counts(data, decoded, candidates)})
    _prefab_result.update({'target_role_kind_signed_distance_counts': _offset_candidate_target_role_kind_signed_distance_counts(decoded, candidates), 'span_byte_length_counts': _offset_candidate_preserved_span_byte_length_counts(decoded, candidates)})
    return _prefab_result


def _offset_candidate_resource_reference_mod4_counts(decoded: object) -> dict[str, dict[str, int]]:
    candidates = _outside_member_descriptor_resource_reference_offset_candidates(decoded)
    return {'candidate_offset_mod4_counts': _mod4_counts(tuple((int(candidate.offset) for candidate in candidates))), 'target_value_mod4_counts': _mod4_counts(tuple((int(candidate.value) for candidate in candidates)))}


def _offset_candidate_resource_reference_alignment_target_kind_counts(decoded: object) -> dict[str, int]:
    return _offset_candidate_alignment_target_kind_counts(_outside_member_descriptor_resource_reference_offset_candidates(decoded))


def _offset_candidate_resource_reference_alignment_target_kind_extension_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        key = f'{alignment}|{candidate.target_kind}|{extension}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_alignment_target_kind_role_counts(decoded: object) -> dict[str, int]:
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        key = f'{alignment}|{candidate.target_kind}|{role}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_alignment_target_kind_span_bucket_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        alignment = 'aligned' if start % 4 == 0 else 'unaligned'
        bucket = _preserved_span_byte_length_bucket(int(span.end) - int(span.start))
        key = f'{alignment}|{candidate.target_kind}|{bucket}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _preserved_span_position_bucket(candidate_start: int, candidate_end: int, span: object) -> str:
    span_start = int(getattr(span, 'start', 0))
    span_end = int(getattr(span, 'end', 0))
    if candidate_start == span_start:
        return 'at_start'
    if candidate_end == span_end:
        return 'at_end'
    distance_from_start = candidate_start - span_start
    distance_to_end = span_end - candidate_end
    if distance_from_start <= 16:
        return 'near_start_le_16'
    if distance_to_end <= 16:
        return 'near_end_le_16'
    if distance_from_start <= 64:
        return 'near_start_le_64'
    if distance_to_end <= 64:
        return 'near_end_le_64'
    return 'middle'


def _offset_candidate_resource_reference_alignment_target_kind_span_position_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        alignment = 'aligned' if start % 4 == 0 else 'unaligned'
        bucket = _preserved_span_position_bucket(start, end, span)
        key = f'{alignment}|{candidate.target_kind}|{bucket}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_span_position_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    counts: dict[str, int] = {}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        start = int(candidate.offset)
        end = start + 4
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
        if span is None:
            continue
        alignment = 'aligned' if start % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        position = _preserved_span_position_bucket(start, end, span)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{position}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_signed_distance_bucket(candidate: object) -> str:
    delta = int(getattr(candidate, 'value', 0)) - int(getattr(candidate, 'offset', 0))
    if delta == 0:
        return 'self'
    direction = 'forward' if delta > 0 else 'backward'
    distance = abs(delta)
    if distance <= 16:
        return f'{direction}_le_16'
    if distance <= 64:
        return f'{direction}_le_64'
    if distance <= 256:
        return f'{direction}_le_256'
    if distance <= 1024:
        return f'{direction}_le_1024'
    return f'{direction}_gt_1024'


def _offset_candidate_target_role_kind_signed_distance_counts(decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in candidates:
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{role}|{candidate.target_kind}|{distance}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_distance_counts(decoded: object) -> dict[str, int]:
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_resource_reference_target_profile_neighbor_byte_class_counts(decoded: object, data: bytes) -> dict[str, int]:
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    counts: dict[str, int] = {}
    for candidate in _outside_member_descriptor_resource_reference_offset_candidates(decoded):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{byte_class}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _offset_candidate_outside_descriptor_aligned_isolated_role_kind_counts(decoded: object) -> dict[str, int]:
    candidates = _aligned_isolated_offset_candidates(_outside_member_descriptor_offset_candidates(decoded))
    return _offset_candidate_target_role_kind_counts(candidates, decoded)


def _offset_candidate_preserved_span_shape_counts(decoded: object, candidates: Sequence[object]) -> dict[str, int]:
    metrics = {}
    metrics.update({'in_preserved_span_count': 0, 'outside_preserved_span_count': 0})
    metrics.update({'preserved_span_exact_4_count': 0, 'preserved_span_le_8_count': 0})
    metrics.update({'at_preserved_span_start_count': 0, 'at_preserved_span_end_count': 0})
    metrics.update({'in_preserved_span_middle_count': 0})
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate in candidates:
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
        if span_length == 4:
            metrics['preserved_span_exact_4_count'] += 1
        if span_length <= 8:
            metrics['preserved_span_le_8_count'] += 1
        if start == span_start:
            metrics['at_preserved_span_start_count'] += 1
        if end == span_end:
            metrics['at_preserved_span_end_count'] += 1
        if start != span_start and end != span_end:
            metrics['in_preserved_span_middle_count'] += 1
    return metrics
