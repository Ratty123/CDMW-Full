from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from cdmw.domain.archives.prefab import (
    PREFAB_EDIT_JSON_FORMAT,
    PREFAB_EDIT_JSON_VERSION,
    SUPPORTED_PREFAB_EDIT_ROLES,
    SUPPORTED_PREFAB_PLACEMENT_FIELDS,
    PrefabEditJsonError,
)
from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import (
    build_prefab_resource_path_patch,
    decode_prefab,
    rebuild_prefab_resized_strings,
)


from cdmw.core.prefab_json_common import _as_bool, _as_int, _as_list, _as_mapping, _as_string, _normalize_path, _require_keys, _sha256_hex
from cdmw.core.prefab_json_document import _header_document, _is_exact_layout_string_field, _layout_document, _length_change_blocked_message, _member_declarations_document, _offset_candidates_document, _policy_document, _resize_impact_document, _role_set, _validate_resize_impact

def _validate_source_identity(data: bytes, document: Mapping[str, Any], virtual_path: str='') -> None:
    source = _as_mapping(document.get('source'), 'source')
    _require_keys(source, {'path', 'sha256', 'byte_length'}, 'source')
    expected_length = _as_int(source.get('byte_length'), 'source.byte_length')
    if expected_length != len(data):
        raise PrefabEditJsonError('Prefab edit JSON source byte length does not match the selected prefab.')
    expected_sha = _as_string(source.get('sha256'), 'source.sha256')
    if expected_sha.lower() != _sha256_hex(data):
        raise PrefabEditJsonError('Prefab edit JSON source SHA-256 does not match the selected prefab.')
    if virtual_path:
        document_path = _normalize_path(_as_string(source.get('path'), 'source.path')).casefold()
        selected_path = _normalize_path(virtual_path).casefold()
        if document_path and document_path != selected_path:
            raise PrefabEditJsonError('Prefab edit JSON source path does not match the selected prefab.')


def _current_reference_keys_and_counts(data: bytes, roles: Sequence[str]) -> tuple[set[tuple[int, int, int, str, str, str]], dict[str, int]]:
    allowed_roles = _role_set(roles)
    decoded = decode_prefab(data)
    keys: set[tuple[int, int, int, str, str, str]] = set()
    counts: dict[str, int] = {}
    for reference in decoded.references:
        if reference.role not in allowed_roles:
            continue
        if not _is_exact_layout_string_field(decoded, reference.field):
            continue
        text = _normalize_path(reference.text)
        keys.add((reference.field.index, reference.field.offset, reference.field.length, reference.role, reference.extension, text))
        counts[text] = counts.get(text, 0) + 1
    return (keys, counts)


def _current_placement_keys(data: bytes) -> set[tuple[str, int, int, int, str]]:
    keys: set[tuple[str, int, int, int, str]] = set()
    for field in inspect_prefab_attachment_profile_fields(data):
        if field.field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            continue
        keys.add((field.field_name, field.length_offset, field.value_offset, field.byte_length, field.value))
    return keys


def _validate_resize_readiness(value: Any) -> dict[str, Any]:
    readiness = _as_mapping(value, 'policy.resize_readiness')
    _require_keys(readiness, {'length_changing_import_ready', 'editable_row_count', 'editable_rows_with_resize_impact', 'affected_offset_candidate_rows', 'reason'}, 'policy.resize_readiness')
    return {'length_changing_import_ready': _as_bool(readiness.get('length_changing_import_ready'), 'policy.resize_readiness.length_changing_import_ready'), 'editable_row_count': _as_int(readiness.get('editable_row_count'), 'policy.resize_readiness.editable_row_count'), 'editable_rows_with_resize_impact': _as_int(readiness.get('editable_rows_with_resize_impact'), 'policy.resize_readiness.editable_rows_with_resize_impact'), 'affected_offset_candidate_rows': _as_int(readiness.get('affected_offset_candidate_rows'), 'policy.resize_readiness.affected_offset_candidate_rows'), 'reason': _as_string(readiness.get('reason'), 'policy.resize_readiness.reason')}


