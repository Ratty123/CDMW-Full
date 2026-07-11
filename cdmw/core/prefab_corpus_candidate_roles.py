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


def _editable_row_record_end(row: Mapping[str, object]) -> int | None:
    if 'offset' in row:
        return int(row.get('offset') or 0) + 4 + int(row.get('byte_length') or 0)
    if 'value_offset' in row:
        return int(row.get('value_offset') or 0) + int(row.get('byte_length') or 0)
    return None


def _string_field_role(decoded: object, field_index: int) -> str:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    if field_index in _resource_reference_target_field_indexes(decoded):
        return 'resource_reference'
    member_name_indexes = {int(getattr(declaration, 'name_field_index', -2)) for declaration in getattr(decoded, 'member_declarations', ())}
    if field_index in member_name_indexes:
        return 'member_name'
    member_type_indexes = {int(getattr(declaration, 'type_field_index', -2)) for declaration in getattr(decoded, 'member_declarations', ())}
    if field_index in member_type_indexes:
        return 'member_type'
    return 'other_string'


def _string_field_relation_to_declaration(decoded: object, declaration: object, field_index: int) -> str:
    from cdmw.core.prefab_corpus_candidate_offsets_0 import _resource_reference_target_field_indexes
    current_index = int(getattr(declaration, 'member_index', -1))
    if field_index in _resource_reference_target_field_indexes(decoded):
        return 'resource_reference'
    for other in getattr(decoded, 'member_declarations', ()):
        other_index = int(getattr(other, 'member_index', -1))
        if int(getattr(other, 'name_field_index', -2)) == field_index:
            if other is declaration or other_index == current_index:
                return 'same_member_name'
            return 'later_member_name' if other_index > current_index else 'earlier_member_name'
        if int(getattr(other, 'type_field_index', -2)) == field_index:
            if other is declaration or other_index == current_index:
                return 'same_member_type'
            return 'later_member_type' if other_index > current_index else 'earlier_member_type'
    return 'other_string'


def _member_descriptor_relation_to_declaration(declaration: object, other: object) -> str:
    current_index = int(getattr(declaration, 'member_index', -1))
    other_index = int(getattr(other, 'member_index', -1))
    if other is declaration or other_index == current_index:
        return 'same_member_descriptor'
    return 'later_member_descriptor' if other_index > current_index else 'earlier_member_descriptor'


def _candidate_target_role(decoded: object, candidate: object) -> str:
    return _string_field_role(decoded, int(getattr(candidate, 'target_field_index', -1)))


def _offset_candidate_targets_edit_metadata(decoded: object, candidate: object) -> bool:
    return _candidate_target_role(decoded, candidate) in {'member_name', 'member_type', 'other_string'}


def _candidate_owner_kind(decoded: object, candidate: object) -> str:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _candidate_member_descriptor_owner
    owner = _candidate_member_descriptor_owner(decoded, int(candidate.offset), int(candidate.offset) + 4)
    if owner is None:
        return 'outside_member_descriptor'
    return str(getattr(owner, 'descriptor_kind', '') or 'unknown')


def _candidate_target_text(decoded: object, candidate: object) -> str:
    field_index = int(getattr(candidate, 'target_field_index', -1))
    for reference in getattr(decoded, 'references', ()):
        field = getattr(reference, 'field', None)
        if int(getattr(field, 'index', -2)) == field_index:
            return str(getattr(reference, 'text', '') or '')
    for declaration in getattr(decoded, 'member_declarations', ()):
        if int(getattr(declaration, 'name_field_index', -2)) == field_index:
            return str(getattr(declaration, 'name', '') or '')
        if int(getattr(declaration, 'type_field_index', -2)) == field_index:
            return str(getattr(declaration, 'type_name', '') or '')
    return ''


def _candidate_resource_reference_extension(decoded: object, candidate: object) -> str:
    field_index = int(getattr(candidate, 'target_field_index', -1))
    for reference in getattr(decoded, 'references', ()):
        field = getattr(reference, 'field', None)
        if int(getattr(field, 'index', -2)) == field_index:
            extension = str(getattr(reference, 'extension', '') or '').lower()
            if extension:
                return extension
            text = str(getattr(reference, 'text', '') or '').replace('\\', '/')
            name = text.rsplit('/', 1)[-1]
            if '.' in name:
                return f".{name.rsplit('.', 1)[-1].lower()}"
            return ''
    return ''


def _candidate_resource_reference_name(decoded: object, candidate: object) -> str:
    text = _candidate_target_text(decoded, candidate).replace('\\', '/')
    return text.rsplit('/', 1)[-1]


def _top_count_map(counts: Mapping[str, int], limit: int=20) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))[:limit])


def _resize_impact_offset_candidate_target_role_kind_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _resize_impact_offset_candidate_owner_kind_target_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        key = f'{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + count
    return dict(sorted(counts.items()))


def _candidate_identity(candidate: object) -> tuple[int, int, str, int]:
    return (int(getattr(candidate, 'offset', 0)), int(getattr(candidate, 'value', 0)), str(getattr(candidate, 'target_kind', '')), int(getattr(candidate, 'target_field_index', -1)))


def _unique_offset_candidates(candidates: Sequence[object]) -> tuple[object, ...]:
    seen: set[tuple[int, int, str, int]] = set()
    result: list[object] = []
    for candidate in candidates:
        key = _candidate_identity(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return tuple(result)


def _resize_impact_offset_candidate_multiplicities(decoded: object, rows: object) -> tuple[tuple[object, int], ...]:
    if not isinstance(rows, list):
        return ()
    record_ends: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        record_end = _editable_row_record_end(row)
        if record_end is None:
            continue
        record_ends.append(record_end)
    if not record_ends:
        return ()
    record_ends.sort()
    result: list[tuple[object, int]] = []
    for candidate in tuple(getattr(decoded, 'offset_candidates', ())):
        count = bisect_right(record_ends, int(candidate.value))
        if count:
            result.append((candidate, count))
    return tuple(result)


def _resize_impact_offset_candidates(decoded: object, rows: object) -> tuple[object, ...]:
    result: list[object] = []
    for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows):
        result.extend([candidate] * count)
    return tuple(result)


def _resize_impact_resource_reference_candidate_multiplicities(decoded: object, rows: object) -> tuple[tuple[object, int], ...]:
    return tuple(((candidate, count) for candidate, count in _resize_impact_offset_candidate_multiplicities(decoded, rows) if _candidate_target_role(decoded, candidate) == 'resource_reference'))


def _resize_impact_resource_reference_candidates(decoded: object, rows: object) -> tuple[object, ...]:
    result: list[object] = []
    for candidate, count in _resize_impact_resource_reference_candidate_multiplicities(decoded, rows):
        result.extend([candidate] * count)
    return tuple(result)


def _resize_impact_unique_offset_candidate_count(decoded: object, rows: object) -> int:
    return len(_unique_offset_candidates(tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))))


def _resize_impact_unique_offset_candidate_target_role_kind_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    for candidate in _unique_offset_candidates(candidates):
        key = f'{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _resize_impact_unique_offset_candidate_owner_kind_target_counts(decoded: object, rows: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    candidates = tuple((candidate for candidate, _count in _resize_impact_offset_candidate_multiplicities(decoded, rows)))
    for candidate in _unique_offset_candidates(candidates):
        key = f'{_candidate_owner_kind(decoded, candidate)}|{_candidate_target_role(decoded, candidate)}|{candidate.target_kind}'
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
