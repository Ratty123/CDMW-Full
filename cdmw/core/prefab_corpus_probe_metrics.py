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


def _policy_resize_readiness(document: Mapping[str, object]) -> dict[str, object]:
    policy = document.get('policy')
    if not isinstance(policy, Mapping):
        return {}
    readiness = policy.get('resize_readiness')
    if not isinstance(readiness, Mapping):
        return {}
    return {'length_changing_import_ready': bool(readiness.get('length_changing_import_ready') is True), 'editable_row_count': int(readiness.get('editable_row_count') or 0), 'editable_rows_with_resize_impact': int(readiness.get('editable_rows_with_resize_impact') or 0), 'affected_offset_candidate_rows': int(readiness.get('affected_offset_candidate_rows') or 0), 'reason': str(readiness.get('reason') or '')}


def _probe_reason_counts(rows: Sequence[Mapping[str, object]], key: str, status: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(key)
        if not isinstance(probe, Mapping):
            if status != 'failed':
                continue
            reason = 'Missing probe result.'
        else:
            if probe.get('status') != status:
                continue
            reason = str(probe.get('error') or 'No reason recorded.')
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _probe_count_map(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(probe_key)
        if not isinstance(probe, Mapping):
            continue
        values = probe.get(metric_key)
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            counts[str(name)] = counts.get(str(name), 0) + int(value or 0)
    return dict(sorted(counts.items()))


def _probe_top_count_map(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:
    from cdmw.core.prefab_corpus_candidate_roles import _top_count_map
    return _top_count_map(_probe_count_map(rows, probe_key, metric_key))


def _probe_int_sum(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> int:
    return sum((int(row[probe_key].get(metric_key) or 0) for row in rows if isinstance(row.get(probe_key), Mapping)))


def _probe_value_counts(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(probe_key)
        if not isinstance(probe, Mapping):
            continue
        name = str(probe.get(metric_key) or 'none')
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _probe_status_value_counts(rows: Sequence[Mapping[str, object]], probe_key: str, metric_key: str) -> dict[str, int]:

    def _label(value: object) -> str:
        if value is None or value == '':
            return 'none'
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)
    counts: dict[str, int] = {}
    for row in rows:
        probe = row.get(probe_key)
        if not isinstance(probe, Mapping):
            continue
        name = f"{probe.get('status') or 'missing'}|{_label(probe.get(metric_key))}"
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _audit_report_only_array_count_hint_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges
    try:
        before_decoded = decode_prefab(payload)
        selected = next((declaration for declaration in before_decoded.member_declarations if declaration.is_array and int(declaration.array_count_hint) > 0 and (int(declaration.descriptor_byte_length) >= 8)), None)
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'member_name': ''})
            _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
            _prefab_result.update({'old_count_hint': 0, 'new_count_hint': 0})
            _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_count_hint_changed': False})
            _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
            _prefab_result.update({'error': 'No array descriptor with a nonzero count hint.'})
            return _prefab_result
        old_count = int(selected.array_count_hint)
        new_count = old_count + 1 if old_count < 65535 else old_count - 1
        count_offset = int(selected.descriptor_offset) + 6
        if count_offset < 0 or count_offset + 2 > len(payload):
            raise PrefabEditJsonError('Array count-hint descriptor word is outside the payload.')
        patched = bytearray(payload)
        patched[count_offset:count_offset + 2] = new_count.to_bytes(2, 'little')
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(payload, patched_bytes, [(count_offset, count_offset + 2, new_count.to_bytes(2, 'little'))])
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = after_declarations[int(selected.member_index)] if 0 <= int(selected.member_index) < len(after_declarations) else None
        member_identity_preserved = after_selected is not None and str(after_selected.name) == str(selected.name) and (str(after_selected.type_name) == str(selected.type_name)) and (int(after_selected.descriptor_offset) == int(selected.descriptor_offset))
        decoded_count_hint_changed = after_selected is not None and int(after_selected.array_count_hint) == new_count
        ok = changed_only_expected and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and member_identity_preserved and decoded_count_hint_changed
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'member_name': str(selected.name)})
        _prefab_result.update({'member_type': str(selected.type_name), 'descriptor_offset': int(selected.descriptor_offset)})
        _prefab_result.update({'old_count_hint': old_count, 'new_count_hint': new_count})
        _prefab_result.update({'changed_only_expected_bytes': changed_only_expected, 'layout_fully_accounted_after_edit': layout_ok})
        _prefab_result.update({'no_edit_rebuild_after_edit': no_edit_rebuild_ok, 'json_no_edit_roundtrip_after_edit': json_no_edit_ok})
        _prefab_result.update({'json_layout_rebuild_after_edit': json_layout_rebuild_ok, 'decoded_count_hint_changed': decoded_count_hint_changed})
        _prefab_result.update({'member_identity_preserved': member_identity_preserved, 'semantics_proven': False})
        _prefab_result.update({'error': '' if ok else 'Array count-hint descriptor mutation did not survive parser/rebuild checks.'})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'member_name': ''})
        _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
        _prefab_result.update({'old_count_hint': 0, 'new_count_hint': 0})
        _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
        _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
        _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_count_hint_changed': False})
        _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
        _prefab_result.update({'error': str(exc)})
        return _prefab_result