def _validate_policy(data: bytes, document: Mapping[str, Any]) -> None:
    policy = _as_mapping(document.get('policy'), 'policy')
    _require_keys(policy, {'edit_mode', 'resizing_supported', 'length_changing_rebuild_supported', 'resize_readiness', 'layout_no_edit_rebuild_proven', 'same_length_resource_reference_edits', 'same_length_placement_field_edits', 'transform_value_editing_supported', 'array_resizing_supported'}, 'policy')
    edit_mode = _as_string(policy.get('edit_mode'), 'policy.edit_mode')
    if edit_mode != 'same_length_resource_companion_and_placement_fields_only':
        raise PrefabEditJsonError('Prefab edit JSON uses an unsupported edit mode.')
    if _as_bool(policy.get('resizing_supported'), 'policy.resizing_supported'):
        raise PrefabEditJsonError('Prefab edit JSON resizing is not supported in V1.')
    if _as_bool(policy.get('length_changing_rebuild_supported'), 'policy.length_changing_rebuild_supported'):
        raise PrefabEditJsonError('Prefab edit JSON length-changing rebuild is not supported in V1.')
    if _as_bool(policy.get('transform_value_editing_supported'), 'policy.transform_value_editing_supported'):
        raise PrefabEditJsonError('Prefab edit JSON transform value editing is not supported in V1.')
    if _as_bool(policy.get('array_resizing_supported'), 'policy.array_resizing_supported'):
        raise PrefabEditJsonError('Prefab edit JSON array resizing is not supported in V1.')
    decoded = decode_prefab(data)
    expected = _policy_document(data, decoded)
    actual = {'edit_mode': edit_mode, 'resizing_supported': False, 'length_changing_rebuild_supported': False, 'resize_readiness': _validate_resize_readiness(policy.get('resize_readiness')), 'layout_no_edit_rebuild_proven': _as_bool(policy.get('layout_no_edit_rebuild_proven'), 'policy.layout_no_edit_rebuild_proven'), 'same_length_resource_reference_edits': _as_bool(policy.get('same_length_resource_reference_edits'), 'policy.same_length_resource_reference_edits'), 'same_length_placement_field_edits': _as_bool(policy.get('same_length_placement_field_edits'), 'policy.same_length_placement_field_edits'), 'transform_value_editing_supported': False, 'array_resizing_supported': False}
    if actual != expected:
        raise PrefabEditJsonError('Prefab edit JSON policy evidence does not match the selected prefab.')


def _validate_declared_fields(data: bytes, document: Mapping[str, Any]) -> None:
    raw_fields = _as_list(document.get('declared_fields'), 'declared_fields')
    declared_fields = tuple((_as_string(value, 'declared_fields[]') for value in raw_fields))
    if declared_fields != tuple(decode_prefab(data).declared_fields):
        raise PrefabEditJsonError('Prefab edit JSON declared fields do not match the selected prefab.')


def _validate_placement_rows(data: bytes, rows: list[Any], decoded: Any | None=None) -> dict[str, str]:
    prefab = decoded or decode_prefab(data)
    current_keys = _current_placement_keys(data)
    seen_keys: set[tuple[str, int, int, int, str]] = set()
    replacements: dict[str, str] = {}
    for expected_row_index, raw_row in enumerate(rows):
        row = _as_mapping(raw_row, 'editable.placement_fields[]')
        _require_keys(row, {'row_index', 'field_name', 'length_offset', 'value_offset', 'byte_length', 'text', 'value', 'resize_impact'}, 'editable.placement_fields[]')
        row_index = _as_int(row.get('row_index'), 'editable.placement_fields[].row_index')
        if row_index != expected_row_index:
            raise PrefabEditJsonError('Prefab edit JSON placement row index does not match its position.')
        field_name = _as_string(row.get('field_name'), 'editable.placement_fields[].field_name')
        if field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            raise PrefabEditJsonError(f'Unsupported prefab placement field: {field_name}.')
        length_offset = _as_int(row.get('length_offset'), 'editable.placement_fields[].length_offset')
        value_offset = _as_int(row.get('value_offset'), 'editable.placement_fields[].value_offset')
        byte_length = _as_int(row.get('byte_length'), 'editable.placement_fields[].byte_length')
        original = _as_string(row.get('text'), 'editable.placement_fields[].text').strip()
        value = _as_string(row.get('value'), 'editable.placement_fields[].value').strip()
        key = (field_name, length_offset, value_offset, byte_length, original)
        if key not in current_keys:
            raise PrefabEditJsonError('Prefab edit JSON placement row does not match the selected prefab.')
        if key in seen_keys:
            raise PrefabEditJsonError('Prefab edit JSON contains a duplicate placement row.')
        seen_keys.add(key)
        resize_impact = _resize_impact_document(prefab, value_offset + byte_length)
        _validate_resize_impact(row.get('resize_impact'), resize_impact, 'editable.placement_fields[].resize_impact')
        if value == original:
            continue
        try:
            encoded = value.encode('ascii')
        except UnicodeEncodeError as exc:
            raise PrefabEditJsonError('Prefab placement replacement must be ASCII in V1.') from exc
        if len(encoded) != byte_length:
            raise PrefabEditJsonError(_length_change_blocked_message('Prefab placement replacement', byte_length, len(encoded), resize_impact))
        replacements[field_name] = value
    if seen_keys != current_keys:
        raise PrefabEditJsonError('Prefab edit JSON placement rows do not match the selected prefab.')
    return replacements


