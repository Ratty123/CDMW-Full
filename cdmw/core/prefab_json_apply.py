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


from cdmw.core.prefab_json_common import _as_int, _as_list, _as_mapping, _as_string, _normalize_path, _require_keys, _validate_resource_replacement_path
from cdmw.core.prefab_json_document import _length_change_blocked_message, _resize_impact_document, _validate_resize_impact
from cdmw.core.prefab_json_validation import _current_reference_keys_and_counts, _editable_rows, _validate_declared_fields, _validate_placement_rows, _validate_policy, _validate_source_identity, _validate_structure

def apply_prefab_edit_document(data: bytes, document: Mapping[str, Any], *, virtual_path: str='', roles: Sequence[str]=SUPPORTED_PREFAB_EDIT_ROLES, allow_experimental_length_change: bool=False) -> bytes:
    payload = bytes(data or b'')
    root = _as_mapping(document, 'document')
    if root.get('format') != PREFAB_EDIT_JSON_FORMAT or root.get('version') != PREFAB_EDIT_JSON_VERSION:
        raise PrefabEditJsonError(f'Prefab edit JSON must use {PREFAB_EDIT_JSON_FORMAT}.')
    _require_keys(root, {'format', 'version', 'source', 'policy', 'structure', 'declared_fields', 'editable'}, 'document')
    _validate_source_identity(payload, root, virtual_path=virtual_path)
    _validate_policy(payload, root)
    _validate_structure(payload, root)
    _validate_declared_fields(payload, root)
    rows, placement_rows = _editable_rows(root)
    allowed_roles = {str(role or '').strip().lower() for role in roles if str(role or '').strip()}
    current_keys, current_counts_by_text = _current_reference_keys_and_counts(payload, tuple(allowed_roles))
    decoded_for_resize = decode_prefab(payload)
    same_length_replacements_by_text: dict[str, str] = {}
    resized_replacements_by_offset: dict[int, tuple[str, str]] = {}
    row_values_by_text: dict[str, set[str]] = {}
    row_counts_by_text: dict[str, int] = {}
    seen_keys: set[tuple[int, int, int, str, str, str]] = set()
    for expected_row_index, raw_row in enumerate(rows):
        row = _as_mapping(raw_row, 'editable.resource_references[]')
        _require_keys(row, {'row_index', 'field_index', 'offset', 'byte_length', 'role', 'extension', 'text', 'value', 'resize_impact'}, 'editable.resource_references[]')
        row_index = _as_int(row.get('row_index'), 'row_index')
        if row_index != expected_row_index:
            raise PrefabEditJsonError('Prefab edit JSON row index does not match its position.')
        field_index = _as_int(row.get('field_index'), 'field_index')
        offset = _as_int(row.get('offset'), 'offset')
        byte_length = _as_int(row.get('byte_length'), 'byte_length')
        role = _as_string(row.get('role'), 'role').strip().lower()
        extension = _as_string(row.get('extension'), 'extension').strip().lower()
        original = _normalize_path(_as_string(row.get('text'), 'text'))
        value = _normalize_path(_as_string(row.get('value'), 'value'))
        if role not in allowed_roles:
            raise PrefabEditJsonError(f'Unsupported prefab edit role: {role}.')
        key = (field_index, offset, byte_length, role, extension, original)
        if key not in current_keys:
            raise PrefabEditJsonError('Prefab edit JSON row does not match the selected prefab.')
        if key in seen_keys:
            raise PrefabEditJsonError('Prefab edit JSON contains a duplicate reference row.')
        seen_keys.add(key)
        resize_impact = _resize_impact_document(decoded_for_resize, offset + 4 + byte_length)
        _validate_resize_impact(row.get('resize_impact'), resize_impact, 'editable.resource_references[].resize_impact')
        row_values_by_text.setdefault(original, set()).add(value)
        row_counts_by_text[original] = row_counts_by_text.get(original, 0) + 1
        if value == original:
            continue
        _validate_resource_replacement_path(original, value, role, extension)
        replacement_length = len(value.encode('utf-8'))
        if replacement_length != byte_length:
            if not allow_experimental_length_change:
                raise PrefabEditJsonError(_length_change_blocked_message('Prefab replacement', byte_length, replacement_length, resize_impact))
            resized_replacements_by_offset[offset] = (original, value)
        previous = same_length_replacements_by_text.get(original)
        if previous is not None and previous != value:
            raise PrefabEditJsonError('Duplicate prefab references must use the same replacement value.')
        if replacement_length == byte_length:
            same_length_replacements_by_text[original] = value
    if seen_keys != current_keys:
        raise PrefabEditJsonError('Prefab edit JSON reference rows do not match the selected prefab.')
    changed_originals = {original for original, values in row_values_by_text.items() if values and values != {original}}
    for original in changed_originals:
        if row_counts_by_text.get(original, 0) != current_counts_by_text.get(original, 0):
            raise PrefabEditJsonError('Duplicate prefab references must all be present before editing.')
        values = row_values_by_text.get(original, set())
        replacement = next(iter(values)) if len(values) == 1 else ''
        if values != {replacement}:
            raise PrefabEditJsonError('Duplicate prefab references must be edited consistently.')
    placement_replacements = _validate_placement_rows(payload, placement_rows, decoded_for_resize)
    patched = payload
    if placement_replacements:
        try:
            patched = build_prefab_attachment_profile_patch(patched, attached_socket_name=placement_replacements.get('_attachedSocketName', ''), pivot_socket_name=placement_replacements.get('_pivotSocketName', ''), part_name=placement_replacements.get('_partName', '')).data
        except ValueError as exc:
            raise PrefabEditJsonError(str(exc)) from exc
    if same_length_replacements_by_text:
        patched = build_prefab_resource_path_patch(patched, same_length_replacements_by_text, roles=tuple(allowed_roles)).data
    if resized_replacements_by_offset:
        # This used to go through crimson_formats.rebuild_prefab_resized_strings,
        # which finds pointers by scanning for u32s that happen to equal a known
        # string offset and rewrites any coincidental match. The exact rewriter
        # relocates every pointer and length field by the identity rule and
        # reproduces the game's own output on 10,124 of 10,124 length-changing
        # prefabs in the archives, so there is no reason to keep the guesswork.
        from cdmw.core.prefab_binary import PrefabBinaryError
        from cdmw.core.prefab_binary_edit import PrefabPathEdit, rewrite_prefab_paths

        try:
            patched = rewrite_prefab_paths(
                patched,
                [
                    PrefabPathEdit(offset=offset, old_text=old, new_text=new)
                    for offset, (old, new) in sorted(resized_replacements_by_offset.items())
                ],
            ).data
        except PrefabBinaryError as exc:
            raise PrefabEditJsonError(
                "A different-length replacement needs a prefab this tool can read all "
                f"the way through, and this one stopped: {exc}"
            ) from exc
    return patched