def _audit_report_only_transform_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges
    try:
        before_decoded = decode_prefab(payload)
        selected = next((declaration for declaration in before_decoded.member_declarations if declaration.is_transform and len(declaration.descriptor_words_le_u16) > 3 and (int(declaration.descriptor_words_le_u16[3]) > 0) and (int(declaration.descriptor_byte_length) >= 8)), None)
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'member_name': ''})
            _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
            _prefab_result.update({'old_word3': 0, 'new_word3': 0})
            _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False})
            _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
            _prefab_result.update({'error': 'No transform descriptor with a nonzero word3.'})
            return _prefab_result
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 65535 else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError('Transform descriptor word3 is outside the payload.')
        patched = bytearray(payload)
        patched[word3_offset:word3_offset + 2] = new_word3.to_bytes(2, 'little')
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(payload, patched_bytes, [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, 'little'))])
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = after_declarations[int(selected.member_index)] if 0 <= int(selected.member_index) < len(after_declarations) else None
        member_identity_preserved = after_selected is not None and str(after_selected.name) == str(selected.name) and (str(after_selected.type_name) == str(selected.type_name)) and (int(after_selected.descriptor_offset) == int(selected.descriptor_offset))
        decoded_word3_changed = after_selected is not None and len(after_selected.descriptor_words_le_u16) > 3 and (int(after_selected.descriptor_words_le_u16[3]) == new_word3)
        ok = changed_only_expected and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and member_identity_preserved and decoded_word3_changed
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'member_name': str(selected.name)})
        _prefab_result.update({'member_type': str(selected.type_name), 'descriptor_offset': int(selected.descriptor_offset)})
        _prefab_result.update({'old_word3': old_word3, 'new_word3': new_word3})
        _prefab_result.update({'changed_only_expected_bytes': changed_only_expected, 'layout_fully_accounted_after_edit': layout_ok})
        _prefab_result.update({'no_edit_rebuild_after_edit': no_edit_rebuild_ok, 'json_no_edit_roundtrip_after_edit': json_no_edit_ok})
        _prefab_result.update({'json_layout_rebuild_after_edit': json_layout_rebuild_ok, 'decoded_word3_changed': decoded_word3_changed})
        _prefab_result.update({'member_identity_preserved': member_identity_preserved, 'semantics_proven': False})
        _prefab_result.update({'error': '' if ok else 'Transform descriptor word3 mutation did not survive parser/rebuild checks.'})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'member_name': ''})
        _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
        _prefab_result.update({'old_word3': 0, 'new_word3': 0})
        _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
        _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
        _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False})
        _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
        _prefab_result.update({'error': str(exc)})
        return _prefab_result


