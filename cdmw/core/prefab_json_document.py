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


from cdmw.core.prefab_json_common import _as_bool, _as_int, _as_mapping, _as_string, _normalize_path, _require_keys, _sha256_hex

def _header_document(data: bytes, decoded: Any | None=None) -> dict[str, Any]:
    payload = bytes(data or b'')
    header = (decoded or decode_prefab(payload)).header
    prefix = payload[:max(0, int(header.prefix_byte_length))]
    return {'magic': header.magic, 'version': header.version, 'prefix_byte_length': header.prefix_byte_length, 'first_string_offset': header.first_string_offset, 'prefix_sha256': _sha256_hex(prefix)}


def _member_declarations_document(data: bytes, decoded: Any) -> list[dict[str, Any]]:
    payload = bytes(data or b'')
    return [{'member_index': declaration.member_index, 'name_field_index': declaration.name_field_index, 'type_field_index': declaration.type_field_index, 'name_offset': declaration.name_offset, 'type_offset': declaration.type_offset, 'descriptor_offset': declaration.descriptor_offset, 'descriptor_byte_length': declaration.descriptor_byte_length, 'descriptor_words_le_u16': list(declaration.descriptor_words_le_u16), 'descriptor_kind': declaration.descriptor_kind, 'is_array': declaration.is_array, 'is_reference': declaration.is_reference, 'is_transform': declaration.is_transform, 'array_stride_hint': declaration.array_stride_hint, 'array_count_hint': declaration.array_count_hint, 'descriptor_sha256': _sha256_hex(payload[declaration.descriptor_offset:declaration.descriptor_offset + declaration.descriptor_byte_length]), 'name': declaration.name, 'type': declaration.type_name} for declaration in decoded.member_declarations]


def _layout_document(decoded: Any) -> dict[str, Any]:
    layout = decoded.layout
    return {'byte_length': layout.byte_length, 'span_count': len(layout.spans), 'string_span_count': layout.string_span_count, 'preserved_span_count': layout.preserved_span_count, 'parsed_string_byte_count': layout.parsed_string_byte_count, 'preserved_byte_count': layout.preserved_byte_count, 'accounted_byte_count': layout.accounted_byte_count, 'fully_accounted': layout.fully_accounted, 'spans': [{'span_index': span.index, 'start': span.start, 'end': span.end, 'kind': span.kind, 'field_index': span.field_index} for span in layout.spans]}


def _offset_candidates_document(decoded: Any) -> list[dict[str, Any]]:
    return [{'row_index': index, 'offset': candidate.offset, 'value': candidate.value, 'target_kind': candidate.target_kind, 'target_field_index': candidate.target_field_index, 'candidate_offset_mod4': candidate.offset % 4, 'target_value_mod4': candidate.value % 4} for index, candidate in enumerate(decoded.offset_candidates)]


def _resize_impact_document(decoded: Any, record_end: int) -> dict[str, Any]:
    end = int(record_end)
    affected_count = sum((1 for candidate in decoded.offset_candidates if int(candidate.value) >= end))
    downstream_byte_count = max(0, int(decoded.layout.byte_length) - end)
    tail_only = downstream_byte_count == 0
    plan_kind = 'blocked_by_offset_candidates' if affected_count else 'tail_length_prefix_only' if tail_only else 'blocked_by_downstream_bytes'
    return {'length_change_supported': False, 'affected_offset_candidate_count': affected_count, 'length_change_plan': {'enabled': False, 'kind': plan_kind, 'tail_only': tail_only, 'downstream_byte_count': downstream_byte_count, 'affected_offset_candidate_count': affected_count}, 'reason': f'Length change would require rebuilding {affected_count} preserved-byte offset candidate(s).' if affected_count else 'No offset candidates after this record were recovered, but count/padding rebuild is still not proven.'}


def _validate_resize_impact(raw_value: Any, expected: Mapping[str, Any], label: str) -> None:
    impact = _as_mapping(raw_value, label)
    _require_keys(impact, {'length_change_supported', 'affected_offset_candidate_count', 'length_change_plan', 'reason'}, label)
    plan = _as_mapping(impact.get('length_change_plan'), f'{label}.length_change_plan')
    _require_keys(plan, {'enabled', 'kind', 'tail_only', 'downstream_byte_count', 'affected_offset_candidate_count'}, f'{label}.length_change_plan')
    actual = {'length_change_supported': _as_bool(impact.get('length_change_supported'), f'{label}.length_change_supported'), 'affected_offset_candidate_count': _as_int(impact.get('affected_offset_candidate_count'), f'{label}.affected_offset_candidate_count'), 'length_change_plan': {'enabled': _as_bool(plan.get('enabled'), f'{label}.length_change_plan.enabled'), 'kind': _as_string(plan.get('kind'), f'{label}.length_change_plan.kind'), 'tail_only': _as_bool(plan.get('tail_only'), f'{label}.length_change_plan.tail_only'), 'downstream_byte_count': _as_int(plan.get('downstream_byte_count'), f'{label}.length_change_plan.downstream_byte_count'), 'affected_offset_candidate_count': _as_int(plan.get('affected_offset_candidate_count'), f'{label}.length_change_plan.affected_offset_candidate_count')}, 'reason': _as_string(impact.get('reason'), f'{label}.reason')}
    if actual != dict(expected):
        raise PrefabEditJsonError('Prefab edit JSON resize impact evidence does not match the selected prefab.')