def rebuild_prefab_no_edit_from_edit_document(data: bytes, document: Mapping[str, Any], *, virtual_path: str='') -> bytes:
    payload = bytes(data or b'')
    root = _as_mapping(document, 'document')
    if root.get('format') != PREFAB_EDIT_JSON_FORMAT or root.get('version') != PREFAB_EDIT_JSON_VERSION:
        raise PrefabEditJsonError(f'Prefab edit JSON must use {PREFAB_EDIT_JSON_FORMAT}.')
    _require_keys(root, {'format', 'version', 'source', 'policy', 'structure', 'declared_fields', 'editable'}, 'document')
    _validate_source_identity(payload, root, virtual_path=virtual_path)
    _validate_policy(payload, root)
    _validate_structure(payload, root)
    _validate_declared_fields(payload, root)
    _editable_rows(root)
    if apply_prefab_edit_document(payload, root, virtual_path=virtual_path) != payload:
        raise PrefabEditJsonError('Prefab edit JSON no-edit rebuild cannot contain editable value changes.')
    layout = _as_mapping(_as_mapping(root.get('structure'), 'structure').get('layout'), 'structure.layout')
    spans = _as_list(layout.get('spans'), 'structure.layout.spans')
    rebuilt = bytearray()
    cursor = 0
    for raw_span in spans:
        span = _as_mapping(raw_span, 'structure.layout.spans[]')
        start = _as_int(span.get('start'), 'structure.layout.spans[].start')
        end = _as_int(span.get('end'), 'structure.layout.spans[].end')
        kind = _as_string(span.get('kind'), 'structure.layout.spans[].kind')
        if start != cursor:
            raise PrefabEditJsonError('Prefab edit JSON layout spans have a gap or overlap.')
        if start < 0 or end < start or end > len(payload):
            raise PrefabEditJsonError('Prefab edit JSON layout span points outside the payload.')
        if kind not in {'preserved', 'string_field'}:
            raise PrefabEditJsonError(f'Unsupported prefab layout span kind: {kind}.')
        rebuilt.extend(payload[start:end])
        cursor = end
    if cursor != len(payload) or len(rebuilt) != _as_int(layout.get('byte_length'), 'structure.layout.byte_length'):
        raise PrefabEditJsonError('Prefab edit JSON layout rebuild did not account for the full payload.')
    return bytes(rebuilt)


def apply_prefab_edit_json(data: bytes, document_text: str, *, virtual_path: str='', roles: Sequence[str]=SUPPORTED_PREFAB_EDIT_ROLES) -> bytes:
    try:
        document = json.loads(document_text)
    except json.JSONDecodeError as exc:
        raise PrefabEditJsonError('Prefab edit JSON is not valid JSON.') from exc
    return apply_prefab_edit_document(data, _as_mapping(document, 'document'), virtual_path=virtual_path, roles=roles)
