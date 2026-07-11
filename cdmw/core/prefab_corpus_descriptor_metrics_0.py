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


def _transform_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_transform', False):
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _transform_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if not getattr(declaration, 'is_transform', False):
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _nonzero_word3_offset_candidate_status_counts(signature_offset_candidate_counts: Mapping[str, object]) -> dict[str, int]:
    counts = {'with_offset_candidate': 0, 'without_offset_candidate': 0}
    for key, value in signature_offset_candidate_counts.items():
        parts = str(key).rsplit('|', 2)
        if len(parts) != 3:
            continue
        _type_name, words_text, status = parts
        if status not in counts:
            continue
        words = words_text.split(',')
        if len(words) <= 3 or int(words[3]) == 0:
            continue
        counts[status] += int(value or 0)
    return counts


def _descriptor_kind_nonzero_word3_offset_candidate_status_counts(kind_status_counts: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, status_counts in kind_status_counts.items():
        for status in ('with_offset_candidate', 'without_offset_candidate'):
            counts[f'{kind}|{status}'] = int(status_counts.get(status) or 0)
    return dict(sorted(counts.items()))


def _descriptor_kind_nonzero_word3_offset_candidate_target_counts(kind_target_counts: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, target_counts in kind_target_counts.items():
        for target, value in target_counts.items():
            counts[f'{kind}|{target}'] = int(value or 0)
    return dict(sorted(counts.items()))


def _transform_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or not getattr(owner, 'is_transform', False):
            continue
        words = ','.join((str(int(value)) for value in getattr(owner, 'descriptor_words_le_u16', ())))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _nonzero_word3_offset_candidate_target_counts(signature_offset_candidate_target_counts: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in signature_offset_candidate_target_counts.items():
        parts = str(key).rsplit('|', 3)
        if len(parts) != 4:
            continue
        _type_name, words_text, role, target_kind = parts
        words = words_text.split(',')
        if len(words) <= 3 or int(words[3]) == 0:
            continue
        target_key = f'{role}|{target_kind}'
        counts[target_key] = counts.get(target_key, 0) + int(value or 0)
    return dict(sorted(counts.items()))


def _transform_descriptor_word_value_counts(declarations: object, word_index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_transform', False):
            continue
        words = getattr(declaration, 'descriptor_words_le_u16', ())
        if len(words) <= word_index:
            continue
        key = str(int(words[word_index]))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _transform_theoretical_payload_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_transform', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        payload_bytes = int(words[1]) if len(words) > 1 else 0
        if payload_bytes <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{payload_bytes}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _transform_theoretical_payload_span_fit_metrics(decoded: object) -> dict[str, object]:
    from cdmw.core.prefab_corpus_array_metrics import _member_descriptor_overlaps, _span_overlaps
    from cdmw.core.prefab_corpus_candidate_roles import _member_descriptor_relation_to_declaration, _string_field_relation_to_declaration, _string_field_role
    metrics = {}
    metrics.update({'member_rows': 0, 'byte_count': 0})
    metrics.update({'exact_preserved_span_rows': 0, 'later_preserved_span_fit_rows': 0})
    metrics.update({'no_preserved_span_fit_rows': 0, 'immediate_window_string_span_overlap_rows': 0})
    metrics.update({'immediate_window_string_span_overlap_count': 0, 'immediate_window_string_span_role_counts': {}})
    metrics.update({'immediate_window_string_span_relation_counts': {}, 'later_fit_with_intervening_string_or_declaration_rows': 0})
    metrics.update({'later_fit_gap_string_span_relation_counts': {}, 'later_fit_gap_member_descriptor_relation_counts': {}})
    layout_spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    preserved_spans = tuple((span for span in layout_spans if getattr(span, 'kind', '') == 'preserved'))
    string_spans = tuple((span for span in layout_spans if getattr(span, 'kind', '') == 'string_field'))
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    for declaration in declarations:
        if not getattr(declaration, 'is_transform', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        theoretical_bytes = int(words[1]) if len(words) > 1 else 0
        if theoretical_bytes <= 0:
            continue
        descriptor_end = int(getattr(declaration, 'descriptor_offset', 0)) + int(getattr(declaration, 'descriptor_byte_length', 0))
        immediate_end = descriptor_end + theoretical_bytes
        metrics['member_rows'] += 1
        metrics['byte_count'] += theoretical_bytes
        immediate_string_overlaps = tuple((span for span in string_spans if _span_overlaps(span, descriptor_end, immediate_end)))
        if immediate_string_overlaps:
            metrics['immediate_window_string_span_overlap_rows'] += 1
            metrics['immediate_window_string_span_overlap_count'] += len(immediate_string_overlaps)
            role_counts = metrics['immediate_window_string_span_role_counts']
            relation_counts = metrics['immediate_window_string_span_relation_counts']
            assert isinstance(role_counts, dict)
            assert isinstance(relation_counts, dict)
            for span in immediate_string_overlaps:
                field_index = int(getattr(span, 'field_index', -1))
                role = _string_field_role(decoded, field_index)
                relation = _string_field_relation_to_declaration(decoded, declaration, field_index)
                role_counts[role] = role_counts.get(role, 0) + 1
                relation_counts[relation] = relation_counts.get(relation, 0) + 1
        exact_span = any((int(getattr(span, 'start', 0)) == descriptor_end and int(getattr(span, 'end', 0)) == descriptor_end + theoretical_bytes for span in preserved_spans))
        if exact_span:
            metrics['exact_preserved_span_rows'] += 1
            continue
        later_span = next((span for span in sorted(preserved_spans, key=lambda item: int(getattr(item, 'start', 0))) if int(getattr(span, 'start', 0)) >= descriptor_end and int(getattr(span, 'end', 0)) - int(getattr(span, 'start', 0)) >= theoretical_bytes), None)
        if later_span is not None:
            metrics['later_preserved_span_fit_rows'] += 1
            later_start = int(getattr(later_span, 'start', 0))
            if later_start > descriptor_end:
                gap_strings = tuple((span for span in string_spans if _span_overlaps(span, descriptor_end, later_start)))
                gap_declarations = tuple((other for other in declarations if _member_descriptor_overlaps(other, descriptor_end, later_start)))
                if gap_strings or gap_declarations:
                    metrics['later_fit_with_intervening_string_or_declaration_rows'] += 1
                string_relation_counts = metrics['later_fit_gap_string_span_relation_counts']
                descriptor_relation_counts = metrics['later_fit_gap_member_descriptor_relation_counts']
                assert isinstance(string_relation_counts, dict)
                assert isinstance(descriptor_relation_counts, dict)
                for span in gap_strings:
                    relation = _string_field_relation_to_declaration(decoded, declaration, int(getattr(span, 'field_index', -1)))
                    string_relation_counts[relation] = string_relation_counts.get(relation, 0) + 1
                for other in gap_declarations:
                    relation = _member_descriptor_relation_to_declaration(declaration, other)
                    descriptor_relation_counts[relation] = descriptor_relation_counts.get(relation, 0) + 1
        else:
            metrics['no_preserved_span_fit_rows'] += 1
    return metrics


def _transform_exact_payload_owner_counts(decoded: object) -> dict[str, int]:
    counts = {'member_rows': 0, 'value_rows': 0}
    preserved_spans = tuple((span for span in getattr(getattr(decoded, 'layout', None), 'spans', ()) if getattr(span, 'kind', '') == 'preserved'))
    for declaration in getattr(decoded, 'member_declarations', ()):
        if not getattr(declaration, 'is_transform', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        payload_bytes = int(words[1]) if len(words) > 1 else 0
        if payload_bytes <= 0:
            continue
        descriptor_end = int(getattr(declaration, 'descriptor_offset', 0)) + int(getattr(declaration, 'descriptor_byte_length', 0))
        if any((int(getattr(span, 'start', 0)) == descriptor_end and int(getattr(span, 'end', 0)) == descriptor_end + payload_bytes for span in preserved_spans)):
            counts['member_rows'] += 1
            counts['value_rows'] += 1
    return counts


def _reference_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'reference':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'reference':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, 'descriptor_kind', '')) != 'reference':
            continue
        words = ','.join((str(int(value)) for value in getattr(owner, 'descriptor_words_le_u16', ())))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, 'descriptor_kind', '')) not in {'scalar', 'bool'}:
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '')) not in {'scalar', 'bool'}:
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _scalar_or_bool_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, 'descriptor_kind', '')) not in {'scalar', 'bool'}:
            continue
        words = ','.join((str(int(value)) for value in getattr(owner, 'descriptor_words_le_u16', ())))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'string':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'string':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, 'descriptor_kind', '')) != 'string':
            continue
        words = ','.join((str(int(value)) for value in getattr(owner, 'descriptor_words_le_u16', ())))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'descriptor':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '')) != 'descriptor':
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _generic_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or str(getattr(owner, 'descriptor_kind', '')) != 'descriptor':
            continue
        words = ','.join((str(int(value)) for value in getattr(owner, 'descriptor_words_le_u16', ())))
        field_index = int(candidate.target_field_index)
        if field_index in reference_indexes:
            role = 'resource_reference'
        elif field_index in member_name_indexes:
            role = 'member_name'
        elif field_index in member_type_indexes:
            role = 'member_type'
        else:
            role = 'other_string'
        key = f"{getattr(owner, 'type_name', '')}|{words}|{role}|{candidate.target_kind}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_owner_kind_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None:
            continue
        kind = str(getattr(owner, 'descriptor_kind', '') or 'unknown')
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_owner_kind_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None:
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
        kind = str(getattr(owner, 'descriptor_kind', '') or 'unknown')
        key = f'{kind}|{role}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _descriptor_tail_metrics(declarations: object, kind: str) -> dict[str, int]:
    metrics = {'member_count': 0, 'tail_byte_count': 0}
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '') or '') != kind:
            continue
        tail_bytes = max(0, int(getattr(declaration, 'descriptor_byte_length', 0)) - 8)
        if tail_bytes <= 0:
            continue
        metrics['member_count'] += 1
        metrics['tail_byte_count'] += tail_bytes
    return metrics


