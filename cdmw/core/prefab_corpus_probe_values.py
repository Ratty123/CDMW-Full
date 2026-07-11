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


def _same_length_probe_value(value: str) -> str:
    text = str(value or '').replace('\\', '/')
    if not text:
        return ''
    last_slash = max(text.rfind('/'), text.rfind('\\'))
    last_dot = text.rfind('.')
    end = last_dot if last_dot > last_slash else len(text)
    chars = list(text)
    for index in range(end - 1, -1, -1):
        char = chars[index]
        if char in {'/', '\\', '.'}:
            continue
        if 'a' <= char <= 'z':
            chars[index] = 'b' if char != 'b' else 'c'
            return ''.join(chars)
        if 'A' <= char <= 'Z':
            chars[index] = 'B' if char != 'B' else 'C'
            return ''.join(chars)
        if '0' <= char <= '9':
            chars[index] = '1' if char != '1' else '2'
            return ''.join(chars)
    return ''


def _longer_probe_value(value: str) -> str:
    text = str(value or '').replace('\\', '/')
    if '/' not in text:
        return ''
    last_slash = text.rfind('/')
    last_dot = text.rfind('.')
    socket_suffix = '.sockets.xml'
    if text.casefold().endswith(socket_suffix):
        candidate = f'{text[:-len(socket_suffix)]}_cdmwprobe{text[-len(socket_suffix):]}'
        return candidate if len(candidate.encode('utf-8')) > len(text.encode('utf-8')) else ''
    if last_dot > last_slash:
        candidate = f'{text[:last_dot]}_cdmwprobe{text[last_dot:]}'
    else:
        candidate = f'{text}_cdmwprobe'
    return candidate if len(candidate.encode('utf-8')) > len(text.encode('utf-8')) else ''


def _same_length_placement_probe_value(field_name: str, value: str) -> str:
    text = str(value or '').strip()
    lowered = text.casefold()
    if field_name in {'_attachedSocketName', '_pivotSocketName'}:
        socket_index = lowered.find('socket')
        if socket_index < 1:
            return ''
        candidate = _same_length_probe_value(text[:socket_index]) + text[socket_index:]
        return candidate if candidate != text and 'socket' in candidate.casefold() else ''
    if field_name == '_partName' and text.startswith('CD_'):
        candidate = 'CD_' + _same_length_probe_value(text[3:])
        return candidate if candidate != text and candidate.startswith('CD_') else ''
    return ''


def _longer_placement_probe_value(field_name: str, value: str) -> str:
    text = str(value or '').strip()
    if field_name in {'_attachedSocketName', '_pivotSocketName'}:
        socket_index = text.casefold().find('socket')
        if socket_index < 1:
            return ''
        return f'{text[:socket_index]}CDMWProbe_{text[socket_index:]}'
    if field_name == '_partName' and text.startswith('CD_'):
        return f'{text}_CDMWPROBE'
    return ''


def _changed_only_expected_ranges(before: bytes, after: bytes, ranges: Sequence[tuple[int, int, bytes]]) -> bool:
    if len(before) != len(after):
        return False
    cursor = 0
    for start, end, expected in sorted(ranges, key=lambda item: item[0]):
        if start < cursor or end < start or end > len(before):
            return False
        if before[cursor:start] != after[cursor:start]:
            return False
        if after[start:end] != expected:
            return False
        cursor = end
    return before[cursor:] == after[cursor:]


def _expected_length_changed_bytes(payload: bytes, record_replacements: Sequence[tuple[int, int, bytes]], offset_value_replacements: Sequence[tuple[int, int]]=()) -> bytes | None:
    records = sorted(record_replacements, key=lambda item: item[0])
    patches = sorted(offset_value_replacements, key=lambda item: item[0])
    cursor = 0
    for start, end, replacement in records:
        if start < cursor or end < start or end > len(payload) or (not isinstance(replacement, bytes)):
            return None
        cursor = end
    for offset, value in patches:
        if offset < 0 or offset + 4 > len(payload) or value < 0:
            return None
    for record_start, record_end, _replacement in records:
        if any((record_start <= offset < record_end for offset, _value in patches)):
            return None

    def copy_patched(start: int, end: int) -> bytes:
        segment = bytearray(payload[start:end])
        for offset, value in patches:
            if start <= offset and offset + 4 <= end:
                segment[offset - start:offset - start + 4] = int(value).to_bytes(4, 'little')
        for offset, value in patches:
            if start <= offset and offset + 4 <= end:
                actual = int.from_bytes(segment[offset - start:offset - start + 4], 'little')
                if actual != int(value):
                    return b''
        return bytes(segment)
    rebuilt = bytearray()
    cursor = 0
    for start, end, replacement in records:
        rebuilt.extend(copy_patched(cursor, start))
        rebuilt.extend(replacement)
        cursor = end
    rebuilt.extend(copy_patched(cursor, len(payload)))
    return bytes(rebuilt)


def _effective_offset_value_replacements_after_resize(before: object, edit_deltas: Sequence[tuple[int, int]], after_payload: bytes) -> tuple[tuple[int, int], ...]:
    deltas = [(int(edit_end), int(delta)) for edit_end, delta in edit_deltas if int(delta)]

    def shift(position: int) -> int:
        return int(position) + sum((delta for edit_end, delta in deltas if int(position) >= edit_end))
    replacements: list[tuple[int, int]] = []
    for candidate in getattr(before, 'offset_candidates', ()):
        expected_offset = shift(int(candidate.offset))
        if 0 <= expected_offset and expected_offset + 4 <= len(after_payload):
            raw_value = int.from_bytes(after_payload[expected_offset:expected_offset + 4], 'little')
            if raw_value == int(candidate.value):
                continue
        replacements.append((int(candidate.offset), shift(int(candidate.value))))
    return tuple(replacements)


def _resize_impact_offset_candidate_count(rows: object) -> int:
    if not isinstance(rows, list):
        return 0
    total = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        impact = row.get('resize_impact')
        if not isinstance(impact, Mapping):
            continue
        total += int(impact.get('affected_offset_candidate_count') or 0)
    return total


def _length_change_plan_counts(rows: object) -> dict[str, int]:
    counts = {'tail_only_candidate_count': 0, 'downstream_rebuild_row_count': 0, 'offset_rebuild_row_count': 0}
    if not isinstance(rows, list):
        return counts
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        impact = row.get('resize_impact')
        if not isinstance(impact, Mapping):
            continue
        plan = impact.get('length_change_plan')
        if not isinstance(plan, Mapping):
            continue
        affected_offsets = int(plan.get('affected_offset_candidate_count') or 0)
        downstream_bytes = int(plan.get('downstream_byte_count') or 0)
        if affected_offsets:
            counts['offset_rebuild_row_count'] += 1
        elif plan.get('tail_only') is True:
            counts['tail_only_candidate_count'] += 1
        if downstream_bytes:
            counts['downstream_rebuild_row_count'] += 1
    return counts