def _audit_report_only_reference_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges
    try:
        before_decoded = decode_prefab(payload)
        selected = next((declaration for declaration in before_decoded.member_declarations if declaration.is_reference and (not declaration.is_array) and (not declaration.is_transform) and (len(declaration.descriptor_words_le_u16) > 3) and (int(declaration.descriptor_words_le_u16[3]) > 0) and (int(declaration.descriptor_byte_length) >= 8)), None)
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'member_name': ''})
            _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
            _prefab_result.update({'old_word3': 0, 'new_word3': 0})
            _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False})
            _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
            _prefab_result.update({'error': 'No reference descriptor with a nonzero word3.'})
            return _prefab_result
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 65535 else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError('Reference descriptor word3 is outside the payload.')
        patched = bytearray(payload)
        patched[word3_offset:word3_offset + 2] = new_word3.to_bytes(2, 'little')
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(payload, patched_bytes, [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, 'little'))])
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = after_declarations[int(selected.member_index)] if 0 <= int(selected.member_index) < len(after_declarations) else None
        member_identity_preserved = after_selected is not None and str(after_selected.name) == str(selected.name) and (str(after_selected.type_name) == str(selected.type_name)) and (int(after_selected.descriptor_offset) == int(selected.descriptor_offset))
        decoded_word3_changed = after_selected is not None and len(after_selected.descriptor_words_le_u16) > 3 and (int(after_selected.descriptor_words_le_u16[3]) == new_word3)
        ok = changed_only_expected and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and member_identity_preserved and decoded_word3_changed
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'member_name': str(selected.name)})
        _prefab_result.update({'member_type': str(selected.type_name), 'descriptor_offset': int(selected.descriptor_offset)})
        _prefab_result.update({'old_word3': old_word3, 'new_word3': new_word3})
        _prefab_result.update({'changed_only_expected_bytes': changed_only_expected, 'layout_fully_accounted_after_edit': layout_ok})
        _prefab_result.update({'no_edit_rebuild_after_edit': no_edit_rebuild_ok, 'json_no_edit_roundtrip_after_edit': json_no_edit_ok})
        _prefab_result.update({'json_layout_rebuild_after_edit': json_layout_rebuild_ok, 'decoded_word3_changed': decoded_word3_changed})
        _prefab_result.update({'member_identity_preserved': member_identity_preserved, 'semantics_proven': False})
        _prefab_result.update({'error': '' if ok else 'Reference descriptor word3 mutation did not survive parser/rebuild checks.'})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'member_name': ''})
        _prefab_result.update({'member_type': '', 'descriptor_offset': -1})
        _prefab_result.update({'old_word3': 0, 'new_word3': 0})
        _prefab_result.update({'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
        _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
        _prefab_result.update({'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False})
        _prefab_result.update({'member_identity_preserved': False, 'semantics_proven': False})
        _prefab_result.update({'error': str(exc)})
        return _prefab_result


def _audit_report_only_preserved_unknown_byte_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges
    try:
        before_decoded = decode_prefab(payload)
        selected = next((span for span in before_decoded.layout.spans if span.kind == 'preserved' and int(span.end) > int(span.start) and (int(span.start) >= max(4, int(before_decoded.header.prefix_byte_length)))), None)
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'span_index': -1})
            _prefab_result.update({'span_start': -1, 'span_end': -1})
            _prefab_result.update({'mutation_offset': -1, 'old_byte': 0})
            _prefab_result.update({'new_byte': 0, 'changed_only_expected_bytes': False})
            _prefab_result.update({'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False})
            _prefab_result.update({'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False})
            _prefab_result.update({'decoded_byte_changed': False, 'span_identity_preserved': False})
            _prefab_result.update({'semantics_proven': False, 'error': 'No non-header preserved span available for direct mutation.'})
            return _prefab_result
        mutation_offset = int(selected.start)
        old_byte = int(payload[mutation_offset])
        new_byte = old_byte ^ 255
        patched = bytearray(payload)
        patched[mutation_offset] = new_byte
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(payload, patched_bytes, [(mutation_offset, mutation_offset + 1, bytes([new_byte]))])
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        after_spans = tuple(after_decoded.layout.spans)
        after_selected = after_spans[int(selected.index)] if 0 <= int(selected.index) < len(after_spans) else None
        span_identity_preserved = after_selected is not None and after_selected.kind == selected.kind and (int(after_selected.start) == int(selected.start)) and (int(after_selected.end) == int(selected.end))
        decoded_byte_changed = patched_bytes[mutation_offset] == new_byte
        ok = changed_only_expected and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and span_identity_preserved and decoded_byte_changed
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'span_index': int(selected.index)})
        _prefab_result.update({'span_start': int(selected.start), 'span_end': int(selected.end)})
        _prefab_result.update({'mutation_offset': mutation_offset, 'old_byte': old_byte})
        _prefab_result.update({'new_byte': new_byte, 'changed_only_expected_bytes': changed_only_expected})
        _prefab_result.update({'layout_fully_accounted_after_edit': layout_ok, 'no_edit_rebuild_after_edit': no_edit_rebuild_ok})
        _prefab_result.update({'json_no_edit_roundtrip_after_edit': json_no_edit_ok, 'json_layout_rebuild_after_edit': json_layout_rebuild_ok})
        _prefab_result.update({'decoded_byte_changed': decoded_byte_changed, 'span_identity_preserved': span_identity_preserved})
        _prefab_result.update({'semantics_proven': False, 'error': '' if ok else 'Preserved unknown byte mutation did not survive parser/rebuild checks.'})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError, IndexError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'span_index': -1})
        _prefab_result.update({'span_start': -1, 'span_end': -1})
        _prefab_result.update({'mutation_offset': -1, 'old_byte': 0})
        _prefab_result.update({'new_byte': 0, 'changed_only_expected_bytes': False})
        _prefab_result.update({'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False})
        _prefab_result.update({'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False})
        _prefab_result.update({'decoded_byte_changed': False, 'span_identity_preserved': False})
        _prefab_result.update({'semantics_proven': False, 'error': str(exc)})
        return _prefab_result


def _audit_report_only_descriptor_word3_mutation_probe(payload: bytes, virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges
    try:
        before_decoded = decode_prefab(payload)
        selected = next((declaration for declaration in before_decoded.member_declarations if not declaration.is_array and (not declaration.is_reference) and (not declaration.is_transform) and (len(declaration.descriptor_words_le_u16) > 3) and (int(declaration.descriptor_words_le_u16[3]) > 0) and (int(declaration.descriptor_byte_length) >= 8)), None)
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'member_name': ''})
            _prefab_result.update({'member_type': '', 'descriptor_kind': ''})
            _prefab_result.update({'descriptor_offset': -1, 'old_word3': 0})
            _prefab_result.update({'new_word3': 0, 'changed_only_expected_bytes': False})
            _prefab_result.update({'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False})
            _prefab_result.update({'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False})
            _prefab_result.update({'decoded_word3_changed': False, 'member_identity_preserved': False})
            _prefab_result.update({'semantics_proven': False, 'error': 'No non-array/non-reference/non-transform descriptor with a nonzero word3.'})
            return _prefab_result
        old_word3 = int(selected.descriptor_words_le_u16[3])
        new_word3 = old_word3 + 1 if old_word3 < 65535 else old_word3 - 1
        word3_offset = int(selected.descriptor_offset) + 6
        if word3_offset < 0 or word3_offset + 2 > len(payload):
            raise PrefabEditJsonError('Descriptor word3 is outside the payload.')
        patched = bytearray(payload)
        patched[word3_offset:word3_offset + 2] = new_word3.to_bytes(2, 'little')
        patched_bytes = bytes(patched)
        changed_only_expected = _changed_only_expected_ranges(payload, patched_bytes, [(word3_offset, word3_offset + 2, new_word3.to_bytes(2, 'little'))])
        after_decoded = decode_prefab(patched_bytes)
        layout_ok = after_decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched_bytes) == patched_bytes
        patched_document = build_prefab_edit_document(patched_bytes, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched_bytes, patched_document, virtual_path=virtual_path) == patched_bytes
        after_declarations = tuple(after_decoded.member_declarations)
        after_selected = after_declarations[int(selected.member_index)] if 0 <= int(selected.member_index) < len(after_declarations) else None
        member_identity_preserved = after_selected is not None and str(after_selected.name) == str(selected.name) and (str(after_selected.type_name) == str(selected.type_name)) and (int(after_selected.descriptor_offset) == int(selected.descriptor_offset))
        decoded_word3_changed = after_selected is not None and len(after_selected.descriptor_words_le_u16) > 3 and (int(after_selected.descriptor_words_le_u16[3]) == new_word3)
        ok = changed_only_expected and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and member_identity_preserved and decoded_word3_changed
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'member_name': str(selected.name)})
        _prefab_result.update({'member_type': str(selected.type_name), 'descriptor_kind': str(selected.descriptor_kind)})
        _prefab_result.update({'descriptor_offset': int(selected.descriptor_offset), 'old_word3': old_word3})
        _prefab_result.update({'new_word3': new_word3, 'changed_only_expected_bytes': changed_only_expected})
        _prefab_result.update({'layout_fully_accounted_after_edit': layout_ok, 'no_edit_rebuild_after_edit': no_edit_rebuild_ok})
        _prefab_result.update({'json_no_edit_roundtrip_after_edit': json_no_edit_ok, 'json_layout_rebuild_after_edit': json_layout_rebuild_ok})
        _prefab_result.update({'decoded_word3_changed': decoded_word3_changed, 'member_identity_preserved': member_identity_preserved})
        _prefab_result.update({'semantics_proven': False, 'error': '' if ok else 'Descriptor word3 mutation did not survive parser/rebuild checks.'})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'member_name': ''})
        _prefab_result.update({'member_type': '', 'descriptor_kind': ''})
        _prefab_result.update({'descriptor_offset': -1, 'old_word3': 0})
        _prefab_result.update({'new_word3': 0, 'changed_only_expected_bytes': False})
        _prefab_result.update({'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False})
        _prefab_result.update({'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False})
        _prefab_result.update({'decoded_word3_changed': False, 'member_identity_preserved': False})
        _prefab_result.update({'semantics_proven': False, 'error': str(exc)})
        return _prefab_result


def _skipped_probe_results(reason: str) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    return ({'status': 'skipped', 'edited_reference_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': reason}, {'status': 'skipped', 'edited_field_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': reason}, {'status': 'skipped', 'edited_reference_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': False, 'replacement_reference_found': False, 'error': reason}, {'status': 'skipped', 'edited_field_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_low_level_profile_patch': False, 'replacement_field_found': False, 'error': reason})
