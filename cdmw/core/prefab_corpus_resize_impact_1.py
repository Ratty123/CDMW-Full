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


def _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
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
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _identity_repeat_summary(counts: Mapping[str, int]) -> dict[str, int]:
    values = [int(value) for value in counts.values()]
    repeated = [value for value in values if value > 1]
    high_repeat = [value for value in values if value >= 10]
    _prefab_result = {}
    _prefab_result.update({'candidate_count': sum(values), 'unique_identity_count': len(values)})
    _prefab_result.update({'repeated_identity_count': len(repeated), 'repeated_candidate_count': sum(repeated)})
    _prefab_result.update({'high_repeat_10_identity_count': len(high_repeat), 'high_repeat_10_candidate_count': sum(high_repeat)})
    _prefab_result.update({'max_identity_candidate_count': max(values, default=0)})
    return _prefab_result


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_collapse_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts = {}
    counts.update({'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0})
    counts.update({'high_repeat_identity_count': 0, 'high_repeat_candidate_count': 0})
    counts.update({'remaining_group_count_after_high_repeat_collapse': 0, 'remaining_candidate_count_after_high_repeat_collapse': 0})
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    counts['high_repeat_identity_count'] = len(high_repeat_identities)
    counts['high_repeat_candidate_count'] = sum((int(identity_counts[identity]) for identity in high_repeat_identities))
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        counts['mixed_target_group_count'] += 1
        counts['mixed_target_candidate_count'] += len(impacted)
        remaining = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities))
        if remaining:
            counts['remaining_group_count_after_high_repeat_collapse'] += 1
            counts['remaining_candidate_count_after_high_repeat_collapse'] += len(remaining)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_profile_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_owner_kind, _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        remaining = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities))
        if not remaining:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        width = offsets[-1] + 4 - base
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in group}))
        remaining_profiles = ','.join(sorted({f'{_candidate_owner_kind(decoded, candidate)}:{_candidate_target_role(decoded, candidate)}:{candidate.target_kind}' for candidate in remaining}))
        key = f'size_{len(group)}|width_{width}|deltas_{deltas}|group={group_profiles}|remaining={remaining_profiles}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_identity_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        for candidate in impacted:
            key = _candidate_target_identity_key(decoded, candidate)
            if key in high_repeat_identities:
                continue
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_role_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts = {}
    counts.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    counts.update({'remaining_resource_reference_candidate_count': 0, 'remaining_metadata_candidate_count': 0})
    counts.update({'remaining_resource_reference_group_count': 0, 'remaining_metadata_only_group_count': 0})
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        remaining = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities))
        if not remaining:
            continue
        roles = [_candidate_target_role(decoded, candidate) for candidate in remaining]
        resource_count = sum((1 for role in roles if role == 'resource_reference'))
        counts['remaining_group_count'] += 1
        counts['remaining_candidate_count'] += len(remaining)
        counts['remaining_resource_reference_candidate_count'] += resource_count
        counts['remaining_metadata_candidate_count'] += len(remaining) - resource_count
        if resource_count:
            counts['remaining_resource_reference_group_count'] += 1
        else:
            counts['remaining_metadata_only_group_count'] += 1
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts(decoded: object, rows: object, payload: bytes, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))

    def detail(candidate: object, base: int) -> str:
        start = int(candidate.offset)
        span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start <= int(getattr(span, 'end', 0)) - 4), None)
        span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, start + 4, span)
        return f'delta_{start - base}:{_candidate_target_identity_key(decoded, candidate)}|word_{bytes(payload[start:start + 4]).hex()}|mod4_{start % 4}|{span_position}'
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities and _candidate_target_role(decoded, candidate) == 'resource_reference'))
        if not remaining_resource_references:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        deltas = ','.join((str(offset - base) for offset in offsets))
        group_details = ','.join(sorted((detail(candidate, base) for candidate in group)))
        remaining_details = ','.join(sorted((detail(candidate, base) for candidate in remaining_resource_references)))
        key = f'size_{len(group)}|deltas_{deltas}|group={group_details}|remaining_resource_reference={remaining_details}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts = {}
    counts.update({'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0})
    counts.update({'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0})
    counts.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities and _candidate_target_role(decoded, candidate) == 'resource_reference'))
        if not remaining_resource_references:
            continue
        counts['remaining_resource_reference_group_count'] += 1
        counts['remaining_resource_reference_candidate_count'] += len(remaining_resource_references)
        remaining_resource_reference_ids = {id(candidate) for candidate in remaining_resource_references}
        colliders = tuple((candidate for candidate in group if id(candidate) not in remaining_resource_reference_ids))
        if colliders and all((_candidate_target_role(decoded, candidate) != 'resource_reference' for candidate in colliders)):
            counts['metadata_collision_group_count'] += 1
            counts['metadata_collision_candidate_count'] += len(remaining_resource_references)
        else:
            counts['remaining_group_count'] += 1
            counts['remaining_candidate_count'] += len(remaining_resource_references)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts(decoded: object, rows: object, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts = {}
    counts.update({'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0})
    counts.update({'nonimpacted_reference_collision_group_count': 0, 'nonimpacted_reference_collision_candidate_count': 0})
    counts.update({'remaining_group_count': 0, 'remaining_candidate_count': 0})
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        remaining_resource_references = tuple((candidate for candidate in impacted if _candidate_target_identity_key(decoded, candidate) not in high_repeat_identities and _candidate_target_role(decoded, candidate) == 'resource_reference'))
        if not remaining_resource_references:
            continue
        counts['remaining_resource_reference_group_count'] += 1
        counts['remaining_resource_reference_candidate_count'] += len(remaining_resource_references)
        remaining_resource_reference_ids = {id(candidate) for candidate in remaining_resource_references}
        resource_reference_colliders = tuple((candidate for candidate in group if id(candidate) not in remaining_resource_reference_ids and _candidate_target_role(decoded, candidate) == 'resource_reference'))
        if resource_reference_colliders and all((id(candidate) not in impacted_ids for candidate in resource_reference_colliders)):
            counts['nonimpacted_reference_collision_group_count'] += 1
            counts['nonimpacted_reference_collision_candidate_count'] += len(remaining_resource_references)
        else:
            counts['remaining_group_count'] += 1
            counts['remaining_candidate_count'] += len(remaining_resource_references)
    return counts


def _resize_impact_unique_offset_candidate_mixed_target_high_repeat_identity_remaining_shape_counts(decoded: object, rows: object, payload: bytes, *, min_count: int=10) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _candidate_target_text, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    from cdmw.core.prefab_corpus_resize_impact_0 import _candidate_target_identity_key
    counts: dict[str, int] = {}
    identity_counts = _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_identity_counts(decoded, rows)
    high_repeat_identities = {identity for identity, count in identity_counts.items() if int(count) >= int(min_count)}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        deltas = ','.join((str(offset - base) for offset in offsets))
        for candidate in impacted:
            if _candidate_target_identity_key(decoded, candidate) in high_repeat_identities:
                continue
            start = int(candidate.offset)
            end = start + 4
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
            span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
            word = bytes(payload[start:end]).hex()
            key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|{_candidate_target_text(decoded, candidate)}|word_{word}|mod4_{start % 4}|{span_position}|deltas_{deltas}'
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_mixed_target_overlap_impacted_shape_counts(decoded: object, rows: object, payload: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_overlap_groups, _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _candidate_target_role, _candidate_target_text, _resize_impact_offset_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    impacted_ids = {id(candidate) for candidate in _unique_offset_candidates(candidates)}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for group in _offset_candidate_overlap_groups(tuple(getattr(decoded, 'offset_candidates', ()))):
        impacted = tuple((candidate for candidate in group if id(candidate) in impacted_ids))
        if len(group) < 2 or not impacted:
            continue
        group_targets = {(int(candidate.value), str(candidate.target_kind), int(candidate.target_field_index)) for candidate in group}
        if len(group_targets) == 1:
            continue
        offsets = tuple(sorted((int(candidate.offset) for candidate in group)))
        base = offsets[0]
        deltas = ','.join((str(offset - base) for offset in offsets))
        for candidate in impacted:
            start = int(candidate.offset)
            end = start + 4
            span = next((span for span in preserved_spans if int(getattr(span, 'start', 0)) <= start and end <= int(getattr(span, 'end', 0))), None)
            span_position = 'outside_preserved_span' if span is None else _preserved_span_position_bucket(start, end, span)
            word = bytes(payload[start:end]).hex()
            key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}|value_{int(candidate.value)}|field_{int(candidate.target_field_index)}|{_candidate_target_text(decoded, candidate)}|word_{word}|mod4_{start % 4}|{span_position}|deltas_{deltas}'
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_distance_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_signed_distance_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_resource_reference_candidate_multiplicities
    counts: dict[str, int] = {}
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}'
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_unique_resource_reference_target_profile_distance_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_signed_distance_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_resource_reference_candidate_multiplicities, _unique_offset_candidates
    counts: dict[str, int] = {}
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    candidates = _unique_offset_candidates(tuple((candidate for candidate, _count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows))))
    for candidate in candidates:
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        distance = _offset_candidate_signed_distance_bucket(candidate)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{distance}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_span_position_counts(decoded: object, rows: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _preserved_span_position_bucket
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_resource_reference_candidate_multiplicities
    counts: dict[str, int] = {}
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in spans if getattr(span, 'kind', '') == 'preserved'))
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
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
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_resource_reference_target_profile_neighbor_byte_class_counts(decoded: object, rows: object, data: bytes) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _offset_candidate_neighbor_byte_class
    from cdmw.core.prefab_corpus_candidate_roles import _resize_impact_resource_reference_candidate_multiplicities
    counts: dict[str, int] = {}
    extensions_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'extension', '') or '') for reference in getattr(decoded, 'references', ())}
    roles_by_field_index = {int(getattr(getattr(reference, 'field', None), 'index', -1)): str(getattr(reference, 'role', '') or '') for reference in getattr(decoded, 'references', ())}
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        alignment = 'aligned' if int(candidate.offset) % 4 == 0 else 'unaligned'
        role = roles_by_field_index.get(int(candidate.target_field_index), '')
        extension = extensions_by_field_index.get(int(candidate.target_field_index), '')
        byte_class = _offset_candidate_neighbor_byte_class(data, candidate)
        key = f'{alignment}|{candidate.target_kind}|{role}|{extension}|{byte_class}'
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))