def _editable_rows(document: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    editable = _as_mapping(document.get('editable'), 'editable')
    _require_keys(editable, {'resource_references', 'placement_fields'}, 'editable')
    return (_as_list(editable.get('resource_references'), 'editable.resource_references'), _as_list(editable.get('placement_fields'), 'editable.placement_fields'))


def _validate_structure_header(data: bytes, structure: Mapping[str]) -> Any:
    header = _as_mapping(structure.get('header'), 'structure.header')
    _require_keys(header, {'magic', 'version', 'prefix_byte_length', 'first_string_offset', 'prefix_sha256'}, 'structure.header')
    decoded = decode_prefab(data)
    actual = _header_document(data, decoded)
    expected = {'magic': _as_int(header.get('magic'), 'structure.header.magic'), 'version': _as_int(header.get('version'), 'structure.header.version'), 'prefix_byte_length': _as_int(header.get('prefix_byte_length'), 'structure.header.prefix_byte_length'), 'first_string_offset': _as_int(header.get('first_string_offset'), 'structure.header.first_string_offset'), 'prefix_sha256': _as_string(header.get('prefix_sha256'), 'structure.header.prefix_sha256').lower()}
    if expected != actual:
        raise PrefabEditJsonError('Prefab edit JSON header evidence does not match the selected prefab.')
    return decoded


def _validate_structure_layout(structure: Mapping[str], decoded: Any) -> None:
    layout = _as_mapping(structure.get('layout'), 'structure.layout')
    _require_keys(layout, {'byte_length', 'span_count', 'string_span_count', 'preserved_span_count', 'parsed_string_byte_count', 'preserved_byte_count', 'accounted_byte_count', 'fully_accounted', 'spans'}, 'structure.layout')
    raw_spans = _as_list(layout.get('spans'), 'structure.layout.spans')
    spans: list[dict[str, Any]] = []
    for expected_span_index, raw_span in enumerate(raw_spans):
        span = _as_mapping(raw_span, 'structure.layout.spans[]')
        _require_keys(span, {'span_index', 'start', 'end', 'kind', 'field_index'}, 'structure.layout.spans[]')
        span_index = _as_int(span.get('span_index'), 'structure.layout.spans[].span_index')
        if span_index != expected_span_index:
            raise PrefabEditJsonError('Prefab edit JSON layout span index does not match its position.')
        spans.append({'span_index': span_index, 'start': _as_int(span.get('start'), 'structure.layout.spans[].start'), 'end': _as_int(span.get('end'), 'structure.layout.spans[].end'), 'kind': _as_string(span.get('kind'), 'structure.layout.spans[].kind'), 'field_index': _as_int(span.get('field_index'), 'structure.layout.spans[].field_index')})
    expected_layout = {'byte_length': _as_int(layout.get('byte_length'), 'structure.layout.byte_length'), 'span_count': _as_int(layout.get('span_count'), 'structure.layout.span_count'), 'string_span_count': _as_int(layout.get('string_span_count'), 'structure.layout.string_span_count'), 'preserved_span_count': _as_int(layout.get('preserved_span_count'), 'structure.layout.preserved_span_count'), 'parsed_string_byte_count': _as_int(layout.get('parsed_string_byte_count'), 'structure.layout.parsed_string_byte_count'), 'preserved_byte_count': _as_int(layout.get('preserved_byte_count'), 'structure.layout.preserved_byte_count'), 'accounted_byte_count': _as_int(layout.get('accounted_byte_count'), 'structure.layout.accounted_byte_count'), 'fully_accounted': _as_bool(layout.get('fully_accounted'), 'structure.layout.fully_accounted'), 'spans': spans}
    if expected_layout != _layout_document(decoded):
        raise PrefabEditJsonError('Prefab edit JSON layout evidence does not match the selected prefab.')


def _validate_structure_members(data: bytes, structure: Mapping[str], decoded: Any) -> None:
    raw_members = _as_list(structure.get('member_declarations'), 'structure.member_declarations')
    members: list[dict[str, Any]] = []
    for raw_member in raw_members:
        member = _as_mapping(raw_member, 'structure.member_declarations[]')
        _require_keys(member, {'member_index', 'name_field_index', 'type_field_index', 'name_offset', 'type_offset', 'descriptor_offset', 'descriptor_byte_length', 'descriptor_words_le_u16', 'descriptor_kind', 'is_array', 'is_reference', 'is_transform', 'array_stride_hint', 'array_count_hint', 'descriptor_sha256', 'name', 'type'}, 'structure.member_declarations[]')
        members.append({'member_index': _as_int(member.get('member_index'), 'structure.member_declarations[].member_index'), 'name_field_index': _as_int(member.get('name_field_index'), 'structure.member_declarations[].name_field_index'), 'type_field_index': _as_int(member.get('type_field_index'), 'structure.member_declarations[].type_field_index'), 'name_offset': _as_int(member.get('name_offset'), 'structure.member_declarations[].name_offset'), 'type_offset': _as_int(member.get('type_offset'), 'structure.member_declarations[].type_offset'), 'descriptor_offset': _as_int(member.get('descriptor_offset'), 'structure.member_declarations[].descriptor_offset'), 'descriptor_byte_length': _as_int(member.get('descriptor_byte_length'), 'structure.member_declarations[].descriptor_byte_length'), 'descriptor_words_le_u16': [_as_int(value, 'structure.member_declarations[].descriptor_words_le_u16[]') for value in _as_list(member.get('descriptor_words_le_u16'), 'structure.member_declarations[].descriptor_words_le_u16')], 'descriptor_kind': _as_string(member.get('descriptor_kind'), 'structure.member_declarations[].descriptor_kind'), 'is_array': _as_bool(member.get('is_array'), 'structure.member_declarations[].is_array'), 'is_reference': _as_bool(member.get('is_reference'), 'structure.member_declarations[].is_reference'), 'is_transform': _as_bool(member.get('is_transform'), 'structure.member_declarations[].is_transform'), 'array_stride_hint': _as_int(member.get('array_stride_hint'), 'structure.member_declarations[].array_stride_hint'), 'array_count_hint': _as_int(member.get('array_count_hint'), 'structure.member_declarations[].array_count_hint'), 'descriptor_sha256': _as_string(member.get('descriptor_sha256'), 'structure.member_declarations[].descriptor_sha256'), 'name': _as_string(member.get('name'), 'structure.member_declarations[].name'), 'type': _as_string(member.get('type'), 'structure.member_declarations[].type')})
    if members != _member_declarations_document(data, decoded):
        raise PrefabEditJsonError('Prefab edit JSON member declarations do not match the selected prefab.')


def _validate_structure_offset_candidates(structure: Mapping[str], decoded: Any) -> None:
    raw_offset_candidates = _as_list(structure.get('offset_candidates'), 'structure.offset_candidates')
    offset_candidates: list[dict[str, Any]] = []
    for expected_row_index, raw_candidate in enumerate(raw_offset_candidates):
        candidate = _as_mapping(raw_candidate, 'structure.offset_candidates[]')
        _require_keys(candidate, {'row_index', 'offset', 'value', 'target_kind', 'target_field_index', 'candidate_offset_mod4', 'target_value_mod4'}, 'structure.offset_candidates[]')
        row_index = _as_int(candidate.get('row_index'), 'structure.offset_candidates[].row_index')
        if row_index != expected_row_index:
            raise PrefabEditJsonError('Prefab edit JSON offset candidate row index does not match its position.')
        offset_candidates.append({'row_index': row_index, 'offset': _as_int(candidate.get('offset'), 'structure.offset_candidates[].offset'), 'value': _as_int(candidate.get('value'), 'structure.offset_candidates[].value'), 'target_kind': _as_string(candidate.get('target_kind'), 'structure.offset_candidates[].target_kind'), 'target_field_index': _as_int(candidate.get('target_field_index'), 'structure.offset_candidates[].target_field_index'), 'candidate_offset_mod4': _as_int(candidate.get('candidate_offset_mod4'), 'structure.offset_candidates[].candidate_offset_mod4'), 'target_value_mod4': _as_int(candidate.get('target_value_mod4'), 'structure.offset_candidates[].target_value_mod4')})
    if offset_candidates != _offset_candidates_document(decoded):
        raise PrefabEditJsonError('Prefab edit JSON offset candidates do not match the selected prefab.')


def _validate_structure(data: bytes, document: Mapping[str, Any]) -> None:
    structure = _as_mapping(document.get('structure'), 'structure')
    _require_keys(structure, {'header', 'layout', 'member_declarations', 'offset_candidates'}, 'structure')
    decoded = _validate_structure_header(data, structure)
    _validate_structure_layout(structure, decoded)
    _validate_structure_members(data, structure, decoded)
    _validate_structure_offset_candidates(structure, decoded)
