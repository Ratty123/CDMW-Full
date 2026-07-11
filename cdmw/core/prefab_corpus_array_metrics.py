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


def _array_descriptor_signature_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        key = f"{getattr(declaration, 'type_name', '')}|{words}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_descriptor_signature_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if not getattr(declaration, 'is_array', False):
            continue
        words = ','.join((str(int(value)) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        key = f"{getattr(declaration, 'type_name', '')}|{words}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_descriptor_signature_offset_candidate_target_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    reference_indexes = _resource_reference_target_field_indexes(decoded)
    member_name_indexes = {int(declaration.name_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    member_type_indexes = {int(declaration.type_field_index) for declaration in getattr(decoded, 'member_declarations', ())}
    for candidate in getattr(decoded, 'offset_candidates', ()):
        owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
        if owner is None or not getattr(owner, 'is_array', False):
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


def _array_descriptor_word_value_counts(declarations: object, word_index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = getattr(declaration, 'descriptor_words_le_u16', ())
        if len(words) <= word_index:
            continue
        key = str(int(words[word_index]))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _array_stride_hint_type_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        stride = int(getattr(declaration, 'array_stride_hint', 0) or 0)
        if stride <= 0:
            continue
        key = f"{getattr(declaration, 'type_name', '')}|{stride}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_count_hint_type_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        if count <= 0:
            continue
        key = f"{getattr(declaration, 'type_name', '')}|{count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_count_hint_member_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        if count <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_word3_relation_counts(declarations: object) -> dict[str, int]:
    counts = {}
    counts.update({'array_rows': 0, 'with_count_hint_rows': 0})
    counts.update({'with_stride_hint_rows': 0, 'word3_zero_rows': 0})
    counts.update({'word3_nonzero_rows': 0, 'word3_equals_count_hint_rows': 0})
    counts.update({'word3_nonzero_equals_count_hint_rows': 0, 'count_hint_positive_word3_equals_count_hint_rows': 0})
    counts.update({'count_hint_positive_word3_not_count_hint_rows': 0, 'word3_equals_stride_hint_rows': 0})
    counts.update({'word3_equals_word2_delta_rows': 0, 'word3_nonzero_without_count_hint_rows': 0})
    counts.update({'word3_nonzero_without_stride_hint_rows': 0})
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        word2 = words[2] if len(words) > 2 else 0
        word3 = words[3] if len(words) > 3 else 0
        count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        stride = int(getattr(declaration, 'array_stride_hint', 0) or 0)
        word2_delta = word2 - 4096 if word2 > 4096 else 0
        counts['array_rows'] += 1
        if count > 0:
            counts['with_count_hint_rows'] += 1
        if stride > 0:
            counts['with_stride_hint_rows'] += 1
        if word3 == 0:
            counts['word3_zero_rows'] += 1
        else:
            counts['word3_nonzero_rows'] += 1
        if count > 0 and word3 == count:
            counts['word3_equals_count_hint_rows'] += 1
            if word3:
                counts['word3_nonzero_equals_count_hint_rows'] += 1
        if count > 0 and word3 == count:
            counts['count_hint_positive_word3_equals_count_hint_rows'] += 1
        if count > 0 and word3 != count:
            counts['count_hint_positive_word3_not_count_hint_rows'] += 1
        if stride > 0 and word3 == stride:
            counts['word3_equals_stride_hint_rows'] += 1
        if word2_delta > 0 and word3 == word2_delta:
            counts['word3_equals_word2_delta_rows'] += 1
        if word3 and count <= 0:
            counts['word3_nonzero_without_count_hint_rows'] += 1
        if word3 and stride <= 0:
            counts['word3_nonzero_without_stride_hint_rows'] += 1
    return counts


def _array_theoretical_payload_shape_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        if count <= 0:
            continue
        stride = int(getattr(declaration, 'array_stride_hint', 0) or 0)
        if stride <= 0:
            words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{stride}|{count}|{stride * count}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _span_overlaps(span: object, start: int, end: int) -> bool:
    return int(getattr(span, 'start', 0)) < end and int(getattr(span, 'end', 0)) > start


def _member_descriptor_overlaps(declaration: object, start: int, end: int) -> bool:
    descriptor_start = int(getattr(declaration, 'descriptor_offset', 0))
    descriptor_end = descriptor_start + int(getattr(declaration, 'descriptor_byte_length', 0))
    return descriptor_start < end and descriptor_end > start


def _array_theoretical_payload_span_fit_metrics(decoded: object) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_roles import _member_descriptor_relation_to_declaration, _string_field_relation_to_declaration, _string_field_role
    metrics = {}
    metrics.update({'member_rows': 0, 'byte_count': 0})
    metrics.update({'non_tiny_member_rows': 0, 'non_tiny_byte_count': 0})
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
        if not getattr(declaration, 'is_array', False):
            continue
        count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        if count <= 0:
            continue
        stride = int(getattr(declaration, 'array_stride_hint', 0) or 0)
        if stride <= 0:
            words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        theoretical_bytes = stride * count
        descriptor_end = int(getattr(declaration, 'descriptor_offset', 0)) + int(getattr(declaration, 'descriptor_byte_length', 0))
        immediate_end = descriptor_end + theoretical_bytes
        metrics['member_rows'] += 1
        metrics['byte_count'] += theoretical_bytes
        if theoretical_bytes > 8:
            metrics['non_tiny_member_rows'] += 1
            metrics['non_tiny_byte_count'] += theoretical_bytes
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


def _array_exact_payload_owner_counts(decoded: object) -> dict[str, int]:
    counts = {'member_rows': 0, 'element_rows': 0}
    preserved_spans = tuple((span for span in getattr(getattr(decoded, 'layout', None), 'spans', ()) if getattr(span, 'kind', '') == 'preserved'))
    for declaration in getattr(decoded, 'member_declarations', ()):
        if not getattr(declaration, 'is_array', False):
            continue
        element_count = int(getattr(declaration, 'array_count_hint', 0) or 0)
        if element_count <= 0:
            continue
        stride = int(getattr(declaration, 'array_stride_hint', 0) or 0)
        if stride <= 0:
            words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
            stride = int(words[2]) - 4096 if len(words) > 2 else 0
        if stride <= 0:
            continue
        descriptor_end = int(getattr(declaration, 'descriptor_offset', 0)) + int(getattr(declaration, 'descriptor_byte_length', 0))
        payload_end = descriptor_end + stride * element_count
        if any((int(getattr(span, 'start', 0)) == descriptor_end and int(getattr(span, 'end', 0)) == payload_end for span in preserved_spans)):
            counts['member_rows'] += 1
            counts['element_rows'] += element_count
    return counts


def _array_word2_delta_member_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        if len(words) <= 2:
            continue
        delta = int(words[2]) - 4096
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{delta}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_word2_delta_word3_member_counts(declarations: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        if len(words) <= 3:
            continue
        delta = int(words[2]) - 4096
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{delta}|{int(words[3])}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_word2_delta_word3_member_offset_candidate_counts(decoded: object) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    counts: dict[str, int] = {}
    declarations = tuple(getattr(decoded, 'member_declarations', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in declarations:
        if not getattr(declaration, 'is_array', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        if len(words) <= 3:
            continue
        has_candidate = any((_candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4) is declaration for candidate in candidates))
        status = 'with_offset_candidate' if has_candidate else 'without_offset_candidate'
        delta = int(words[2]) - 4096
        key = f"{getattr(declaration, 'name', '')}|{getattr(declaration, 'type_name', '')}|{delta}|{int(words[3])}|{status}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _array_nonzero_word3_offset_candidate_status_counts(word2_delta_word3_member_offset_candidate_counts: Mapping[str, object]) -> dict[str, int]:
    counts = {'with_offset_candidate': 0, 'without_offset_candidate': 0}
    for key, value in word2_delta_word3_member_offset_candidate_counts.items():
        parts = str(key).rsplit('|', 4)
        if len(parts) != 5:
            continue
        _member_name, _type_name, _word2_delta, word3, status = parts
        if int(word3) == 0 or status not in counts:
            continue
        counts[status] += int(value or 0)
    return counts


def _array_classification_source_counts(declarations: object) -> dict[str, int]:
    counts = {'type_vector_count': 0, 'type_brackets_count': 0, 'name_list_flag_count': 0}
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        normalized_name = str(getattr(declaration, 'name', '') or '').strip().lower()
        normalized_type = str(getattr(declaration, 'type_name', '') or '').strip().lower()
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        if normalized_type.startswith('vector<'):
            counts['type_vector_count'] += 1
        if normalized_type.endswith('[]'):
            counts['type_brackets_count'] += 1
        if normalized_name.endswith('list') and len(words) >= 3 and int(words[2]) & 4096:
            counts['name_list_flag_count'] += 1
    return counts


def _array_word3_category_counts(declarations: object) -> dict[str, int]:
    counts = {}
    counts.update({'zero_count': 0, 'one_count': 0})
    counts.update({'power_of_two_gt_one_count': 0, 'other_nonzero_count': 0})
    counts.update({'nonzero_with_stride_hint_count': 0, 'nonzero_without_stride_hint_count': 0})
    iterable = declarations if isinstance(declarations, Sequence) else ()
    for declaration in iterable:
        if not getattr(declaration, 'is_array', False):
            continue
        words = tuple((int(value) for value in getattr(declaration, 'descriptor_words_le_u16', ())))
        value = int(words[3]) if len(words) > 3 else 0
        if value == 0:
            counts['zero_count'] += 1
            continue
        if int(getattr(declaration, 'array_stride_hint', 0)) > 0:
            counts['nonzero_with_stride_hint_count'] += 1
        else:
            counts['nonzero_without_stride_hint_count'] += 1
        if value == 1:
            counts['one_count'] += 1
        elif value > 1 and value & value - 1 == 0:
            counts['power_of_two_gt_one_count'] += 1
        else:
            counts['other_nonzero_count'] += 1
    return counts
