from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import (
    build_prefab_resource_path_patch,
    decode_prefab,
    rebuild_prefab_resized_strings,
)


PREFAB_EDIT_JSON_FORMAT = "cdmw.prefab.edit.v1"
PREFAB_EDIT_JSON_VERSION = 1
SUPPORTED_PREFAB_EDIT_ROLES = ("model", "material_sidecar", "texture", "companion_metadata")
SUPPORTED_PREFAB_PLACEMENT_FIELDS = ("_attachedSocketName", "_pivotSocketName", "_partName")


class PrefabEditJsonError(ValueError):
    """Raised when a prefab edit document is stale, malformed, or unsafe."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PrefabEditJsonError(f"{label} must be a JSON object.")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PrefabEditJsonError(f"{label} must be a JSON array.")
    return value


def _as_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PrefabEditJsonError(f"{label} must be a string.")
    return value


def _as_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PrefabEditJsonError(f"{label} must be an integer.")
    return value


def _as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PrefabEditJsonError(f"{label} must be a boolean.")
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    keys = set(value.keys())
    missing = sorted(allowed - keys)
    if missing:
        raise PrefabEditJsonError(f"{label} is missing required field(s): {', '.join(missing)}.")
    extra = sorted(keys - allowed)
    if extra:
        raise PrefabEditJsonError(f"{label} contains unsupported field(s): {', '.join(extra)}.")


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _resource_path_extension(value: str) -> str:
    return PurePosixPath(_normalize_path(value)).suffix.lower()


def _validate_resource_replacement_path(original: str, value: str, role: str, extension: str) -> None:
    normalized = _normalize_path(value)
    if not normalized or any(ord(char) < 0x20 for char in normalized):
        raise PrefabEditJsonError("Prefab replacement path is invalid.")
    if normalized.startswith("/") or ":" in normalized or "//" in normalized:
        raise PrefabEditJsonError("Prefab replacement path is invalid.")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PrefabEditJsonError("Prefab replacement path is invalid.")
    if "/" not in normalized:
        raise PrefabEditJsonError("Prefab replacement path must stay relative to game data.")
    expected_extension = str(extension or "").strip().lower()
    if _resource_path_extension(normalized) != expected_extension:
        raise PrefabEditJsonError("Prefab replacement path must keep the same extension in V1.")
    if str(original or "").casefold().endswith(".sockets.xml") and not normalized.casefold().endswith(".sockets.xml"):
        raise PrefabEditJsonError("Prefab socket descriptor replacement must keep the .sockets.xml suffix in V1.")
    if role == "model" and expected_extension not in {".pac", ".pam", ".pamlod"}:
        raise PrefabEditJsonError("Prefab model replacement path has an unsupported extension.")
    if role == "texture" and expected_extension != ".dds":
        raise PrefabEditJsonError("Prefab texture replacement path has an unsupported extension.")


def _header_document(data: bytes, decoded: Any | None = None) -> dict[str, Any]:
    payload = bytes(data or b"")
    header = (decoded or decode_prefab(payload)).header
    prefix = payload[: max(0, int(header.prefix_byte_length))]
    return {
        "magic": header.magic,
        "version": header.version,
        "prefix_byte_length": header.prefix_byte_length,
        "first_string_offset": header.first_string_offset,
        "prefix_sha256": _sha256_hex(prefix),
    }


def _member_declarations_document(data: bytes, decoded: Any) -> list[dict[str, Any]]:
    payload = bytes(data or b"")
    return [
        {
            "member_index": declaration.member_index,
            "name_field_index": declaration.name_field_index,
            "type_field_index": declaration.type_field_index,
            "name_offset": declaration.name_offset,
            "type_offset": declaration.type_offset,
            "descriptor_offset": declaration.descriptor_offset,
            "descriptor_byte_length": declaration.descriptor_byte_length,
            "descriptor_words_le_u16": list(declaration.descriptor_words_le_u16),
            "descriptor_kind": declaration.descriptor_kind,
            "is_array": declaration.is_array,
            "is_reference": declaration.is_reference,
            "is_transform": declaration.is_transform,
            "array_stride_hint": declaration.array_stride_hint,
            "array_count_hint": declaration.array_count_hint,
            "descriptor_sha256": _sha256_hex(
                payload[declaration.descriptor_offset : declaration.descriptor_offset + declaration.descriptor_byte_length]
            ),
            "name": declaration.name,
            "type": declaration.type_name,
        }
        for declaration in decoded.member_declarations
    ]


def _layout_document(decoded: Any) -> dict[str, Any]:
    layout = decoded.layout
    return {
        "byte_length": layout.byte_length,
        "span_count": len(layout.spans),
        "string_span_count": layout.string_span_count,
        "preserved_span_count": layout.preserved_span_count,
        "parsed_string_byte_count": layout.parsed_string_byte_count,
        "preserved_byte_count": layout.preserved_byte_count,
        "accounted_byte_count": layout.accounted_byte_count,
        "fully_accounted": layout.fully_accounted,
        "spans": [
            {
                "span_index": span.index,
                "start": span.start,
                "end": span.end,
                "kind": span.kind,
                "field_index": span.field_index,
            }
            for span in layout.spans
        ],
    }


def _offset_candidates_document(decoded: Any) -> list[dict[str, Any]]:
    return [
        {
            "row_index": index,
            "offset": candidate.offset,
            "value": candidate.value,
            "target_kind": candidate.target_kind,
            "target_field_index": candidate.target_field_index,
            "candidate_offset_mod4": candidate.offset % 4,
            "target_value_mod4": candidate.value % 4,
        }
        for index, candidate in enumerate(decoded.offset_candidates)
    ]


def _resize_impact_document(decoded: Any, record_end: int) -> dict[str, Any]:
    end = int(record_end)
    affected_count = sum(1 for candidate in decoded.offset_candidates if int(candidate.value) >= end)
    downstream_byte_count = max(0, int(decoded.layout.byte_length) - end)
    tail_only = downstream_byte_count == 0
    plan_kind = (
        "blocked_by_offset_candidates"
        if affected_count
        else "tail_length_prefix_only"
        if tail_only
        else "blocked_by_downstream_bytes"
    )
    return {
        "length_change_supported": False,
        "affected_offset_candidate_count": affected_count,
        "length_change_plan": {
            "enabled": False,
            "kind": plan_kind,
            "tail_only": tail_only,
            "downstream_byte_count": downstream_byte_count,
            "affected_offset_candidate_count": affected_count,
        },
        "reason": (
            f"Length change would require rebuilding {affected_count} preserved-byte offset candidate(s)."
            if affected_count
            else "No offset candidates after this record were recovered, but count/padding rebuild is still not proven."
        ),
    }


def _validate_resize_impact(raw_value: Any, expected: Mapping[str, Any], label: str) -> None:
    impact = _as_mapping(raw_value, label)
    _require_keys(
        impact,
        {"length_change_supported", "affected_offset_candidate_count", "length_change_plan", "reason"},
        label,
    )
    plan = _as_mapping(impact.get("length_change_plan"), f"{label}.length_change_plan")
    _require_keys(
        plan,
        {"enabled", "kind", "tail_only", "downstream_byte_count", "affected_offset_candidate_count"},
        f"{label}.length_change_plan",
    )
    actual = {
        "length_change_supported": _as_bool(impact.get("length_change_supported"), f"{label}.length_change_supported"),
        "affected_offset_candidate_count": _as_int(
            impact.get("affected_offset_candidate_count"),
            f"{label}.affected_offset_candidate_count",
        ),
        "length_change_plan": {
            "enabled": _as_bool(plan.get("enabled"), f"{label}.length_change_plan.enabled"),
            "kind": _as_string(plan.get("kind"), f"{label}.length_change_plan.kind"),
            "tail_only": _as_bool(plan.get("tail_only"), f"{label}.length_change_plan.tail_only"),
            "downstream_byte_count": _as_int(
                plan.get("downstream_byte_count"),
                f"{label}.length_change_plan.downstream_byte_count",
            ),
            "affected_offset_candidate_count": _as_int(
                plan.get("affected_offset_candidate_count"),
                f"{label}.length_change_plan.affected_offset_candidate_count",
            ),
        },
        "reason": _as_string(impact.get("reason"), f"{label}.reason"),
    }
    if actual != dict(expected):
        raise PrefabEditJsonError("Prefab edit JSON resize impact evidence does not match the selected prefab.")


def _length_change_blocked_message(label: str, slot_length: int, replacement_length: int, impact: Mapping[str, Any]) -> str:
    return (
        f"{label} must keep the same byte length in V1 "
        f"({slot_length} byte slot, replacement is {replacement_length} byte(s)); "
        f"{impact.get('reason')}"
    )


def _placement_fields_document(data: bytes, decoded: Any | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefab = decoded or decode_prefab(data)
    for field in inspect_prefab_attachment_profile_fields(data):
        if field.field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            continue
        rows.append(
            {
                "row_index": len(rows),
                "field_name": field.field_name,
                "length_offset": field.length_offset,
                "value_offset": field.value_offset,
                "byte_length": field.byte_length,
                "text": field.value,
                "value": field.value,
                "resize_impact": _resize_impact_document(prefab, field.value_offset + field.byte_length),
            }
        )
    return rows


def _role_set(roles: Sequence[str]) -> set[str]:
    return {str(role or "").strip().lower() for role in roles if str(role or "").strip()}


def _is_exact_layout_string_field(decoded: Any, field: Any) -> bool:
    field_start = int(field.offset)
    field_end = field_start + 4 + int(field.length)
    return any(
        span.kind == "string_field"
        and int(span.field_index) == int(field.index)
        and int(span.start) == field_start
        and int(span.end) == field_end
        for span in decoded.layout.spans
    )


def _resource_reference_rows_document(decoded: Any, roles: Sequence[str]) -> list[dict[str, Any]]:
    allowed_roles = _role_set(roles)
    rows: list[dict[str, Any]] = []
    for reference in decoded.references:
        if reference.role not in allowed_roles:
            continue
        if not _is_exact_layout_string_field(decoded, reference.field):
            continue
        text = _normalize_path(reference.text)
        rows.append(
            {
                "row_index": len(rows),
                "field_index": reference.field.index,
                "offset": reference.field.offset,
                "byte_length": reference.field.length,
                "role": reference.role,
                "extension": reference.extension,
                "text": text,
                "value": text,
                "resize_impact": _resize_impact_document(
                    decoded,
                    reference.field.offset + 4 + reference.field.length,
                ),
            }
        )
    return rows


def _resize_readiness_document(
    resource_rows: Sequence[Mapping[str, Any]],
    placement_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    editable_row_count = len(resource_rows) + len(placement_rows)
    impacted_row_count = 0
    affected_offset_candidate_rows = 0
    for row in [*resource_rows, *placement_rows]:
        impact = row.get("resize_impact")
        if not isinstance(impact, Mapping):
            continue
        raw_count = impact.get("affected_offset_candidate_count")
        if not isinstance(raw_count, int) or isinstance(raw_count, bool):
            continue
        affected_offset_candidate_rows += raw_count
        if raw_count:
            impacted_row_count += 1
    reason = (
        "Length-changing import is blocked; editable rows would require "
        f"rebuilding {affected_offset_candidate_rows} preserved-byte offset candidate(s)."
        if affected_offset_candidate_rows
        else "Length-changing import is blocked; count/padding rebuild is still not proven."
    )
    return {
        "length_changing_import_ready": False,
        "editable_row_count": editable_row_count,
        "editable_rows_with_resize_impact": impacted_row_count,
        "affected_offset_candidate_rows": affected_offset_candidate_rows,
        "reason": reason,
    }


def _policy_document(
    data: bytes,
    decoded: Any,
    resource_rows: Sequence[Mapping[str, Any]] | None = None,
    placement_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    resources = (
        list(resource_rows)
        if resource_rows is not None
        else _resource_reference_rows_document(decoded, SUPPORTED_PREFAB_EDIT_ROLES)
    )
    placements = list(placement_rows) if placement_rows is not None else _placement_fields_document(data, decoded)
    return {
        "edit_mode": "same_length_resource_companion_and_placement_fields_only",
        "resizing_supported": False,
        "length_changing_rebuild_supported": False,
        "resize_readiness": _resize_readiness_document(resources, placements),
        "layout_no_edit_rebuild_proven": bool(decoded.layout.fully_accounted),
        "same_length_resource_reference_edits": bool(resources),
        "same_length_placement_field_edits": bool(placements),
        "transform_value_editing_supported": False,
        "array_resizing_supported": False,
    }


def build_prefab_edit_document(
    data: bytes,
    virtual_path: str = "",
    *,
    roles: Sequence[str] = SUPPORTED_PREFAB_EDIT_ROLES,
) -> dict[str, Any]:
    payload = bytes(data or b"")
    decoded = decode_prefab(payload)
    rows = _resource_reference_rows_document(decoded, roles)
    placement_rows = _placement_fields_document(payload, decoded)
    return {
        "format": PREFAB_EDIT_JSON_FORMAT,
        "version": PREFAB_EDIT_JSON_VERSION,
        "source": {
            "path": _normalize_path(virtual_path),
            "sha256": _sha256_hex(payload),
            "byte_length": len(payload),
        },
        "policy": _policy_document(payload, decoded, rows, placement_rows),
        "structure": {
            "header": _header_document(payload, decoded),
            "layout": _layout_document(decoded),
            "member_declarations": _member_declarations_document(payload, decoded),
            "offset_candidates": _offset_candidates_document(decoded),
        },
        "declared_fields": list(decoded.declared_fields),
        "editable": {
            "resource_references": rows,
            "placement_fields": placement_rows,
        },
    }


def dumps_prefab_edit_json(data: bytes, virtual_path: str = "") -> str:
    return json.dumps(build_prefab_edit_document(data, virtual_path), indent=2)


def _validate_source_identity(data: bytes, document: Mapping[str, Any], virtual_path: str = "") -> None:
    source = _as_mapping(document.get("source"), "source")
    _require_keys(source, {"path", "sha256", "byte_length"}, "source")
    expected_length = _as_int(source.get("byte_length"), "source.byte_length")
    if expected_length != len(data):
        raise PrefabEditJsonError("Prefab edit JSON source byte length does not match the selected prefab.")
    expected_sha = _as_string(source.get("sha256"), "source.sha256")
    if expected_sha.lower() != _sha256_hex(data):
        raise PrefabEditJsonError("Prefab edit JSON source SHA-256 does not match the selected prefab.")
    if virtual_path:
        document_path = _normalize_path(_as_string(source.get("path"), "source.path")).casefold()
        selected_path = _normalize_path(virtual_path).casefold()
        if document_path and document_path != selected_path:
            raise PrefabEditJsonError("Prefab edit JSON source path does not match the selected prefab.")


def _current_reference_keys_and_counts(
    data: bytes,
    roles: Sequence[str],
) -> tuple[set[tuple[int, int, int, str, str, str]], dict[str, int]]:
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
        keys.add(
            (
                reference.field.index,
                reference.field.offset,
                reference.field.length,
                reference.role,
                reference.extension,
                text,
            )
        )
        counts[text] = counts.get(text, 0) + 1
    return keys, counts


def _current_placement_keys(data: bytes) -> set[tuple[str, int, int, int, str]]:
    keys: set[tuple[str, int, int, int, str]] = set()
    for field in inspect_prefab_attachment_profile_fields(data):
        if field.field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            continue
        keys.add((field.field_name, field.length_offset, field.value_offset, field.byte_length, field.value))
    return keys


def _validate_resize_readiness(value: Any) -> dict[str, Any]:
    readiness = _as_mapping(value, "policy.resize_readiness")
    _require_keys(
        readiness,
        {
            "length_changing_import_ready",
            "editable_row_count",
            "editable_rows_with_resize_impact",
            "affected_offset_candidate_rows",
            "reason",
        },
        "policy.resize_readiness",
    )
    return {
        "length_changing_import_ready": _as_bool(
            readiness.get("length_changing_import_ready"),
            "policy.resize_readiness.length_changing_import_ready",
        ),
        "editable_row_count": _as_int(
            readiness.get("editable_row_count"),
            "policy.resize_readiness.editable_row_count",
        ),
        "editable_rows_with_resize_impact": _as_int(
            readiness.get("editable_rows_with_resize_impact"),
            "policy.resize_readiness.editable_rows_with_resize_impact",
        ),
        "affected_offset_candidate_rows": _as_int(
            readiness.get("affected_offset_candidate_rows"),
            "policy.resize_readiness.affected_offset_candidate_rows",
        ),
        "reason": _as_string(readiness.get("reason"), "policy.resize_readiness.reason"),
    }


def _validate_policy(data: bytes, document: Mapping[str, Any]) -> None:
    policy = _as_mapping(document.get("policy"), "policy")
    _require_keys(
        policy,
        {
            "edit_mode",
            "resizing_supported",
            "length_changing_rebuild_supported",
            "resize_readiness",
            "layout_no_edit_rebuild_proven",
            "same_length_resource_reference_edits",
            "same_length_placement_field_edits",
            "transform_value_editing_supported",
            "array_resizing_supported",
        },
        "policy",
    )
    edit_mode = _as_string(policy.get("edit_mode"), "policy.edit_mode")
    if edit_mode != "same_length_resource_companion_and_placement_fields_only":
        raise PrefabEditJsonError("Prefab edit JSON uses an unsupported edit mode.")
    if _as_bool(policy.get("resizing_supported"), "policy.resizing_supported"):
        raise PrefabEditJsonError("Prefab edit JSON resizing is not supported in V1.")
    if _as_bool(policy.get("length_changing_rebuild_supported"), "policy.length_changing_rebuild_supported"):
        raise PrefabEditJsonError("Prefab edit JSON length-changing rebuild is not supported in V1.")
    if _as_bool(policy.get("transform_value_editing_supported"), "policy.transform_value_editing_supported"):
        raise PrefabEditJsonError("Prefab edit JSON transform value editing is not supported in V1.")
    if _as_bool(policy.get("array_resizing_supported"), "policy.array_resizing_supported"):
        raise PrefabEditJsonError("Prefab edit JSON array resizing is not supported in V1.")
    decoded = decode_prefab(data)
    expected = _policy_document(data, decoded)
    actual = {
        "edit_mode": edit_mode,
        "resizing_supported": False,
        "length_changing_rebuild_supported": False,
        "resize_readiness": _validate_resize_readiness(policy.get("resize_readiness")),
        "layout_no_edit_rebuild_proven": _as_bool(policy.get("layout_no_edit_rebuild_proven"), "policy.layout_no_edit_rebuild_proven"),
        "same_length_resource_reference_edits": _as_bool(policy.get("same_length_resource_reference_edits"), "policy.same_length_resource_reference_edits"),
        "same_length_placement_field_edits": _as_bool(policy.get("same_length_placement_field_edits"), "policy.same_length_placement_field_edits"),
        "transform_value_editing_supported": False,
        "array_resizing_supported": False,
    }
    if actual != expected:
        raise PrefabEditJsonError("Prefab edit JSON policy evidence does not match the selected prefab.")


def _validate_structure(data: bytes, document: Mapping[str, Any]) -> None:
    structure = _as_mapping(document.get("structure"), "structure")
    _require_keys(structure, {"header", "layout", "member_declarations", "offset_candidates"}, "structure")
    header = _as_mapping(structure.get("header"), "structure.header")
    _require_keys(
        header,
        {"magic", "version", "prefix_byte_length", "first_string_offset", "prefix_sha256"},
        "structure.header",
    )
    decoded = decode_prefab(data)
    actual = _header_document(data, decoded)
    expected = {
        "magic": _as_int(header.get("magic"), "structure.header.magic"),
        "version": _as_int(header.get("version"), "structure.header.version"),
        "prefix_byte_length": _as_int(header.get("prefix_byte_length"), "structure.header.prefix_byte_length"),
        "first_string_offset": _as_int(header.get("first_string_offset"), "structure.header.first_string_offset"),
        "prefix_sha256": _as_string(header.get("prefix_sha256"), "structure.header.prefix_sha256").lower(),
    }
    if expected != actual:
        raise PrefabEditJsonError("Prefab edit JSON header evidence does not match the selected prefab.")
    layout = _as_mapping(structure.get("layout"), "structure.layout")
    _require_keys(
        layout,
        {
            "byte_length",
            "span_count",
            "string_span_count",
            "preserved_span_count",
            "parsed_string_byte_count",
            "preserved_byte_count",
            "accounted_byte_count",
            "fully_accounted",
            "spans",
        },
        "structure.layout",
    )
    raw_spans = _as_list(layout.get("spans"), "structure.layout.spans")
    spans: list[dict[str, Any]] = []
    for expected_span_index, raw_span in enumerate(raw_spans):
        span = _as_mapping(raw_span, "structure.layout.spans[]")
        _require_keys(span, {"span_index", "start", "end", "kind", "field_index"}, "structure.layout.spans[]")
        span_index = _as_int(span.get("span_index"), "structure.layout.spans[].span_index")
        if span_index != expected_span_index:
            raise PrefabEditJsonError("Prefab edit JSON layout span index does not match its position.")
        spans.append(
            {
                "span_index": span_index,
                "start": _as_int(span.get("start"), "structure.layout.spans[].start"),
                "end": _as_int(span.get("end"), "structure.layout.spans[].end"),
                "kind": _as_string(span.get("kind"), "structure.layout.spans[].kind"),
                "field_index": _as_int(span.get("field_index"), "structure.layout.spans[].field_index"),
            }
        )
    expected_layout = {
        "byte_length": _as_int(layout.get("byte_length"), "structure.layout.byte_length"),
        "span_count": _as_int(layout.get("span_count"), "structure.layout.span_count"),
        "string_span_count": _as_int(layout.get("string_span_count"), "structure.layout.string_span_count"),
        "preserved_span_count": _as_int(layout.get("preserved_span_count"), "structure.layout.preserved_span_count"),
        "parsed_string_byte_count": _as_int(layout.get("parsed_string_byte_count"), "structure.layout.parsed_string_byte_count"),
        "preserved_byte_count": _as_int(layout.get("preserved_byte_count"), "structure.layout.preserved_byte_count"),
        "accounted_byte_count": _as_int(layout.get("accounted_byte_count"), "structure.layout.accounted_byte_count"),
        "fully_accounted": _as_bool(layout.get("fully_accounted"), "structure.layout.fully_accounted"),
        "spans": spans,
    }
    if expected_layout != _layout_document(decoded):
        raise PrefabEditJsonError("Prefab edit JSON layout evidence does not match the selected prefab.")
    raw_members = _as_list(structure.get("member_declarations"), "structure.member_declarations")
    members: list[dict[str, Any]] = []
    for raw_member in raw_members:
        member = _as_mapping(raw_member, "structure.member_declarations[]")
        _require_keys(
            member,
            {
                "member_index",
                "name_field_index",
                "type_field_index",
                "name_offset",
                "type_offset",
                "descriptor_offset",
                "descriptor_byte_length",
                "descriptor_words_le_u16",
                "descriptor_kind",
                "is_array",
                "is_reference",
                "is_transform",
                "array_stride_hint",
                "array_count_hint",
                "descriptor_sha256",
                "name",
                "type",
            },
            "structure.member_declarations[]",
        )
        members.append(
            {
                "member_index": _as_int(member.get("member_index"), "structure.member_declarations[].member_index"),
                "name_field_index": _as_int(member.get("name_field_index"), "structure.member_declarations[].name_field_index"),
                "type_field_index": _as_int(member.get("type_field_index"), "structure.member_declarations[].type_field_index"),
                "name_offset": _as_int(member.get("name_offset"), "structure.member_declarations[].name_offset"),
                "type_offset": _as_int(member.get("type_offset"), "structure.member_declarations[].type_offset"),
                "descriptor_offset": _as_int(member.get("descriptor_offset"), "structure.member_declarations[].descriptor_offset"),
                "descriptor_byte_length": _as_int(member.get("descriptor_byte_length"), "structure.member_declarations[].descriptor_byte_length"),
                "descriptor_words_le_u16": [
                    _as_int(value, "structure.member_declarations[].descriptor_words_le_u16[]")
                    for value in _as_list(
                        member.get("descriptor_words_le_u16"),
                        "structure.member_declarations[].descriptor_words_le_u16",
                    )
                ],
                "descriptor_kind": _as_string(member.get("descriptor_kind"), "structure.member_declarations[].descriptor_kind"),
                "is_array": _as_bool(member.get("is_array"), "structure.member_declarations[].is_array"),
                "is_reference": _as_bool(member.get("is_reference"), "structure.member_declarations[].is_reference"),
                "is_transform": _as_bool(member.get("is_transform"), "structure.member_declarations[].is_transform"),
                "array_stride_hint": _as_int(
                    member.get("array_stride_hint"),
                    "structure.member_declarations[].array_stride_hint",
                ),
                "array_count_hint": _as_int(
                    member.get("array_count_hint"),
                    "structure.member_declarations[].array_count_hint",
                ),
                "descriptor_sha256": _as_string(member.get("descriptor_sha256"), "structure.member_declarations[].descriptor_sha256"),
                "name": _as_string(member.get("name"), "structure.member_declarations[].name"),
                "type": _as_string(member.get("type"), "structure.member_declarations[].type"),
            }
        )
    if members != _member_declarations_document(data, decoded):
        raise PrefabEditJsonError("Prefab edit JSON member declarations do not match the selected prefab.")
    raw_offset_candidates = _as_list(structure.get("offset_candidates"), "structure.offset_candidates")
    offset_candidates: list[dict[str, Any]] = []
    for expected_row_index, raw_candidate in enumerate(raw_offset_candidates):
        candidate = _as_mapping(raw_candidate, "structure.offset_candidates[]")
        _require_keys(
            candidate,
            {
                "row_index",
                "offset",
                "value",
                "target_kind",
                "target_field_index",
                "candidate_offset_mod4",
                "target_value_mod4",
            },
            "structure.offset_candidates[]",
        )
        row_index = _as_int(candidate.get("row_index"), "structure.offset_candidates[].row_index")
        if row_index != expected_row_index:
            raise PrefabEditJsonError("Prefab edit JSON offset candidate row index does not match its position.")
        offset_candidates.append(
            {
                "row_index": row_index,
                "offset": _as_int(candidate.get("offset"), "structure.offset_candidates[].offset"),
                "value": _as_int(candidate.get("value"), "structure.offset_candidates[].value"),
                "target_kind": _as_string(candidate.get("target_kind"), "structure.offset_candidates[].target_kind"),
                "target_field_index": _as_int(
                    candidate.get("target_field_index"),
                    "structure.offset_candidates[].target_field_index",
                ),
                "candidate_offset_mod4": _as_int(
                    candidate.get("candidate_offset_mod4"),
                    "structure.offset_candidates[].candidate_offset_mod4",
                ),
                "target_value_mod4": _as_int(
                    candidate.get("target_value_mod4"),
                    "structure.offset_candidates[].target_value_mod4",
                ),
            }
        )
    if offset_candidates != _offset_candidates_document(decoded):
        raise PrefabEditJsonError("Prefab edit JSON offset candidates do not match the selected prefab.")


def _validate_declared_fields(data: bytes, document: Mapping[str, Any]) -> None:
    raw_fields = _as_list(document.get("declared_fields"), "declared_fields")
    declared_fields = tuple(_as_string(value, "declared_fields[]") for value in raw_fields)
    if declared_fields != tuple(decode_prefab(data).declared_fields):
        raise PrefabEditJsonError("Prefab edit JSON declared fields do not match the selected prefab.")


def _validate_placement_rows(data: bytes, rows: list[Any], decoded: Any | None = None) -> dict[str, str]:
    prefab = decoded or decode_prefab(data)
    current_keys = _current_placement_keys(data)
    seen_keys: set[tuple[str, int, int, int, str]] = set()
    replacements: dict[str, str] = {}
    for expected_row_index, raw_row in enumerate(rows):
        row = _as_mapping(raw_row, "editable.placement_fields[]")
        _require_keys(
            row,
            {"row_index", "field_name", "length_offset", "value_offset", "byte_length", "text", "value", "resize_impact"},
            "editable.placement_fields[]",
        )
        row_index = _as_int(row.get("row_index"), "editable.placement_fields[].row_index")
        if row_index != expected_row_index:
            raise PrefabEditJsonError("Prefab edit JSON placement row index does not match its position.")
        field_name = _as_string(row.get("field_name"), "editable.placement_fields[].field_name")
        if field_name not in SUPPORTED_PREFAB_PLACEMENT_FIELDS:
            raise PrefabEditJsonError(f"Unsupported prefab placement field: {field_name}.")
        length_offset = _as_int(row.get("length_offset"), "editable.placement_fields[].length_offset")
        value_offset = _as_int(row.get("value_offset"), "editable.placement_fields[].value_offset")
        byte_length = _as_int(row.get("byte_length"), "editable.placement_fields[].byte_length")
        original = _as_string(row.get("text"), "editable.placement_fields[].text").strip()
        value = _as_string(row.get("value"), "editable.placement_fields[].value").strip()
        key = (field_name, length_offset, value_offset, byte_length, original)
        if key not in current_keys:
            raise PrefabEditJsonError("Prefab edit JSON placement row does not match the selected prefab.")
        if key in seen_keys:
            raise PrefabEditJsonError("Prefab edit JSON contains a duplicate placement row.")
        seen_keys.add(key)
        resize_impact = _resize_impact_document(prefab, value_offset + byte_length)
        _validate_resize_impact(
            row.get("resize_impact"),
            resize_impact,
            "editable.placement_fields[].resize_impact",
        )
        if value == original:
            continue
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PrefabEditJsonError("Prefab placement replacement must be ASCII in V1.") from exc
        if len(encoded) != byte_length:
            raise PrefabEditJsonError(
                _length_change_blocked_message("Prefab placement replacement", byte_length, len(encoded), resize_impact)
            )
        replacements[field_name] = value
    if seen_keys != current_keys:
        raise PrefabEditJsonError("Prefab edit JSON placement rows do not match the selected prefab.")
    return replacements


def _editable_rows(document: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    editable = _as_mapping(document.get("editable"), "editable")
    _require_keys(editable, {"resource_references", "placement_fields"}, "editable")
    return (
        _as_list(editable.get("resource_references"), "editable.resource_references"),
        _as_list(editable.get("placement_fields"), "editable.placement_fields"),
    )


def apply_prefab_edit_document(
    data: bytes,
    document: Mapping[str, Any],
    *,
    virtual_path: str = "",
    roles: Sequence[str] = SUPPORTED_PREFAB_EDIT_ROLES,
    allow_experimental_length_change: bool = False,
) -> bytes:
    payload = bytes(data or b"")
    root = _as_mapping(document, "document")
    if root.get("format") != PREFAB_EDIT_JSON_FORMAT or root.get("version") != PREFAB_EDIT_JSON_VERSION:
        raise PrefabEditJsonError(f"Prefab edit JSON must use {PREFAB_EDIT_JSON_FORMAT}.")
    _require_keys(root, {"format", "version", "source", "policy", "structure", "declared_fields", "editable"}, "document")
    _validate_source_identity(payload, root, virtual_path=virtual_path)
    _validate_policy(payload, root)
    _validate_structure(payload, root)
    _validate_declared_fields(payload, root)

    rows, placement_rows = _editable_rows(root)
    allowed_roles = {str(role or "").strip().lower() for role in roles if str(role or "").strip()}
    current_keys, current_counts_by_text = _current_reference_keys_and_counts(payload, tuple(allowed_roles))
    decoded_for_resize = decode_prefab(payload)
    same_length_replacements_by_text: dict[str, str] = {}
    resized_replacements_by_field_index: dict[int, str] = {}
    row_values_by_text: dict[str, set[str]] = {}
    row_counts_by_text: dict[str, int] = {}
    seen_keys: set[tuple[int, int, int, str, str, str]] = set()

    for expected_row_index, raw_row in enumerate(rows):
        row = _as_mapping(raw_row, "editable.resource_references[]")
        _require_keys(
            row,
            {"row_index", "field_index", "offset", "byte_length", "role", "extension", "text", "value", "resize_impact"},
            "editable.resource_references[]",
        )
        row_index = _as_int(row.get("row_index"), "row_index")
        if row_index != expected_row_index:
            raise PrefabEditJsonError("Prefab edit JSON row index does not match its position.")
        field_index = _as_int(row.get("field_index"), "field_index")
        offset = _as_int(row.get("offset"), "offset")
        byte_length = _as_int(row.get("byte_length"), "byte_length")
        role = _as_string(row.get("role"), "role").strip().lower()
        extension = _as_string(row.get("extension"), "extension").strip().lower()
        original = _normalize_path(_as_string(row.get("text"), "text"))
        value = _normalize_path(_as_string(row.get("value"), "value"))
        if role not in allowed_roles:
            raise PrefabEditJsonError(f"Unsupported prefab edit role: {role}.")
        key = (field_index, offset, byte_length, role, extension, original)
        if key not in current_keys:
            raise PrefabEditJsonError("Prefab edit JSON row does not match the selected prefab.")
        if key in seen_keys:
            raise PrefabEditJsonError("Prefab edit JSON contains a duplicate reference row.")
        seen_keys.add(key)
        resize_impact = _resize_impact_document(decoded_for_resize, offset + 4 + byte_length)
        _validate_resize_impact(
            row.get("resize_impact"),
            resize_impact,
            "editable.resource_references[].resize_impact",
        )
        row_values_by_text.setdefault(original, set()).add(value)
        row_counts_by_text[original] = row_counts_by_text.get(original, 0) + 1
        if value == original:
            continue
        _validate_resource_replacement_path(original, value, role, extension)
        replacement_length = len(value.encode("utf-8"))
        if replacement_length != byte_length:
            if not allow_experimental_length_change:
                raise PrefabEditJsonError(
                    _length_change_blocked_message("Prefab replacement", byte_length, replacement_length, resize_impact)
                )
            resized_replacements_by_field_index[field_index] = value
        previous = same_length_replacements_by_text.get(original)
        if previous is not None and previous != value:
            raise PrefabEditJsonError("Duplicate prefab references must use the same replacement value.")
        if replacement_length == byte_length:
            same_length_replacements_by_text[original] = value

    if seen_keys != current_keys:
        raise PrefabEditJsonError("Prefab edit JSON reference rows do not match the selected prefab.")

    changed_originals = {
        original
        for original, values in row_values_by_text.items()
        if values and values != {original}
    }
    for original in changed_originals:
        if row_counts_by_text.get(original, 0) != current_counts_by_text.get(original, 0):
            raise PrefabEditJsonError("Duplicate prefab references must all be present before editing.")
        values = row_values_by_text.get(original, set())
        replacement = next(iter(values)) if len(values) == 1 else ""
        if values != {replacement}:
            raise PrefabEditJsonError("Duplicate prefab references must be edited consistently.")

    placement_replacements = _validate_placement_rows(payload, placement_rows, decoded_for_resize)
    patched = payload
    if placement_replacements:
        try:
            patched = build_prefab_attachment_profile_patch(
                patched,
                attached_socket_name=placement_replacements.get("_attachedSocketName", ""),
                pivot_socket_name=placement_replacements.get("_pivotSocketName", ""),
                part_name=placement_replacements.get("_partName", ""),
            ).data
        except ValueError as exc:
            raise PrefabEditJsonError(str(exc)) from exc
    if same_length_replacements_by_text:
        patched = build_prefab_resource_path_patch(
            patched,
            same_length_replacements_by_text,
            roles=tuple(allowed_roles),
        ).data
    if resized_replacements_by_field_index:
        try:
            patched = rebuild_prefab_resized_strings(patched, resized_replacements_by_field_index)
        except ValueError as exc:
            raise PrefabEditJsonError(str(exc)) from exc
    return patched


def rebuild_prefab_no_edit_from_edit_document(
    data: bytes,
    document: Mapping[str, Any],
    *,
    virtual_path: str = "",
) -> bytes:
    payload = bytes(data or b"")
    root = _as_mapping(document, "document")
    if root.get("format") != PREFAB_EDIT_JSON_FORMAT or root.get("version") != PREFAB_EDIT_JSON_VERSION:
        raise PrefabEditJsonError(f"Prefab edit JSON must use {PREFAB_EDIT_JSON_FORMAT}.")
    _require_keys(root, {"format", "version", "source", "policy", "structure", "declared_fields", "editable"}, "document")
    _validate_source_identity(payload, root, virtual_path=virtual_path)
    _validate_policy(payload, root)
    _validate_structure(payload, root)
    _validate_declared_fields(payload, root)
    _editable_rows(root)
    if apply_prefab_edit_document(payload, root, virtual_path=virtual_path) != payload:
        raise PrefabEditJsonError("Prefab edit JSON no-edit rebuild cannot contain editable value changes.")
    layout = _as_mapping(_as_mapping(root.get("structure"), "structure").get("layout"), "structure.layout")
    spans = _as_list(layout.get("spans"), "structure.layout.spans")
    rebuilt = bytearray()
    cursor = 0
    for raw_span in spans:
        span = _as_mapping(raw_span, "structure.layout.spans[]")
        start = _as_int(span.get("start"), "structure.layout.spans[].start")
        end = _as_int(span.get("end"), "structure.layout.spans[].end")
        kind = _as_string(span.get("kind"), "structure.layout.spans[].kind")
        if start != cursor:
            raise PrefabEditJsonError("Prefab edit JSON layout spans have a gap or overlap.")
        if start < 0 or end < start or end > len(payload):
            raise PrefabEditJsonError("Prefab edit JSON layout span points outside the payload.")
        if kind not in {"preserved", "string_field"}:
            raise PrefabEditJsonError(f"Unsupported prefab layout span kind: {kind}.")
        rebuilt.extend(payload[start:end])
        cursor = end
    if cursor != len(payload) or len(rebuilt) != _as_int(layout.get("byte_length"), "structure.layout.byte_length"):
        raise PrefabEditJsonError("Prefab edit JSON layout rebuild did not account for the full payload.")
    return bytes(rebuilt)


def apply_prefab_edit_json(
    data: bytes,
    document_text: str,
    *,
    virtual_path: str = "",
    roles: Sequence[str] = SUPPORTED_PREFAB_EDIT_ROLES,
) -> bytes:
    try:
        document = json.loads(document_text)
    except json.JSONDecodeError as exc:
        raise PrefabEditJsonError("Prefab edit JSON is not valid JSON.") from exc
    return apply_prefab_edit_document(
        data,
        _as_mapping(document, "document"),
        virtual_path=virtual_path,
        roles=roles,
    )


__all__ = [
    "PREFAB_EDIT_JSON_FORMAT",
    "PREFAB_EDIT_JSON_VERSION",
    "SUPPORTED_PREFAB_EDIT_ROLES",
    "SUPPORTED_PREFAB_PLACEMENT_FIELDS",
    "PrefabEditJsonError",
    "apply_prefab_edit_document",
    "apply_prefab_edit_json",
    "build_prefab_edit_document",
    "dumps_prefab_edit_json",
    "rebuild_prefab_no_edit_from_edit_document",
]
