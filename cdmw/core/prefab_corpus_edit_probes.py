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


def _audit_same_length_resource_edit_probe(payload: bytes, document: Mapping[str, object], virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges, _same_length_probe_value
    try:
        editable = document.get('editable')
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError('Prefab edit document has no editable object.')
        rows = editable.get('resource_references')
        if not isinstance(rows, list):
            raise PrefabEditJsonError('Prefab edit document has no resource reference rows.')
        selected_original = ''
        selected_replacement = ''
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            original = str(row.get('text') or '')
            replacement = _same_length_probe_value(original)
            if replacement and replacement != original and (len(replacement.encode('utf-8')) == int(row.get('byte_length') or -1)):
                selected_original = original
                selected_replacement = replacement
                break
        if not selected_original:
            return {'status': 'skipped', 'edited_reference_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': 'No editable resource reference with a safe same-length probe candidate.'}
        probe_document = deepcopy(document)
        probe_rows = probe_document['editable']['resource_references']
        expected_ranges: list[tuple[int, int, bytes]] = []
        replacement_bytes = selected_replacement.encode('utf-8')
        edited_count = 0
        for row in probe_rows:
            if row['text'] != selected_original:
                continue
            row['value'] = selected_replacement
            start = int(row['offset']) + 4
            end = start + int(row['byte_length'])
            expected_ranges.append((start, end, replacement_bytes))
            edited_count += 1
        patched = apply_prefab_edit_document(payload, probe_document, virtual_path=virtual_path)
        changed_only_expected = _changed_only_expected_ranges(payload, patched, expected_ranges)
        layout_ok = decode_prefab(patched).layout.fully_accounted
        ok = patched != payload and len(patched) == len(payload) and changed_only_expected and layout_ok
        return {'status': 'passed' if ok else 'failed', 'edited_reference_count': edited_count, 'changed_only_expected_bytes': changed_only_expected, 'layout_fully_accounted_after_edit': layout_ok, 'error': '' if ok else 'Same-length resource edit probe changed unexpected bytes or broke layout accounting.'}
    except (PrefabEditJsonError, ValueError, TypeError, KeyError) as exc:
        return {'status': 'failed', 'edited_reference_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}


def _audit_same_length_placement_edit_probe(payload: bytes, document: Mapping[str, object], virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_probe_values import _changed_only_expected_ranges, _same_length_placement_probe_value
    try:
        editable = document.get('editable')
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError('Prefab edit document has no editable object.')
        rows = editable.get('placement_fields')
        if not isinstance(rows, list):
            raise PrefabEditJsonError('Prefab edit document has no placement field rows.')
        field_counts: dict[str, int] = {}
        for row in rows:
            if isinstance(row, Mapping):
                field_name = str(row.get('field_name') or '')
                field_counts[field_name] = field_counts.get(field_name, 0) + 1
        selected_row_index = -1
        selected_replacement = ''
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            field_name = str(row.get('field_name') or '')
            if field_counts.get(field_name, 0) != 1:
                continue
            original = str(row.get('text') or '')
            replacement = _same_length_placement_probe_value(field_name, original)
            if replacement and len(replacement.encode('ascii')) == int(row.get('byte_length') or -1):
                selected_row_index = index
                selected_replacement = replacement
                break
        if selected_row_index < 0:
            return {'status': 'skipped', 'edited_field_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': 'No editable placement field with a safe same-length probe candidate.'}
        probe_document = deepcopy(document)
        row = probe_document['editable']['placement_fields'][selected_row_index]
        row['value'] = selected_replacement
        replacement_bytes = selected_replacement.encode('ascii')
        start = int(row['value_offset'])
        end = start + int(row['byte_length'])
        patched = apply_prefab_edit_document(payload, probe_document, virtual_path=virtual_path)
        changed_only_expected = _changed_only_expected_ranges(payload, patched, [(start, end, replacement_bytes)])
        layout_ok = decode_prefab(patched).layout.fully_accounted
        ok = patched != payload and len(patched) == len(payload) and changed_only_expected and layout_ok
        return {'status': 'passed' if ok else 'failed', 'edited_field_count': 1, 'changed_only_expected_bytes': changed_only_expected, 'layout_fully_accounted_after_edit': layout_ok, 'error': '' if ok else 'Same-length placement edit probe changed unexpected bytes or broke layout accounting.'}
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        return {'status': 'failed', 'edited_field_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}


def _audit_experimental_length_change_placement_rebuild_probe(payload: bytes, document: Mapping[str, object], virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _offset_candidate_remap_metrics_after_resize
    from cdmw.core.prefab_corpus_probe_values import _effective_offset_value_replacements_after_resize, _expected_length_changed_bytes, _longer_placement_probe_value
    from cdmw.core.prefab_corpus_resize_impact_0 import _selected_resize_offset_candidate_metrics
    selected_resize_metrics = _selected_resize_offset_candidate_metrics(None, ())
    try:
        editable = document.get('editable')
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError('Prefab edit document has no editable object.')
        rows = editable.get('placement_fields')
        if not isinstance(rows, list):
            raise PrefabEditJsonError('Prefab edit document has no placement field rows.')
        selected: Mapping[str, object] | None = None
        replacement = ''
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            candidate = _longer_placement_probe_value(str(row.get('field_name') or ''), str(row.get('text') or ''))
            if candidate and len(candidate.encode('ascii')) > int(row.get('byte_length') or 0):
                selected = row
                replacement = candidate
                break
        if selected is None:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'edited_field_count': 0})
            _prefab_result.update({'byte_delta': 0, 'offset_candidate_count_after_edit': 0})
            _prefab_result.update({'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False})
            _prefab_result.update({'offset_candidate_report_only_effective_remap_status': 'none', 'resized_rebuild_changed_only_expected_bytes': False})
            _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'used_low_level_profile_patch': False})
            _prefab_result.update({'replacement_field_found': False, 'error': NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON})
            _prefab_result.update({**selected_resize_metrics})
            return _prefab_result
        field_name = str(selected.get('field_name') or '')
        original_length = int(selected.get('byte_length') or 0)
        replacement_length = len(replacement.encode('ascii'))
        delta = replacement_length - original_length
        if delta <= 0:
            raise PrefabEditJsonError('Placement length-changing probe did not increase byte length.')
        patch_kwargs = {'attached_socket_name': replacement if field_name == '_attachedSocketName' else '', 'pivot_socket_name': replacement if field_name == '_pivotSocketName' else '', 'part_name': replacement if field_name == '_partName' else '', 'allow_length_changes': True}
        before_decoded = decode_prefab(payload)
        selected_resize_metrics = _selected_resize_offset_candidate_metrics(before_decoded, [(int(selected.get('value_offset') or 0) + original_length, delta)], payload)
        patched = build_prefab_attachment_profile_patch(payload, **patch_kwargs).data
        expected_patched = _expected_length_changed_bytes(payload, [(int(selected.get('length_offset') or 0), int(selected.get('value_offset') or 0) + original_length, replacement_length.to_bytes(4, 'little') + replacement.encode('ascii'))])
        changed_only_expected = expected_patched == patched
        decoded = decode_prefab(patched)
        layout_ok = decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched) == patched
        patched_document = build_prefab_edit_document(patched, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        byte_delta = len(patched) - len(payload)
        edit_end = int(selected.get('value_offset') or 0) + original_length
        offset_remap_metrics = _offset_candidate_remap_metrics_after_resize(before_decoded, decoded, [(edit_end, delta)], patched)
        effective_expected_patched = _expected_length_changed_bytes(payload, [(int(selected.get('length_offset') or 0), int(selected.get('value_offset') or 0) + original_length, replacement_length.to_bytes(4, 'little') + replacement.encode('ascii'))], _effective_offset_value_replacements_after_resize(before_decoded, [(edit_end, delta)], patched))
        changed_only_effective_expected = effective_expected_patched == patched
        offset_candidates_remapped = offset_remap_metrics['remapped'] is True
        offset_candidates_effectively_remapped = offset_remap_metrics['effectively_remapped'] is True
        patched_fields = {field.field_name: field.value for field in inspect_prefab_attachment_profile_fields(patched)}
        replacement_found = patched_fields.get(field_name) == replacement
        ok = patched != payload and byte_delta == delta and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and replacement_found and offset_candidates_remapped and changed_only_expected
        error = ''
        if not ok:
            error = 'Experimental placement length-changing rebuild probe failed offset-candidate remap checks.' if not offset_candidates_remapped else 'Experimental placement length-changing rebuild probe failed parser/layout/JSON checks.'
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'edited_field_count': 1})
        _prefab_result.update({'byte_delta': byte_delta, 'offset_candidate_count_after_edit': len(decoded.offset_candidates)})
        _prefab_result.update({'offset_candidates_remapped_after_edit': offset_candidates_remapped, 'offset_candidates_effectively_remapped_after_edit': offset_candidates_effectively_remapped})
        _prefab_result.update({'offset_candidate_report_only_effective_remap_status': offset_remap_metrics['report_only_effective_remap_status'], 'resized_rebuild_changed_only_expected_bytes': changed_only_expected})
        _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': changed_only_effective_expected, 'offset_candidate_remap_missing_count': offset_remap_metrics['missing_count']})
        _prefab_result.update({'offset_candidate_remap_missing_target_kind_counts': offset_remap_metrics['missing_target_kind_counts'], 'offset_candidate_remap_missing_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_metadata_target_count': offset_remap_metrics['missing_metadata_target_count'], 'offset_candidate_remap_missing_non_metadata_target_count': offset_remap_metrics['missing_non_metadata_target_count']})
        _prefab_result.update({'offset_candidate_remap_missing_metadata_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_metadata_owner_kind_target_role_kind_counts'], 'offset_candidate_remap_missing_non_metadata_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_non_metadata_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts': offset_remap_metrics['missing_non_metadata_resource_reference_extension_counts'], 'offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts': offset_remap_metrics['missing_non_metadata_resource_reference_target_kind_extension_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts': offset_remap_metrics['missing_non_metadata_resource_reference_target_name_top_counts'], 'offset_candidate_remap_missing_unshifted_value_at_expected_offset_count': offset_remap_metrics['missing_unshifted_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidate_remap_missing_shifted_value_at_expected_offset_count': offset_remap_metrics['missing_shifted_value_at_expected_offset_count'], 'offset_candidate_remap_missing_other_value_at_expected_offset_count': offset_remap_metrics['missing_other_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidate_remap_missing_out_of_bounds_expected_offset_count': offset_remap_metrics['missing_out_of_bounds_expected_offset_count'], 'offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count': offset_remap_metrics['missing_after_excluding_unshifted_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset': offset_remap_metrics['remapped_after_excluding_unshifted_value_at_expected_offset'], 'offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_shifted_offset_match_count': offset_remap_metrics['missing_shifted_offset_match_count'], 'offset_candidate_remap_missing_shifted_value_match_count': offset_remap_metrics['missing_shifted_value_match_count']})
        _prefab_result.update({'offset_candidate_remap_missing_same_target_match_count': offset_remap_metrics['missing_same_target_match_count'], 'offset_candidate_remap_stale_unshifted_count': offset_remap_metrics['stale_unshifted_count']})
        _prefab_result.update({'offset_candidate_remap_stale_unshifted_target_kind_counts': offset_remap_metrics['stale_unshifted_target_kind_counts'], 'offset_candidate_remap_sample_missing': offset_remap_metrics['sample_missing']})
        _prefab_result.update({'offset_candidate_remap_sample_stale_unshifted': offset_remap_metrics['sample_stale_unshifted'], 'layout_fully_accounted_after_edit': layout_ok})
        _prefab_result.update({'no_edit_rebuild_after_edit': no_edit_rebuild_ok, 'json_no_edit_roundtrip_after_edit': json_no_edit_ok})
        _prefab_result.update({'json_layout_rebuild_after_edit': json_layout_rebuild_ok, 'used_low_level_profile_patch': True})
        _prefab_result.update({'replacement_field_found': replacement_found, 'error': error})
        _prefab_result.update({**selected_resize_metrics})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError, UnicodeEncodeError) as exc:
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'edited_field_count': 0})
        _prefab_result.update({'byte_delta': 0, 'offset_candidate_count_after_edit': 0})
        _prefab_result.update({'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False})
        _prefab_result.update({'offset_candidate_report_only_effective_remap_status': 'none', 'resized_rebuild_changed_only_expected_bytes': False})
        _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
        _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
        _prefab_result.update({'json_layout_rebuild_after_edit': False, 'used_low_level_profile_patch': False})
        _prefab_result.update({'replacement_field_found': False, 'error': str(exc)})
        _prefab_result.update({**selected_resize_metrics})
        return _prefab_result


def _audit_experimental_length_change_resource_rebuild_probe(payload: bytes, document: Mapping[str, object], virtual_path: str) -> dict[str, object]:
    from cdmw.core.prefab_corpus_candidate_offsets_1 import _offset_candidate_remap_metrics_after_resize
    from cdmw.core.prefab_corpus_probe_values import _effective_offset_value_replacements_after_resize, _expected_length_changed_bytes, _longer_probe_value
    from cdmw.core.prefab_corpus_resize_impact_0 import _selected_resize_offset_candidate_metrics
    selected_resize_metrics = _selected_resize_offset_candidate_metrics(None, ())
    try:
        editable = document.get('editable')
        if not isinstance(editable, Mapping):
            raise PrefabEditJsonError('Prefab edit document has no editable object.')
        rows = editable.get('resource_references')
        if not isinstance(rows, list):
            raise PrefabEditJsonError('Prefab edit document has no resource reference rows.')
        selected_replacements: list[str] = []
        edit_deltas: list[tuple[int, int]] = []
        record_replacements: list[tuple[int, int, bytes]] = []
        expected_delta = 0
        probe_document = deepcopy(document)
        probe_rows = probe_document['editable']['resource_references']
        edited_field_indexes: set[int] = set()
        edited_originals: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            original = str(row.get('text') or '')
            if original in edited_originals:
                continue
            replacement = _longer_probe_value(original)
            if not replacement:
                continue
            group_edits: list[tuple[int, int, int]] = []
            group_field_indexes: set[int] = set()
            for group_row in rows:
                if not isinstance(group_row, Mapping) or str(group_row.get('text') or '') != original:
                    continue
                field_index = int(group_row.get('field_index'))
                original_length = int(group_row.get('byte_length') or 0)
                delta = len(replacement.encode('utf-8')) - original_length
                if delta <= 0:
                    group_edits = []
                    break
                group_edits.append((int(group_row.get('row_index')), int(group_row.get('offset')) + 4 + original_length, delta))
                group_field_indexes.add(field_index)
            if not group_edits:
                continue
            for row_index, edit_end, delta in group_edits:
                group_row = probe_rows[row_index]
                original_length = int(group_row.get('byte_length') or 0)
                offset = int(group_row.get('offset') or 0)
                probe_rows[row_index]['value'] = replacement
                edit_deltas.append((edit_end, delta))
                encoded = replacement.encode('utf-8')
                record_replacements.append((offset, offset + 4 + original_length, len(encoded).to_bytes(4, 'little') + encoded))
                expected_delta += delta
            edited_field_indexes.update(group_field_indexes)
            edited_originals.add(original)
            selected_replacements.append(replacement)
            if len(edited_field_indexes) >= 2:
                break
        if not edited_field_indexes:
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'edited_reference_count': 0})
            _prefab_result.update({'byte_delta': 0, 'offset_candidate_count_after_edit': 0})
            _prefab_result.update({'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False})
            _prefab_result.update({'offset_candidate_report_only_effective_remap_status': 'none', 'resized_rebuild_changed_only_expected_bytes': False})
            _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': False})
            _prefab_result.update({'replacement_reference_found': False, 'error': NO_SAFE_RESOURCE_LENGTH_PROBE_REASON})
            _prefab_result.update({**selected_resize_metrics})
            return _prefab_result
        before_decoded = decode_prefab(payload)
        selected_resize_metrics = _selected_resize_offset_candidate_metrics(before_decoded, edit_deltas, payload)
        patched = apply_prefab_edit_document(payload, probe_document, virtual_path=virtual_path, allow_experimental_length_change=True)
        decoded = decode_prefab(patched)
        layout_ok = decoded.layout.fully_accounted
        no_edit_rebuild_ok = rebuild_prefab_no_edit(patched) == patched
        patched_document = build_prefab_edit_document(patched, virtual_path)
        json_no_edit_ok = apply_prefab_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        json_layout_rebuild_ok = rebuild_prefab_no_edit_from_edit_document(patched, patched_document, virtual_path=virtual_path) == patched
        patched_references = {reference.text.replace('\\', '/').strip() for reference in decoded.references}
        replacement_found = all((replacement in patched_references for replacement in selected_replacements))
        byte_delta = len(patched) - len(payload)

        def shift(position: int) -> int:
            return int(position) + sum((delta for edit_end, delta in edit_deltas if int(position) >= edit_end))
        expected_patched = _expected_length_changed_bytes(payload, record_replacements, tuple(((int(candidate.offset), shift(int(candidate.value))) for candidate in before_decoded.offset_candidates)))
        changed_only_expected = expected_patched == patched
        offset_remap_metrics = _offset_candidate_remap_metrics_after_resize(before_decoded, decoded, edit_deltas, patched)
        effective_expected_patched = _expected_length_changed_bytes(payload, record_replacements, _effective_offset_value_replacements_after_resize(before_decoded, edit_deltas, patched))
        changed_only_effective_expected = effective_expected_patched == patched
        offset_candidates_remapped = offset_remap_metrics['remapped'] is True
        offset_candidates_effectively_remapped = offset_remap_metrics['effectively_remapped'] is True
        ok = patched != payload and byte_delta == expected_delta and layout_ok and no_edit_rebuild_ok and json_no_edit_ok and json_layout_rebuild_ok and replacement_found and offset_candidates_remapped and changed_only_expected
        _prefab_result = {}
        _prefab_result.update({'status': 'passed' if ok else 'failed', 'edited_reference_count': len(edited_field_indexes)})
        _prefab_result.update({'byte_delta': byte_delta, 'offset_candidate_count_after_edit': len(decoded.offset_candidates)})
        _prefab_result.update({'offset_candidates_remapped_after_edit': offset_candidates_remapped, 'offset_candidates_effectively_remapped_after_edit': offset_candidates_effectively_remapped})
        _prefab_result.update({'offset_candidate_report_only_effective_remap_status': offset_remap_metrics['report_only_effective_remap_status'], 'resized_rebuild_changed_only_expected_bytes': changed_only_expected})
        _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': changed_only_effective_expected, 'offset_candidate_remap_missing_count': offset_remap_metrics['missing_count']})
        _prefab_result.update({'offset_candidate_remap_missing_target_kind_counts': offset_remap_metrics['missing_target_kind_counts'], 'offset_candidate_remap_missing_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_metadata_target_count': offset_remap_metrics['missing_metadata_target_count'], 'offset_candidate_remap_missing_non_metadata_target_count': offset_remap_metrics['missing_non_metadata_target_count']})
        _prefab_result.update({'offset_candidate_remap_missing_metadata_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_metadata_owner_kind_target_role_kind_counts'], 'offset_candidate_remap_missing_non_metadata_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_non_metadata_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_non_metadata_resource_reference_extension_counts': offset_remap_metrics['missing_non_metadata_resource_reference_extension_counts'], 'offset_candidate_remap_missing_non_metadata_resource_reference_target_kind_extension_counts': offset_remap_metrics['missing_non_metadata_resource_reference_target_kind_extension_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_non_metadata_resource_reference_target_name_top_counts': offset_remap_metrics['missing_non_metadata_resource_reference_target_name_top_counts'], 'offset_candidate_remap_missing_unshifted_value_at_expected_offset_count': offset_remap_metrics['missing_unshifted_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidate_remap_missing_shifted_value_at_expected_offset_count': offset_remap_metrics['missing_shifted_value_at_expected_offset_count'], 'offset_candidate_remap_missing_other_value_at_expected_offset_count': offset_remap_metrics['missing_other_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidate_remap_missing_out_of_bounds_expected_offset_count': offset_remap_metrics['missing_out_of_bounds_expected_offset_count'], 'offset_candidate_remap_missing_after_excluding_unshifted_value_at_expected_offset_count': offset_remap_metrics['missing_after_excluding_unshifted_value_at_expected_offset_count']})
        _prefab_result.update({'offset_candidates_remapped_after_excluding_unshifted_value_at_expected_offset': offset_remap_metrics['remapped_after_excluding_unshifted_value_at_expected_offset'], 'offset_candidate_remap_missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts': offset_remap_metrics['missing_unshifted_value_at_expected_offset_owner_kind_target_role_kind_counts']})
        _prefab_result.update({'offset_candidate_remap_missing_shifted_offset_match_count': offset_remap_metrics['missing_shifted_offset_match_count'], 'offset_candidate_remap_missing_shifted_value_match_count': offset_remap_metrics['missing_shifted_value_match_count']})
        _prefab_result.update({'offset_candidate_remap_missing_same_target_match_count': offset_remap_metrics['missing_same_target_match_count'], 'offset_candidate_remap_stale_unshifted_count': offset_remap_metrics['stale_unshifted_count']})
        _prefab_result.update({'offset_candidate_remap_stale_unshifted_target_kind_counts': offset_remap_metrics['stale_unshifted_target_kind_counts'], 'offset_candidate_remap_sample_missing': offset_remap_metrics['sample_missing']})
        _prefab_result.update({'offset_candidate_remap_sample_stale_unshifted': offset_remap_metrics['sample_stale_unshifted'], 'layout_fully_accounted_after_edit': layout_ok})
        _prefab_result.update({'no_edit_rebuild_after_edit': no_edit_rebuild_ok, 'json_no_edit_roundtrip_after_edit': json_no_edit_ok})
        _prefab_result.update({'json_layout_rebuild_after_edit': json_layout_rebuild_ok, 'used_opt_in_import_path': True})
        _prefab_result.update({'replacement_reference_found': replacement_found, 'error': '' if ok else 'Experimental length-changing rebuild probe failed parser/layout/JSON checks.'})
        _prefab_result.update({**selected_resize_metrics})
        return _prefab_result
    except (PrefabEditJsonError, ValueError, TypeError, KeyError) as exc:
        if 'offset candidates overlap' in str(exc):
            _prefab_result = {}
            _prefab_result.update({'status': 'skipped', 'edited_reference_count': 0})
            _prefab_result.update({'byte_delta': 0, 'offset_candidate_count_after_edit': 0})
            _prefab_result.update({'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False})
            _prefab_result.update({'offset_candidate_report_only_effective_remap_status': 'none', 'resized_rebuild_changed_only_expected_bytes': False})
            _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
            _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
            _prefab_result.update({'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': True})
            _prefab_result.update({'replacement_reference_found': False, 'error': str(exc)})
            _prefab_result.update({**selected_resize_metrics})
            return _prefab_result
        _prefab_result = {}
        _prefab_result.update({'status': 'failed', 'edited_reference_count': 0})
        _prefab_result.update({'byte_delta': 0, 'offset_candidate_count_after_edit': 0})
        _prefab_result.update({'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False})
        _prefab_result.update({'offset_candidate_report_only_effective_remap_status': 'none', 'resized_rebuild_changed_only_expected_bytes': False})
        _prefab_result.update({'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False})
        _prefab_result.update({'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False})
        _prefab_result.update({'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': False})
        _prefab_result.update({'replacement_reference_found': False, 'error': str(exc)})
        _prefab_result.update({**selected_resize_metrics})
        return _prefab_result