def _descriptor_tail_kind_metrics(declarations: object) -> dict[str, dict[str, int]]:
    member_counts: dict[str, int] = {}
    byte_counts: dict[str, int] = {}
    for declaration in declarations:
        tail_bytes = max(0, int(getattr(declaration, 'descriptor_byte_length', 0)) - 8)
        if tail_bytes <= 0:
            continue
        kind = str(getattr(declaration, 'descriptor_kind', '') or 'unknown')
        member_counts[kind] = member_counts.get(kind, 0) + 1
        byte_counts[kind] = byte_counts.get(kind, 0) + tail_bytes
    return {'member_counts': dict(sorted(member_counts.items())), 'byte_counts': dict(sorted(byte_counts.items()))}


def _descriptor_tail_member_detail_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for declaration in declarations:
        tail_bytes = max(0, int(getattr(declaration, 'descriptor_byte_length', 0)) - 8)
        if tail_bytes <= 0:
            continue
        kind = str(getattr(declaration, 'descriptor_kind', '') or 'unknown')
        name = str(getattr(declaration, 'name', '') or '')
        type_name = str(getattr(declaration, 'type_name', '') or '')
        words = ','.join((str(int(value)) for value in tuple(getattr(declaration, 'descriptor_words_le_u16', ()))[:4]))
        key = f'{kind}|{name}|{type_name}|{words}|{tail_bytes}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_tail_record_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '') or '') != 'reference':
            continue
        tail_bytes = max(0, int(getattr(declaration, 'descriptor_byte_length', 0)) - 8)
        if tail_bytes <= 0:
            continue
        words = tuple(getattr(declaration, 'descriptor_words_le_u16', ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 4095
        if stride <= 0 or tail_bytes % stride != 0:
            key = f'not_exact|{word2}|{stride}|{tail_bytes}'
        else:
            key = f'exact|{word2}|{stride}|{tail_bytes // stride}|{tail_bytes}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _reference_descriptor_tail_offset_candidate_mod_counts(decoded: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if str(getattr(declaration, 'descriptor_kind', '') or '') != 'reference':
            continue
        descriptor_offset = int(getattr(declaration, 'descriptor_offset', 0))
        descriptor_length = int(getattr(declaration, 'descriptor_byte_length', 0))
        tail_bytes = max(0, descriptor_length - 8)
        if tail_bytes <= 0:
            continue
        words = tuple(getattr(declaration, 'descriptor_words_le_u16', ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 4095
        if stride <= 0 or tail_bytes % stride != 0:
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        for candidate in candidates:
            candidate_offset = int(getattr(candidate, 'offset', -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            target_kind = str(getattr(candidate, 'target_kind', '') or 'unknown')
            mod = (candidate_offset - tail_start) % stride
            key = f'{word2}|{stride}|{target_kind}|{mod}'
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