def _length_change_blocked_message(label: str, slot_length: int, replacement_length: int, impact: Mapping[str, Any]) -> str:
    return f"{label} must keep the same byte length in V1 ({slot_length} byte slot, replacement is {replacement_length} byte(s)); {impact.get('reason')}"


def _placement_fields_document(data: bytes, decoded: Any | None=None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefab = decoded or decode_prefab(data)
    for field in inspect_prefab_attachment_profile_fields(data):
        if field.field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            continue
        rows.append({'row_index': len(rows), 'field_name': field.field_name, 'length_offset': field.length_offset, 'value_offset': field.value_offset, 'byte_length': field.byte_length, 'text': field.value, 'value': field.value, 'resize_impact': _resize_impact_document(prefab, field.value_offset + field.byte_length)})
    return rows


def _role_set(roles: Sequence[str]) -> set[str]:
    return {str(role or '').strip().lower() for role in roles if str(role or '').strip()}


def _is_exact_layout_string_field(decoded: Any, field: Any) -> bool:
    field_start = int(field.offset)
    field_end = field_start + 4 + int(field.length)
    return any((span.kind == 'string_field' and int(span.field_index) == int(field.index) and (int(span.start) == field_start) and (int(span.end) == field_end) for span in decoded.layout.spans))


def _resource_reference_rows_document(decoded: Any, roles: Sequence[str]) -> list[dict[str, Any]]:
    allowed_roles = _role_set(roles)
    rows: list[dict[str, Any]] = []
    for reference in decoded.references:
        if reference.role not in allowed_roles:
            continue
        if not _is_exact_layout_string_field(decoded, reference.field):
            continue
        text = _normalize_path(reference.text)
        rows.append({'row_index': len(rows), 'field_index': reference.field.index, 'offset': reference.field.offset, 'byte_length': reference.field.length, 'role': reference.role, 'extension': reference.extension, 'text': text, 'value': text, 'resize_impact': _resize_impact_document(decoded, reference.field.offset + 4 + reference.field.length)})
    return rows


def _resize_readiness_document(resource_rows: Sequence[Mapping[str, Any]], placement_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    editable_row_count = len(resource_rows) + len(placement_rows)
    impacted_row_count = 0
    affected_offset_candidate_rows = 0
    for row in [*resource_rows, *placement_rows]:
        impact = row.get('resize_impact')
        if not isinstance(impact, Mapping):
            continue
        raw_count = impact.get('affected_offset_candidate_count')
        if not isinstance(raw_count, int) or isinstance(raw_count, bool):
            continue
        affected_offset_candidate_rows += raw_count
        if raw_count:
            impacted_row_count += 1
    reason = f'Length-changing import is blocked; editable rows would require rebuilding {affected_offset_candidate_rows} preserved-byte offset candidate(s).' if affected_offset_candidate_rows else 'Length-changing import is blocked; count/padding rebuild is still not proven.'
    return {'length_changing_import_ready': False, 'editable_row_count': editable_row_count, 'editable_rows_with_resize_impact': impacted_row_count, 'affected_offset_candidate_rows': affected_offset_candidate_rows, 'reason': reason}


def _policy_document(data: bytes, decoded: Any, resource_rows: Sequence[Mapping[str, Any]] | None=None, placement_rows: Sequence[Mapping[str, Any]] | None=None) -> dict[str, Any]:
    resources = list(resource_rows) if resource_rows is not None else _resource_reference_rows_document(decoded, SUPPORTED_PREFAB_EDIT_ROLES)
    placements = list(placement_rows) if placement_rows is not None else _placement_fields_document(data, decoded)
    return {'edit_mode': 'same_length_resource_companion_and_placement_fields_only', 'resizing_supported': False, 'length_changing_rebuild_supported': False, 'resize_readiness': _resize_readiness_document(resources, placements), 'layout_no_edit_rebuild_proven': bool(decoded.layout.fully_accounted), 'same_length_resource_reference_edits': bool(resources), 'same_length_placement_field_edits': bool(placements), 'transform_value_editing_supported': False, 'array_resizing_supported': False}


def build_prefab_edit_document(data: bytes, virtual_path: str='', *, roles: Sequence[str]=SUPPORTED_PREFAB_EDIT_ROLES) -> dict[str, Any]:
    payload = bytes(data or b'')
    decoded = decode_prefab(payload)
    rows = _resource_reference_rows_document(decoded, roles)
    placement_rows = _placement_fields_document(payload, decoded)
    return {'format': PREFAB_EDIT_JSON_FORMAT, 'version': PREFAB_EDIT_JSON_VERSION, 'source': {'path': _normalize_path(virtual_path), 'sha256': _sha256_hex(payload), 'byte_length': len(payload)}, 'policy': _policy_document(payload, decoded, rows, placement_rows), 'structure': {'header': _header_document(payload, decoded), 'layout': _layout_document(decoded), 'member_declarations': _member_declarations_document(payload, decoded), 'offset_candidates': _offset_candidates_document(decoded)}, 'declared_fields': list(decoded.declared_fields), 'editable': {'resource_references': rows, 'placement_fields': placement_rows}}


def dumps_prefab_edit_json(data: bytes, virtual_path: str='') -> str:
    return json.dumps(build_prefab_edit_document(data, virtual_path), indent=2)
