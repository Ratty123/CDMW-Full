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


def _reference_descriptor_tail_record_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {}
    counts.update({'exact_tail_members': 0, 'record_count_total': 0})
    counts.update({'unique_record_count_total': 0, 'duplicate_record_count_total': 0})
    counts.update({'offset_candidate_record_count_total': 0, 'offset_candidate_free_record_count_total': 0})
    counts.update({'offset_candidate_multi_kind_record_count_total': 0, 'max_offset_candidates_per_record': 0})
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in getattr(decoded, 'member_declarations', ()):
        if str(getattr(declaration, 'descriptor_kind', '') or '') != 'reference':
            continue
        descriptor_offset = int(getattr(declaration, 'descriptor_offset', 0))
        descriptor_length = int(getattr(declaration, 'descriptor_byte_length', 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, 'descriptor_words_le_u16', ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 4095
        if tail_bytes <= 0 or stride <= 0 or tail_bytes % stride != 0:
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        if tail_start < 0 or tail_end > len(payload):
            continue
        record_count = tail_bytes // stride
        if record_count <= 0:
            continue
        records = [payload[tail_start + record_index * stride:tail_start + (record_index + 1) * stride] for record_index in range(record_count)]
        record_candidate_counts: dict[int, int] = {}
        record_candidate_kinds: dict[int, set[str]] = {}
        for candidate in candidates:
            candidate_offset = int(getattr(candidate, 'offset', -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            record_index = (candidate_offset - tail_start) // stride
            record_candidate_counts[record_index] = record_candidate_counts.get(record_index, 0) + 1
            record_candidate_kinds.setdefault(record_index, set()).add(str(getattr(candidate, 'target_kind', '') or 'unknown'))
        candidate_record_count = len(record_candidate_counts)
        unique_record_count = len(set(records))
        counts['exact_tail_members'] += 1
        counts['record_count_total'] += record_count
        counts['unique_record_count_total'] += unique_record_count
        counts['duplicate_record_count_total'] += record_count - unique_record_count
        counts['offset_candidate_record_count_total'] += candidate_record_count
        counts['offset_candidate_free_record_count_total'] += record_count - candidate_record_count
        counts['offset_candidate_multi_kind_record_count_total'] += sum((1 for kinds in record_candidate_kinds.values() if len(kinds) > 1))
        counts['max_offset_candidates_per_record'] = max(counts['max_offset_candidates_per_record'], max(record_candidate_counts.values(), default=0))
    return counts


def _reference_descriptor_tail_numeric_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {}
    counts.update({'exact_tail_members': 0, 'record_count_total': 0})
    counts.update({'u32_columns_total': 0, 'finite_float_columns': 0})
    counts.update({'worldish_float_columns': 0, 'unitish_float_columns': 0})
    counts.update({'zero_heavy_u32_columns': 0, 'one_float_heavy_columns': 0})
    counts.update({'tiny_or_zero_heavy_float_columns': 0, 'huge_float_columns': 0})
    for declaration in getattr(decoded, 'member_declarations', ()):
        if str(getattr(declaration, 'descriptor_kind', '') or '') != 'reference':
            continue
        descriptor_offset = int(getattr(declaration, 'descriptor_offset', 0))
        descriptor_length = int(getattr(declaration, 'descriptor_byte_length', 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, 'descriptor_words_le_u16', ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 4095
        if tail_bytes <= 0 or stride <= 0 or stride % 4 != 0 or (tail_bytes % stride != 0):
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        if tail_start < 0 or tail_end > len(payload):
            continue
        record_count = tail_bytes // stride
        if record_count <= 0:
            continue
        counts['exact_tail_members'] += 1
        counts['record_count_total'] += record_count
        for word_index in range(stride // 4):
            counts['u32_columns_total'] += 1
            zero_count = 0
            finite_count = 0
            worldish_count = 0
            unitish_count = 0
            one_float_count = 0
            word_offset = tail_start + word_index * 4
            for record_index in range(record_count):
                offset = word_offset + record_index * stride
                raw = payload[offset:offset + 4]
                value = int.from_bytes(raw, 'little')
                if value == 0:
                    zero_count += 1
                float_value = struct.unpack('<f', raw)[0]
                if math.isfinite(float_value):
                    finite_count += 1
                    if -100000.0 <= float_value <= 100000.0:
                        worldish_count += 1
                    if -1.01 <= float_value <= 1.01:
                        unitish_count += 1
                    if float_value == 1.0:
                        one_float_count += 1
            if finite_count * 10 >= record_count * 9:
                counts['finite_float_columns'] += 1
            if worldish_count * 4 >= record_count * 3:
                counts['worldish_float_columns'] += 1
            if unitish_count * 2 >= record_count:
                counts['unitish_float_columns'] += 1
            if zero_count * 2 > record_count:
                counts['zero_heavy_u32_columns'] += 1
            if one_float_count * 2 > record_count:
                counts['one_float_heavy_columns'] += 1
            tiny_nonzero_count = 0
            huge_count = 0
            word_offset = tail_start + word_index * 4
            for record_index in range(record_count):
                offset = word_offset + record_index * stride
                float_value = struct.unpack('<f', payload[offset:offset + 4])[0]
                if not math.isfinite(float_value):
                    continue
                if 0 < abs(float_value) < 1e-06:
                    tiny_nonzero_count += 1
                if abs(float_value) > 100000.0:
                    huge_count += 1
            if (zero_count + tiny_nonzero_count) * 2 >= record_count:
                counts['tiny_or_zero_heavy_float_columns'] += 1
            if huge_count * 10 >= record_count:
                counts['huge_float_columns'] += 1
    return counts


def _reference_descriptor_tail_column_profile_counts(decoded: object, payload: bytes) -> dict[str, int]:
    counts = {}
    counts.update({'exact_tail_members': 0, 'record_count_total': 0})
    counts.update({'u32_columns_total': 0, 'constant_u32_columns': 0})
    counts.update({'variable_u32_columns': 0, 'all_zero_u32_columns': 0})
    counts.update({'mostly_zero_u32_columns': 0, 'offset_candidate_u32_columns': 0})
    counts.update({'offset_candidate_free_u32_columns': 0, 'unique_u32_value_total': 0})
    counts.update({'max_unique_u32_values_per_column': 0, 'unaligned_offset_candidate_rows': 0})
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    for declaration in getattr(decoded, 'member_declarations', ()):
        if str(getattr(declaration, 'descriptor_kind', '') or '') != 'reference':
            continue
        descriptor_offset = int(getattr(declaration, 'descriptor_offset', 0))
        descriptor_length = int(getattr(declaration, 'descriptor_byte_length', 0))
        tail_bytes = max(0, descriptor_length - 8)
        words = tuple(getattr(declaration, 'descriptor_words_le_u16', ()))
        word2 = int(words[2]) if len(words) > 2 else 0
        stride = word2 & 4095
        if tail_bytes <= 0 or stride <= 0 or stride % 4 != 0 or (tail_bytes % stride != 0):
            continue
        tail_start = descriptor_offset + 8
        tail_end = descriptor_offset + descriptor_length
        if tail_start < 0 or tail_end > len(payload):
            continue
        record_count = tail_bytes // stride
        if record_count <= 0:
            continue
        candidate_columns: set[int] = set()
        for candidate in candidates:
            candidate_offset = int(getattr(candidate, 'offset', -1))
            if not (tail_start <= candidate_offset and candidate_offset + 4 <= tail_end):
                continue
            relative = candidate_offset - tail_start
            if relative % 4:
                counts['unaligned_offset_candidate_rows'] += 1
                continue
            candidate_columns.add(relative % stride // 4)
        counts['exact_tail_members'] += 1
        counts['record_count_total'] += record_count
        for word_index in range(stride // 4):
            values = {int.from_bytes(payload[tail_start + record_index * stride + word_index * 4:tail_start + record_index * stride + word_index * 4 + 4], 'little') for record_index in range(record_count)}
            unique_count = len(values)
            counts['u32_columns_total'] += 1
            counts['unique_u32_value_total'] += unique_count
            counts['max_unique_u32_values_per_column'] = max(counts['max_unique_u32_values_per_column'], unique_count)
            if unique_count == 1:
                counts['constant_u32_columns'] += 1
            else:
                counts['variable_u32_columns'] += 1
            zero_count = sum((1 for record_index in range(record_count) if int.from_bytes(payload[tail_start + record_index * stride + word_index * 4:tail_start + record_index * stride + word_index * 4 + 4], 'little') == 0))
            if zero_count == record_count:
                counts['all_zero_u32_columns'] += 1
            if zero_count * 2 >= record_count:
                counts['mostly_zero_u32_columns'] += 1
            if word_index in candidate_columns:
                counts['offset_candidate_u32_columns'] += 1
            else:
                counts['offset_candidate_free_u32_columns'] += 1
    return counts


def _preserved_span_metrics(decoded: object) -> dict[str, int]:
    spans = tuple(getattr(getattr(decoded, 'layout', None), 'spans', ()))
    candidates = tuple(getattr(decoded, 'offset_candidates', ()))
    preserved_spans = [span for span in spans if getattr(span, 'kind', '') == 'preserved']
    descriptor_ranges = []
    descriptor_header_ranges = []
    descriptor_tail_ranges = []
    for declaration in getattr(decoded, 'member_declarations', ()):
        descriptor_start = int(getattr(declaration, 'descriptor_offset', 0))
        descriptor_length = int(getattr(declaration, 'descriptor_byte_length', 0))
        if descriptor_length <= 0:
            continue
        descriptor_end = descriptor_start + descriptor_length
        descriptor_header_end = descriptor_start + min(8, descriptor_length)
        descriptor_ranges.append((descriptor_start, descriptor_end))
        descriptor_header_ranges.append((descriptor_start, descriptor_header_end))
        if descriptor_header_end < descriptor_end:
            descriptor_tail_ranges.append((descriptor_header_end, descriptor_end))
    spans_with_candidates = 0
    spans_with_descriptors = 0
    spans_with_descriptor_headers = 0
    spans_with_descriptor_tails = 0
    descriptor_preserved_bytes = 0
    descriptor_header_preserved_bytes = 0
    descriptor_tail_preserved_bytes = 0
    for span in preserved_spans:
        start = int(getattr(span, 'start', 0))
        end = int(getattr(span, 'end', 0))
        if any((start <= int(candidate.offset) and int(candidate.offset) + 4 <= end for candidate in candidates)):
            spans_with_candidates += 1
        descriptor_bytes = sum((max(0, min(end, descriptor_end) - max(start, descriptor_start)) for descriptor_start, descriptor_end in descriptor_ranges))
        descriptor_header_bytes = sum((max(0, min(end, header_end) - max(start, header_start)) for header_start, header_end in descriptor_header_ranges))
        descriptor_tail_bytes = sum((max(0, min(end, tail_end) - max(start, tail_start)) for tail_start, tail_end in descriptor_tail_ranges))
        if descriptor_bytes:
            spans_with_descriptors += 1
            descriptor_preserved_bytes += descriptor_bytes
        if descriptor_header_bytes:
            spans_with_descriptor_headers += 1
            descriptor_header_preserved_bytes += descriptor_header_bytes
        if descriptor_tail_bytes:
            spans_with_descriptor_tails += 1
            descriptor_tail_preserved_bytes += descriptor_tail_bytes
    preserved_byte_count = sum((int(span.end) - int(span.start) for span in preserved_spans))
    _prefab_result = {}
    _prefab_result.update({'largest_preserved_span_byte_count': max((int(span.end) - int(span.start) for span in preserved_spans), default=0), 'preserved_span_with_offset_candidate_count': spans_with_candidates})
    _prefab_result.update({'preserved_span_without_offset_candidate_count': len(preserved_spans) - spans_with_candidates, 'member_descriptor_preserved_byte_count': descriptor_preserved_bytes})
    _prefab_result.update({'member_descriptor_header_preserved_byte_count': descriptor_header_preserved_bytes, 'member_descriptor_tail_preserved_byte_count': descriptor_tail_preserved_bytes})
    _prefab_result.update({'preserved_unknown_byte_count_excluding_member_descriptors': max(0, preserved_byte_count - descriptor_preserved_bytes), 'preserved_unknown_byte_count_excluding_member_descriptor_headers': max(0, preserved_byte_count - descriptor_header_preserved_bytes)})
    _prefab_result.update({'preserved_span_with_member_descriptor_count': spans_with_descriptors, 'preserved_span_without_member_descriptor_count': len(preserved_spans) - spans_with_descriptors})
    _prefab_result.update({'preserved_span_with_member_descriptor_header_count': spans_with_descriptor_headers, 'preserved_span_with_member_descriptor_tail_count': spans_with_descriptor_tails})
    return _prefab_result
